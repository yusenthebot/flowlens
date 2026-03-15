"""
Trace CRUD route handlers.

Endpoints:
- POST   /v1/traces/ingest
- POST   /v1/traces/import
- GET    /v1/traces
- GET    /v1/traces/errors
- GET    /v1/traces/search
- GET    /v1/traces/{trace_id}
- GET    /v1/traces/{trace_id}/dag
- GET    /v1/traces/{trace_id}/feedback
- POST   /v1/traces/{trace_id}/feedback
- DELETE /v1/traces/{trace_id}
- POST   /v1/traces/batch-delete
- POST   /v1/traces/cleanup
- GET    /v1/traces/diff
- GET    /v1/experiments/diff
"""

from __future__ import annotations

import json
import logging
import random
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from ...analysis.dag_builder import build_causal_dag
from ...analysis.patterns import detect_patterns
from ...analysis.trace_diff import TraceDiff as _TraceDiff
from ..storage import TraceStore
from ..utils import (
    _ALLOWED_IMPORT_DIRS,
    _MAX_ID_LENGTH,
    _MAX_SPANS_PER_INGEST,
    _is_subpath,
    _reconstruct_trace,
    _sanitize_id,
)
from ..validation import validate_trace as _validate_trace

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class TraceIngestRequest(BaseModel):
    """Payload for POST /v1/traces/ingest."""

    trace_id: str = Field(
        ..., min_length=1, max_length=_MAX_ID_LENGTH, description="Unique trace identifier"
    )
    service_name: str = Field("", max_length=_MAX_ID_LENGTH)
    start_time: float = 0
    end_time: float = 0
    duration_ms: float = 0
    total_tokens: int = Field(0, ge=0)
    total_cost_usd: float = Field(0.0, ge=0)
    has_errors: bool = False
    error_count: int = Field(0, ge=0)
    span_count: int = Field(0, ge=0)
    metadata: dict[str, Any] = {}
    spans: list[dict[str, Any]] = Field(default_factory=list, max_length=_MAX_SPANS_PER_INGEST)
    # User/session/experiment context
    user_id: str | None = Field(None, max_length=_MAX_ID_LENGTH)
    session_id: str | None = Field(None, max_length=_MAX_ID_LENGTH)
    experiment: str | None = Field(None, max_length=_MAX_ID_LENGTH)
    tags: dict[str, str] | None = None

    @field_validator("trace_id")
    @classmethod
    def validate_trace_id(cls, v: str) -> str:
        if ".." in v or "\x00" in v:
            raise ValueError("trace_id contains disallowed sequences")
        return v

    @field_validator("service_name")
    @classmethod
    def validate_service_name(cls, v: str) -> str:
        if v and ("\x00" in v or ".." in v):
            raise ValueError("service_name contains disallowed sequences")
        return v


class FeedbackRequest(BaseModel):
    """Payload for POST /v1/traces/{trace_id}/feedback."""

    rating: int = Field(..., ge=1, le=5, description="Rating from 1 (worst) to 5 (best)")
    comment: str | None = Field(None, max_length=4096)
    metadata: dict[str, Any] = {}


class BatchDeleteRequest(BaseModel):
    """Payload for POST /v1/traces/batch-delete."""

    trace_ids: list[str] = Field(
        ...,
        min_length=1,
        max_length=100,
        description="List of trace IDs to delete (max 100 per request)",
    )


class CleanupRequest(BaseModel):
    """Payload for POST /v1/traces/cleanup."""

    days: int = Field(30, ge=1, description="Delete traces older than this many days")


class TraceListResponse(BaseModel):
    traces: list[dict[str, Any]]
    total: int
    limit: int
    offset: int


def create_traces_router(
    store: TraceStore,
    ws_manager: Any,
    alert_engine: Any,
) -> APIRouter:
    """Create and return the traces router.

    Args:
        store: TraceStore instance for data persistence.
        ws_manager: ConnectionManager for WebSocket broadcasts.
        alert_engine: AlertEngine for evaluating alert rules.
    """
    router = APIRouter()

    @router.post("/v1/traces/ingest", status_code=201)
    async def ingest_trace(req: TraceIngestRequest) -> dict[str, str]:
        """Receive and persist trace data; broadcast to WebSocket subscribers."""
        # Enforce spans list size limit (belt-and-suspenders beyond Pydantic)
        if len(req.spans) > _MAX_SPANS_PER_INGEST:
            raise HTTPException(
                400,
                f"spans list exceeds maximum allowed size of {_MAX_SPANS_PER_INGEST}",
            )

        payload = req.model_dump()

        # Structural validation: orphan refs, duplicate span_ids, cycle detection
        is_valid, validation_error = _validate_trace(payload, require_spans=False)
        if not is_valid:
            raise HTTPException(422, f"Trace validation failed: {validation_error}")

        try:
            store.save_trace(payload)
            # Periodically check if cleanup is needed (~1% of ingests)
            # to prevent database from growing unbounded
            if random.random() < 0.01:
                try:
                    store.cleanup_excess_traces()
                except Exception as cleanup_err:
                    logger.debug("Background cleanup check failed: %s", cleanup_err)
        except Exception:
            logger.exception("Failed to save trace %s", req.trace_id[:32])
            raise HTTPException(500, "Failed to persist trace data")

        # Broadcast lightweight summary (not full spans) to WS clients
        if ws_manager.connection_count:
            summary = {
                k: payload[k]
                for k in (
                    "trace_id",
                    "service_name",
                    "start_time",
                    "end_time",
                    "duration_ms",
                    "total_tokens",
                    "total_cost_usd",
                    "has_errors",
                    "error_count",
                    "span_count",
                )
            }
            await ws_manager.broadcast({"event": "trace_ingested", "data": summary})

        # Evaluate alert rules (non-blocking; errors are swallowed)
        try:
            fired_alerts = await alert_engine.check_trace(payload)
            for alert in fired_alerts:
                try:
                    store.save_alert(alert.to_dict())
                except Exception as ae:
                    logger.debug("Failed to persist alert: %s", ae)
        except Exception as alert_err:
            logger.debug("Alert evaluation failed: %s", alert_err)

        return {"status": "ok", "trace_id": req.trace_id}

    @router.post("/v1/traces/import", status_code=201)
    async def import_jsonl(file_path: str) -> dict[str, Any]:
        """
        Bulk-import traces from a JSONL file.

        The ``file_path`` parameter is restricted to pre-approved directories
        defined in ``_ALLOWED_IMPORT_DIRS``.  When that list is empty (the
        default), the endpoint is effectively disabled for security.
        """
        # Resolve the path and check for path-traversal attacks
        try:
            resolved = Path(file_path).resolve()
        except Exception:
            raise HTTPException(400, "Invalid file path")

        # Check null bytes and traversal sequences in the raw input
        if "\x00" in file_path or ".." in file_path:
            raise HTTPException(400, "Invalid file path: disallowed sequences detected")

        # If allowed directories are configured, enforce membership
        if _ALLOWED_IMPORT_DIRS:
            if not any(_is_subpath(resolved, allowed) for allowed in _ALLOWED_IMPORT_DIRS):
                raise HTTPException(
                    403,
                    "Access denied: file_path is outside the allowed directories",
                )
        else:
            # No allowed directories configured — endpoint is disabled
            raise HTTPException(
                403,
                "Import endpoint is disabled. Configure _ALLOWED_IMPORT_DIRS to enable it.",
            )

        if not resolved.exists():
            raise HTTPException(404, "File not found")

        if not resolved.is_file():
            raise HTTPException(400, "Path does not point to a regular file")

        count = 0
        errors = 0
        try:
            with open(resolved) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        trace_data = json.loads(line)
                        is_valid, val_err = _validate_trace(trace_data, require_spans=False)
                        if not is_valid:
                            logger.debug("Import: skipping invalid trace: %s", val_err)
                            errors += 1
                            continue
                        store.save_trace(trace_data)
                        count += 1
                    except Exception as e:
                        errors += 1
                        logger.warning("Failed to import trace line: %s", e)
        except OSError:
            logger.exception("Failed to read import file")
            raise HTTPException(500, "Failed to read the specified file")

        return {"imported": count, "errors": errors}

    # NOTE: specific path segments (/errors, /search, /cleanup) MUST come
    #       before the generic /{trace_id} route to avoid being shadowed.

    @router.get("/v1/traces/errors")
    async def list_error_traces(
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ) -> TraceListResponse:
        """Return only traces that contain at least one error span."""
        try:
            traces = store.get_error_traces(limit=limit, offset=offset)
        except Exception:
            logger.exception("Failed to list error traces")
            raise HTTPException(500, "Failed to retrieve error traces")
        return TraceListResponse(traces=traces, total=len(traces), limit=limit, offset=offset)

    @router.get("/v1/traces/search")
    async def search_traces(
        q: str = Query(..., min_length=1, max_length=200, description="Search term"),
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ) -> TraceListResponse:
        """Full-text search across trace service_name and span name / error_message."""
        q_stripped = q.strip()
        if not q_stripped:
            raise HTTPException(400, "Search query must not be blank")

        try:
            traces = store.search_traces(query=q_stripped, limit=limit, offset=offset)
        except Exception:
            logger.exception("Search failed for query: %s", q_stripped[:50])
            raise HTTPException(500, "Search failed")
        return TraceListResponse(traces=traces, total=len(traces), limit=limit, offset=offset)

    @router.post("/v1/traces/batch-delete", status_code=200)
    async def batch_delete_traces(req: BatchDeleteRequest) -> dict[str, Any]:
        """Delete multiple traces at once."""
        # Sanitise each trace ID
        sanitised: list[str] = []
        for tid in req.trace_ids:
            sanitised.append(_sanitize_id(tid, "trace_id"))

        try:
            deleted = store.batch_delete_traces(sanitised)
        except Exception:
            logger.exception("Batch delete failed")
            raise HTTPException(500, "Batch delete operation failed")
        return {"deleted": deleted, "requested": len(sanitised)}

    @router.post("/v1/traces/cleanup", status_code=200)
    async def cleanup_traces(req: CleanupRequest) -> dict[str, Any]:
        """Delete all traces older than ``req.days`` days."""
        try:
            deleted = store.cleanup_old_traces(days=req.days)
        except Exception:
            logger.exception("Cleanup failed")
            raise HTTPException(500, "Cleanup operation failed")
        return {"deleted": deleted, "days": req.days}

    @router.get("/v1/traces/diff")
    async def trace_diff(
        a: str = Query(..., description="Trace ID A (baseline)"),
        b: str = Query(..., description="Trace ID B (comparison)"),
    ) -> dict[str, Any]:
        """Compare two traces by ID and return a full diff result."""
        _sanitize_id(a, "trace_id_a")
        _sanitize_id(b, "trace_id_b")
        try:
            data_a = store.get_trace(a)
            data_b = store.get_trace(b)
        except Exception:
            logger.exception("Failed to retrieve traces for diff")
            raise HTTPException(500, "Failed to retrieve traces")
        if not data_a:
            raise HTTPException(404, f"Trace '{a}' not found")
        if not data_b:
            raise HTTPException(404, f"Trace '{b}' not found")
        try:
            trace_a = _reconstruct_trace(data_a)
            trace_b = _reconstruct_trace(data_b)
            differ = _TraceDiff()
            result = differ.diff(trace_a, trace_b)
            return result.to_dict()
        except Exception:
            logger.exception("Failed to diff traces %s vs %s", a[:32], b[:32])
            raise HTTPException(500, "Failed to compute trace diff")

    @router.get("/v1/traces")
    async def list_traces(
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        service: str | None = Query(None, max_length=_MAX_ID_LENGTH),
        errors_only: bool = False,
        user_id: str | None = Query(None, max_length=_MAX_ID_LENGTH),
        session_id: str | None = Query(None, max_length=_MAX_ID_LENGTH),
        experiment: str | None = Query(None, max_length=_MAX_ID_LENGTH),
    ) -> TraceListResponse:
        """List traces (paginated). Filter by service, errors, user, session, or experiment."""
        # Sanitize the service filter against path traversal
        if service is not None:
            _sanitize_id(service, "service")
        if user_id is not None:
            _sanitize_id(user_id, "user_id")
        if session_id is not None:
            _sanitize_id(session_id, "session_id")
        if experiment is not None:
            _sanitize_id(experiment, "experiment")

        try:
            traces = store.list_traces(
                limit=limit,
                offset=offset,
                service_name=service,
                has_errors=True if errors_only else None,
                user_id=user_id,
                session_id=session_id,
                experiment=experiment,
            )
        except Exception:
            logger.exception("Failed to list traces")
            raise HTTPException(500, "Failed to retrieve traces")

        # Enrich traces with lightweight span tool summaries for the dashboard.
        # This avoids sending full span data while still enabling tool pills.
        try:
            trace_ids = [t["trace_id"] for t in traces if t.get("span_count", 0) > 0]
            if trace_ids:
                tool_summaries = store.get_span_tool_summaries(trace_ids)
                for t in traces:
                    tid = t["trace_id"]
                    if tid in tool_summaries:
                        t["tool_summary"] = tool_summaries[tid]
        except Exception:
            pass  # Non-critical: tool summaries are a UI convenience

        return TraceListResponse(traces=traces, total=len(traces), limit=limit, offset=offset)

    @router.get("/v1/traces/{trace_id}/dag")
    async def get_trace_dag(trace_id: str) -> dict[str, Any]:
        """Build and return the causal DAG for a trace."""
        _sanitize_id(trace_id, "trace_id")
        try:
            trace_data = store.get_trace(trace_id)
        except Exception:
            logger.exception("Failed to get trace for DAG %s", trace_id[:32])
            raise HTTPException(500, "Failed to retrieve trace")
        if not trace_data:
            raise HTTPException(404, "Trace not found")

        try:
            trace = _reconstruct_trace(trace_data)
            dag = build_causal_dag(trace)
            detect_patterns(trace, dag)
            return dag.to_dict()
        except Exception:
            logger.exception("Failed to build DAG for trace %s", trace_id[:32])
            raise HTTPException(500, "Failed to build causal DAG")

    @router.post("/v1/traces/{trace_id}/feedback", status_code=201)
    async def submit_feedback(trace_id: str, req: FeedbackRequest) -> dict[str, Any]:
        """Submit feedback (rating 1-5, optional comment) for a trace."""
        _sanitize_id(trace_id, "trace_id")
        try:
            feedback_id = store.save_feedback(
                trace_id=trace_id,
                rating=req.rating,
                comment=req.comment,
                metadata=req.metadata,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        except Exception:
            logger.exception("Failed to save feedback for trace %s", trace_id[:32])
            raise HTTPException(500, "Failed to save feedback")
        return {"status": "ok", "trace_id": trace_id, "feedback_id": feedback_id}

    @router.get("/v1/traces/{trace_id}/feedback")
    async def get_trace_feedback(trace_id: str) -> list[dict[str, Any]]:
        """Get all feedback for a specific trace."""
        _sanitize_id(trace_id, "trace_id")
        try:
            return store.get_feedback(trace_id)
        except Exception:
            logger.exception("Failed to get feedback for trace %s", trace_id[:32])
            raise HTTPException(500, "Failed to retrieve feedback")

    @router.get("/v1/traces/{trace_id}")
    async def get_trace(trace_id: str) -> dict[str, Any]:
        """Fetch full trace detail including all spans."""
        _sanitize_id(trace_id, "trace_id")
        try:
            trace = store.get_trace(trace_id)
        except Exception:
            logger.exception("Failed to get trace %s", trace_id[:32])
            raise HTTPException(500, "Failed to retrieve trace")
        if not trace:
            raise HTTPException(404, "Trace not found")
        return trace

    @router.delete("/v1/traces/{trace_id}", status_code=200)
    async def delete_trace(trace_id: str) -> dict[str, str]:
        """Permanently delete a trace and all its spans."""
        _sanitize_id(trace_id, "trace_id")
        try:
            deleted = store.delete_trace(trace_id)
        except Exception:
            logger.exception("Failed to delete trace %s", trace_id[:32])
            raise HTTPException(500, "Failed to delete trace")
        if not deleted:
            raise HTTPException(404, "Trace not found")
        return {"status": "deleted", "trace_id": trace_id}

    return router


def create_experiments_router(store: TraceStore) -> APIRouter:
    """Create and return the experiments router."""
    router = APIRouter()

    @router.get("/v1/experiments/diff")
    async def experiment_diff(
        a: str = Query(..., description="Experiment name A (baseline)"),
        b: str = Query(..., description="Experiment name B (comparison)"),
        limit: int = Query(200, ge=1, le=1000),
    ) -> dict[str, Any]:
        """Compare two experiment groups by name and return aggregate statistics."""
        _sanitize_id(a, "experiment_a")
        _sanitize_id(b, "experiment_b")
        try:
            raw_a = store.list_traces(limit=limit, service_name=a)
            raw_b = store.list_traces(limit=limit, service_name=b)
        except Exception:
            logger.exception("Failed to retrieve experiment traces for diff")
            raise HTTPException(500, "Failed to retrieve experiment traces")
        if not raw_a:
            raise HTTPException(404, f"No traces found for experiment '{a}'")
        if not raw_b:
            raise HTTPException(404, f"No traces found for experiment '{b}'")
        try:
            traces_a = [_reconstruct_trace(t) for t in raw_a]
            traces_b = [_reconstruct_trace(t) for t in raw_b]
            differ = _TraceDiff()
            result = differ.diff_experiments(traces_a, traces_b, name_a=a, name_b=b)
            return result.to_dict()
        except Exception:
            logger.exception("Failed to diff experiments %s vs %s", a[:32], b[:32])
            raise HTTPException(500, "Failed to compute experiment diff")

    return router
