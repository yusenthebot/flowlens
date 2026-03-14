"""
FlowLens API Server — FastAPI application

Endpoints:
- POST   /v1/traces/ingest          — ingest trace data
- POST   /v1/traces/import          — bulk import from JSONL file
- GET    /v1/traces                 — list traces (paginated)
- GET    /v1/traces/errors          — list error traces only
- GET    /v1/traces/search?q=...    — full-text search across traces/spans
- GET    /v1/traces/{id}            — trace detail
- GET    /v1/traces/{id}/dag        — causal DAG for a trace
- DELETE /v1/traces/{id}            — delete a trace
- POST   /v1/traces/batch-delete    — delete multiple traces by ID list
- POST   /v1/traces/cleanup         — delete traces older than N days
- GET    /v1/cost/breakdown         — cost attribution
- GET    /v1/cost/trends            — cost over time (daily/hourly)
- GET    /v1/stats                  — global statistics
- GET    /v1/stats/trends           — trace volume over time (bucketed for charting)
- GET    /v1/stats/summary          — enhanced stats with per-agent breakdown
- GET    /v1/patterns/summary       — aggregate pattern statistics
- GET    /v1/agents/summary         — agent-level trace statistics
- GET    /v1/agents/activity        — real-time per-agent activity (last hour)
- GET    /v1/agents/profiles        — profile info for all known agents
- GET    /v1/agents/relationships   — agent spawn relationship graph (nodes + edges)
- GET    /v1/activity/stream        — recent activity events across all agents
- GET    /v1/export/report          — summary activity report (last N hours)
- GET    /health                    — health check
- WS     /ws/traces                 — real-time trace stream
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional
import sqlite3

from fastapi import (
    FastAPI,
    HTTPException,
    Query,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field, field_validator

from .storage import TraceStore
from ..sdk.models import Span, SpanKind, SpanStatus, Trace, TokenUsage
from ..analysis.dag_builder import build_causal_dag
from ..analysis.patterns import detect_patterns
from ..analysis.trace_diff import TraceDiff as _TraceDiff
from ..analysis.smart_advisor import SmartAdvisor as _SmartAdvisor
from ..config import settings
from ..logging_config import configure_logging
from ..alerting import AlertRule, Alert
from ..alerting.engine import AlertEngine
from ..alerting.webhooks import send_webhook as _send_webhook

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Security constants
# ---------------------------------------------------------------------------

# Maximum allowed length for string identifiers (trace_id, service_name, etc.)
_MAX_ID_LENGTH = 512
# Maximum number of spans per ingest request
_MAX_SPANS_PER_INGEST = 10_000
# Allowed characters for identifiers: alphanumeric, hyphens, underscores, dots, colons
_SAFE_ID_RE = re.compile(r"^[\w\-.:/ ]+$")
# Allowed base directories for the import endpoint (empty means disabled)
_ALLOWED_IMPORT_DIRS: list[Path] = []


def _sanitize_id(value: str, field_name: str = "identifier") -> str:
    """
    Validate a string ID for safety.

    - Enforces a maximum length to prevent oversized inputs.
    - Rejects values containing path-traversal sequences (../).
    - Does NOT restrict to a strict character whitelist so that legitimate
      Unicode service names remain accepted.

    Raises HTTPException(400) when the value fails validation.
    """
    if len(value) > _MAX_ID_LENGTH:
        raise HTTPException(
            400,
            f"Invalid {field_name}: exceeds maximum length of {_MAX_ID_LENGTH} characters",
        )
    if ".." in value or value.startswith("/") or "\x00" in value:
        raise HTTPException(400, f"Invalid {field_name}: contains disallowed sequences")
    return value


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class TraceIngestRequest(BaseModel):
    """Payload for POST /v1/traces/ingest."""
    trace_id: str = Field(..., min_length=1, max_length=_MAX_ID_LENGTH, description="Unique trace identifier")
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
    user_id: Optional[str] = Field(None, max_length=_MAX_ID_LENGTH)
    session_id: Optional[str] = Field(None, max_length=_MAX_ID_LENGTH)
    experiment: Optional[str] = Field(None, max_length=_MAX_ID_LENGTH)
    tags: Optional[dict[str, str]] = None

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
    comment: Optional[str] = Field(None, max_length=4096)
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


class StatsResponse(BaseModel):
    total_traces: int = 0
    total_spans: int = 0
    total_tokens: int = 0
    total_cost: float = 0
    error_traces: int = 0
    avg_duration_ms: float = 0


# ---------------------------------------------------------------------------
# Alerting Pydantic models
# ---------------------------------------------------------------------------

class AlertRuleCreate(BaseModel):
    """Payload for POST /v1/alerts/rules."""
    name: str = Field(..., min_length=1, max_length=256)
    condition: str = Field(..., min_length=1, max_length=512)
    severity: str = Field("warning", pattern="^(critical|warning|info)$")
    webhook_url: Optional[str] = Field(None, max_length=2048)
    cooldown_seconds: int = Field(300, ge=0)
    enabled: bool = True


class AlertWebhookTest(BaseModel):
    """Payload for POST /v1/alerts/test."""
    webhook_url: str = Field(..., min_length=1, max_length=2048)


# ---------------------------------------------------------------------------
# WebSocket connection manager
# ---------------------------------------------------------------------------

class ConnectionManager:
    """
    Manages active WebSocket connections for the /ws/traces endpoint.

    All connected clients receive every newly ingested trace as a JSON message.
    """

    def __init__(self) -> None:
        self._active: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._active.append(ws)
        logger.debug("WS client connected (%d total)", len(self._active))

    def disconnect(self, ws: WebSocket) -> None:
        self._active.remove(ws)
        logger.debug("WS client disconnected (%d remaining)", len(self._active))

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Send *message* to every connected client, dropping dead connections."""
        dead: list[WebSocket] = []
        for ws in list(self._active):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            if ws in self._active:
                self._active.remove(ws)

    @property
    def connection_count(self) -> int:
        return len(self._active)


# ---------------------------------------------------------------------------
# Rate-limit helper (simple in-process token bucket per IP)
# ---------------------------------------------------------------------------

class _RateLimiter:
    """
    Lightweight per-IP rate limiter using a sliding-window counter.

    Supports per-key limits so ingest endpoints can be granted a higher
    budget than read/search endpoints.

    Not suitable for multi-process deployments — use Redis for those.
    """

    # Cleanup stale entries every N seconds
    _STALE_CLEANUP_INTERVAL = 300  # 5 minutes

    def __init__(self, requests_per_minute: int = 120) -> None:
        self._default_limit = requests_per_minute
        self._window = 60  # seconds
        # Maps (client_ip, limit_key) -> list[float]
        self._counts: dict[tuple[str, str], list[float]] = defaultdict(list)
        self._last_cleanup = time.time()

    def _maybe_cleanup(self, now: float) -> None:
        """Periodically purge stale (all-expired) entries to prevent unbounded growth."""
        if now - self._last_cleanup < self._STALE_CLEANUP_INTERVAL:
            return
        window_start = now - self._window
        stale_keys = [
            k for k, hits in self._counts.items()
            if not any(t > window_start for t in hits)
        ]
        for k in stale_keys:
            del self._counts[k]
        self._last_cleanup = now
        if stale_keys:
            logger.debug("Rate limiter: purged %d stale entries", len(stale_keys))

    def check(
        self,
        client_ip: str,
        limit_key: str = "default",
        limit_override: Optional[int] = None,
    ) -> tuple[bool, int, int, int]:
        """
        Record a request and return (allowed, remaining, limit, retry_after_seconds).

        ``allowed`` is False when the caller has exceeded the budget for this window.
        ``retry_after_seconds`` is 0 when the request is within budget.
        ``limit_override`` lets callers specify a per-endpoint limit.
        """
        now = time.time()
        self._maybe_cleanup(now)

        limit = limit_override if limit_override is not None else self._default_limit
        window_start = now - self._window
        key = (client_ip, limit_key)
        hits = self._counts[key]

        # Purge expired timestamps
        self._counts[key] = [t for t in hits if t > window_start]
        used = len(self._counts[key])

        allowed = used < limit
        if allowed:
            self._counts[key].append(now)
            used += 1

        remaining = max(0, limit - used)
        retry_after = (
            0
            if allowed
            else int(self._window - (now - self._counts[key][0]))
        )
        return allowed, remaining, limit, retry_after


# ---------------------------------------------------------------------------
# Built-in agent profile definitions
# ---------------------------------------------------------------------------

_AGENT_PROFILES = {
    "vr-alpha": {"name": "Alpha", "role": "Core Developer", "color": "#3b82f6", "icon": "shield"},
    "vr-beta": {"name": "Beta", "role": "Worker Engineer", "color": "#10b981", "icon": "gear"},
    "vr-gamma": {"name": "Gamma", "role": "Test & Monitor", "color": "#8b5cf6", "icon": "bolt"},
    "vr-lead": {"name": "Lead", "role": "Architect", "color": "#f59e0b", "icon": "crown"},
    "vr-scribe": {"name": "Scribe", "role": "Documentation", "color": "#6b7280", "icon": "book"},
    "main": {"name": "Main", "role": "Session", "color": "#6366f1", "icon": "terminal"},
    "Explore": {"name": "Explore", "role": "Explorer", "color": "#06b6d4", "icon": "search"},
}


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app(db_path: str | None = None) -> FastAPI:
    """Create and return the configured FastAPI application instance."""

    configure_logging()

    store = TraceStore(db_path=db_path or settings.db_path)
    ws_manager = ConnectionManager()
    rate_limiter = _RateLimiter(requests_per_minute=settings.rate_limit)

    # Alerting engine — load persisted rules from DB on startup
    alert_engine = AlertEngine()
    for _rule_data in store.list_alert_rules():
        alert_engine.add_rule(AlertRule.from_dict(_rule_data))

    # Track server start time for uptime calculation
    _server_start_time: float = time.time()

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
        logger.info("FlowLens server started")
        try:
            yield
        finally:
            logger.info("FlowLens server shutting down")
            # Graceful shutdown: flush any pending operations
            try:
                # Give any pending writes a moment to complete
                time.sleep(0.1)
            except Exception:
                pass
            store.close()
            logger.info("Database connections closed")

    app = FastAPI(
        title="FlowLens",
        description="Agent Observability Platform — Chrome DevTools for LLM Agents",
        version="0.5.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # -----------------------------------------------------------------------
    # API key authentication (optional, disabled by default)
    # -----------------------------------------------------------------------

    # Read the API key once at app-creation time so we don't call os.getenv
    # on every request.
    _api_key: str | None = os.environ.get("FLOWLENS_API_KEY") or None

    # Paths that are always accessible even when auth is enabled.
    _NO_AUTH_PATHS: frozenset[str] = frozenset({"/", "/dashboard"})

    @app.middleware("http")
    async def api_key_auth(request: Request, call_next):  # type: ignore[no-untyped-def]
        if request.scope.get("type") == "websocket":
            return await call_next(request)
        if _api_key is not None and request.url.path not in _NO_AUTH_PATHS:
            provided = request.headers.get("X-API-Key")
            if provided != _api_key:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Unauthorized: invalid or missing API key"},
                    headers={"WWW-Authenticate": "ApiKey"},
                )
        return await call_next(request)

    # -----------------------------------------------------------------------
    # Middleware — security headers + request logging + rate-limit
    # -----------------------------------------------------------------------

    @app.middleware("http")
    async def security_and_rate_limit(request: Request, call_next):  # type: ignore[no-untyped-def]
        if request.scope.get("type") == "websocket":
            return await call_next(request)
        start = time.perf_counter()
        client_ip = request.client.host if request.client else "unknown"
        path = request.url.path

        # Per-endpoint rate-limit budget: ingest gets 3× the default allowance.
        if path == "/v1/traces/ingest":
            limit_key = "ingest"
            limit_override = settings.rate_limit * 3
        elif path.startswith("/v1/traces/search"):
            limit_key = "search"
            limit_override = max(1, settings.rate_limit // 2)
        else:
            limit_key = "default"
            limit_override = None

        allowed, remaining, limit, retry_after = rate_limiter.check(
            client_ip, limit_key=limit_key, limit_override=limit_override
        )

        if not allowed:
            logger.warning(
                "Rate limit exceeded for %s on %s (key=%s)",
                client_ip, path, limit_key,
            )
            response = JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Please slow down."},
                headers={
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Retry-After": str(retry_after),
                    "Retry-After": str(retry_after),
                },
            )
            return response

        try:
            response: Response = await call_next(request)
        except Exception:
            # Catch unhandled exceptions and return a generic 500 without
            # leaking internal details (stack traces, file paths, etc.).
            logger.exception("Unhandled exception processing %s %s", request.method, path)
            response = JSONResponse(
                status_code=500,
                content={"detail": "An internal server error occurred."},
            )

        elapsed_ms = (time.perf_counter() - start) * 1000

        # Log request details (exclude health checks to reduce noise)
        if path != "/health":
            logger.info(
                "%s %s %d %.1fms",
                request.method,
                path,
                response.status_code,
                elapsed_ms,
            )

        # Security headers — prevent common web vulnerabilities
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data:"
        )

        # Standard rate-limit headers
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        if retry_after:
            response.headers["X-RateLimit-Retry-After"] = str(retry_after)

        return response

    # -----------------------------------------------------------------------
    # WebSocket — real-time trace stream
    # -----------------------------------------------------------------------

    @app.websocket("/ws/traces")
    async def ws_traces(ws: WebSocket) -> None:
        """
        Stream newly ingested traces to connected clients.

        Each message is a JSON object with ``event`` and ``data`` keys.
        Clients receive a ``connected`` handshake immediately upon joining.
        """
        await ws_manager.connect(ws)
        try:
            await ws.send_json(
                {
                    "event": "connected",
                    "data": {"message": "Subscribed to trace stream"},
                }
            )
            # Keep the connection alive — we push events from the ingest endpoint.
            while True:
                # We only need to stay alive; the client can send pings if desired.
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            ws_manager.disconnect(ws)

    # -----------------------------------------------------------------------
    # Ingest
    # -----------------------------------------------------------------------

    @app.post("/v1/traces/ingest", status_code=201)
    async def ingest_trace(req: TraceIngestRequest) -> dict[str, str]:
        """Receive and persist trace data; broadcast to WebSocket subscribers."""
        import random
        # Enforce spans list size limit (belt-and-suspenders beyond Pydantic)
        if len(req.spans) > _MAX_SPANS_PER_INGEST:
            raise HTTPException(
                400,
                f"spans list exceeds maximum allowed size of {_MAX_SPANS_PER_INGEST}",
            )

        try:
            payload = req.model_dump()
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
            summary = {k: payload[k] for k in (
                "trace_id", "service_name", "start_time", "end_time",
                "duration_ms", "total_tokens", "total_cost_usd",
                "has_errors", "error_count", "span_count",
            )}
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

    @app.post("/v1/traces/import", status_code=201)
    async def import_jsonl(file_path: str) -> dict[str, Any]:
        """
        Bulk-import traces from a JSONL file.

        The ``file_path`` parameter is restricted to pre-approved directories
        defined in ``_ALLOWED_IMPORT_DIRS``.  When that list is empty (the
        default), the endpoint is effectively disabled for security.

        Configure allowed directories by appending to
        ``flowlens.server.app._ALLOWED_IMPORT_DIRS`` before calling
        ``create_app()``.
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
            if not any(
                _is_subpath(resolved, allowed)
                for allowed in _ALLOWED_IMPORT_DIRS
            ):
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
                        store.save_trace(trace_data)
                        count += 1
                    except Exception as e:
                        errors += 1
                        logger.warning("Failed to import trace line: %s", e)
        except OSError:
            logger.exception("Failed to read import file")
            raise HTTPException(500, "Failed to read the specified file")

        return {"imported": count, "errors": errors}

    # -----------------------------------------------------------------------
    # Query — list / search / errors
    # NOTE: specific path segments (/errors, /search, /cleanup) MUST come
    #       before the generic /{trace_id} route to avoid being shadowed.
    # -----------------------------------------------------------------------

    @app.get("/v1/traces/errors")
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
        return TraceListResponse(
            traces=traces, total=len(traces), limit=limit, offset=offset
        )

    @app.get("/v1/traces/search")
    async def search_traces(
        q: str = Query(..., min_length=1, max_length=200, description="Search term"),
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ) -> TraceListResponse:
        """
        Full-text search across trace service_name and span name / error_message.
        """
        q_stripped = q.strip()
        if not q_stripped:
            raise HTTPException(400, "Search query must not be blank")

        try:
            traces = store.search_traces(query=q_stripped, limit=limit, offset=offset)
        except Exception:
            logger.exception("Search failed for query: %s", q_stripped[:50])
            raise HTTPException(500, "Search failed")
        return TraceListResponse(
            traces=traces, total=len(traces), limit=limit, offset=offset
        )

    @app.post("/v1/traces/batch-delete", status_code=200)
    async def batch_delete_traces(req: BatchDeleteRequest) -> dict[str, Any]:
        """
        Delete multiple traces at once.

        Accepts a JSON body ``{"trace_ids": ["id1", "id2", ...]}``.
        Returns the count of traces actually deleted (IDs that did not exist
        are silently ignored).
        """
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

    @app.post("/v1/traces/cleanup", status_code=200)
    async def cleanup_traces(req: CleanupRequest) -> dict[str, Any]:
        """Delete all traces older than ``req.days`` days."""
        try:
            deleted = store.cleanup_old_traces(days=req.days)
        except Exception:
            logger.exception("Cleanup failed")
            raise HTTPException(500, "Cleanup operation failed")
        return {"deleted": deleted, "days": req.days}

    @app.get("/v1/traces")
    async def list_traces(
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        service: Optional[str] = Query(None, max_length=_MAX_ID_LENGTH),
        errors_only: bool = False,
        user_id: Optional[str] = Query(None, max_length=_MAX_ID_LENGTH),
        session_id: Optional[str] = Query(None, max_length=_MAX_ID_LENGTH),
        experiment: Optional[str] = Query(None, max_length=_MAX_ID_LENGTH),
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
        return TraceListResponse(
            traces=traces, total=len(traces), limit=limit, offset=offset
        )

    @app.get("/v1/traces/{trace_id}")
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

    @app.delete("/v1/traces/{trace_id}", status_code=200)
    async def delete_trace(trace_id: str) -> dict[str, str]:
        """
        Permanently delete a trace and all its spans.

        Returns 404 if the trace does not exist.
        """
        _sanitize_id(trace_id, "trace_id")
        try:
            deleted = store.delete_trace(trace_id)
        except Exception:
            logger.exception("Failed to delete trace %s", trace_id[:32])
            raise HTTPException(500, "Failed to delete trace")
        if not deleted:
            raise HTTPException(404, "Trace not found")
        return {"status": "deleted", "trace_id": trace_id}

    # -----------------------------------------------------------------------
    # Analysis
    # -----------------------------------------------------------------------

    @app.get("/v1/traces/{trace_id}/dag")
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

    # -----------------------------------------------------------------------
    # Trace diff / experiment diff
    # -----------------------------------------------------------------------

    @app.get("/v1/traces/diff")
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

    @app.get("/v1/experiments/diff")
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

    # -----------------------------------------------------------------------
    # Fleet analysis / regression detection
    # -----------------------------------------------------------------------

    @app.get("/v1/analysis/fleet")
    async def fleet_analysis(
        limit: int = Query(500, ge=1, le=2000),
        service: Optional[str] = Query(None, max_length=_MAX_ID_LENGTH),
    ) -> dict[str, Any]:
        """Fleet-wide analysis and recommendations."""
        if service is not None:
            _sanitize_id(service, "service")
        try:
            raw_traces = store.list_traces(limit=limit, service_name=service)
        except Exception:
            logger.exception("Failed to list traces for fleet analysis")
            raise HTTPException(500, "Failed to retrieve traces")
        try:
            traces = [_reconstruct_trace(t) for t in raw_traces]
            advisor = _SmartAdvisor()
            return advisor.analyze_fleet(traces)
        except Exception:
            logger.exception("Fleet analysis failed")
            raise HTTPException(500, "Fleet analysis failed")

    @app.get("/v1/analysis/regressions")
    async def regression_analysis(
        days: int = Query(7, ge=1, le=365, description="Days to treat as recent"),
        service: Optional[str] = Query(None, max_length=_MAX_ID_LENGTH),
        limit: int = Query(500, ge=1, le=2000),
    ) -> dict[str, Any]:
        """Detect regressions by comparing recent traces against baseline."""
        if service is not None:
            _sanitize_id(service, "service")
        import time as _time
        cutoff = _time.time() - days * 86_400
        try:
            all_raw = store.list_traces(limit=limit, service_name=service)
        except Exception:
            logger.exception("Failed to list traces for regression analysis")
            raise HTTPException(500, "Failed to retrieve traces")
        try:
            all_traces = [_reconstruct_trace(t) for t in all_raw]
            recent_traces = [t for t in all_traces if t.start_time >= cutoff]
            baseline_traces = [t for t in all_traces if t.start_time < cutoff]
            if not recent_traces:
                return {
                    "regressions": [],
                    "summary": f"No traces found in the last {days} day(s).",
                    "recent_count": 0,
                    "baseline_count": len(baseline_traces),
                }
            if not baseline_traces:
                return {
                    "regressions": [],
                    "summary": "No baseline traces available for comparison.",
                    "recent_count": len(recent_traces),
                    "baseline_count": 0,
                }
            advisor = _SmartAdvisor()
            reports = advisor.detect_regression(
                recent_traces, baseline_traces, service_name=service or "all services"
            )
            return {
                "regressions": [r.to_dict() for r in reports],
                "summary": (
                    f"Detected {len(reports)} regression(s) comparing last {days} day(s) "
                    f"({len(recent_traces)} traces) against baseline "
                    f"({len(baseline_traces)} traces)."
                ),
                "recent_count": len(recent_traces),
                "baseline_count": len(baseline_traces),
            }
        except Exception:
            logger.exception("Regression analysis failed")
            raise HTTPException(500, "Regression analysis failed")

    # -----------------------------------------------------------------------
    # Cost
    # -----------------------------------------------------------------------

    @app.get("/v1/cost/breakdown")
    async def cost_breakdown(
        group_by: str = Query("service_name", pattern="^(service_name|kind|name)$"),
    ) -> list[dict[str, Any]]:
        """Cost attribution grouped by service, span kind, or span name."""
        try:
            return store.get_cost_breakdown(group_by=group_by)
        except Exception:
            logger.exception("Failed to get cost breakdown")
            raise HTTPException(500, "Failed to retrieve cost breakdown")

    @app.get("/v1/cost/trends")
    async def cost_trends(
        granularity: str = Query("daily", pattern="^(daily|hourly)$"),
        limit: int = Query(30, ge=1, le=365),
    ) -> list[dict[str, Any]]:
        """
        Aggregate cost over time.

        ``granularity`` is either ``daily`` (default) or ``hourly``.
        ``limit`` controls how many time buckets are returned (most recent first
        in the raw query; the response is sorted oldest-to-newest).
        """
        try:
            return store.get_cost_trends(granularity=granularity, limit=limit)
        except Exception:
            logger.exception("Failed to get cost trends")
            raise HTTPException(500, "Failed to retrieve cost trends")

    @app.get("/v1/cost/forecast")
    async def cost_forecast(
        days: int = Query(30, ge=1, le=365, description="Forecast horizon in days"),
    ) -> dict[str, Any]:
        """
        Project future costs using linear regression on daily cost data.

        Returns projected_daily_cost, projected_monthly_cost, trend,
        confidence_interval, days_of_data, slope, and r_squared.
        """
        from ..analysis.cost_forecast import CostForecaster
        try:
            daily_records = store.get_daily_costs(days=max(days, 7))
            forecaster = CostForecaster()
            forecast = forecaster.forecast(daily_records, days=days)
            return forecast.to_dict()
        except Exception:
            logger.exception("Failed to compute cost forecast")
            raise HTTPException(500, "Failed to compute cost forecast")

    @app.get("/v1/cost/budget")
    async def cost_budget(
        budget: float = Query(..., gt=0, description="Budget cap in USD"),
    ) -> dict[str, Any]:
        """
        Return budget status: how much has been spent, what remains,
        the current daily burn rate, and estimated days until the budget is exhausted.
        """
        from ..analysis.cost_forecast import CostForecaster
        try:
            daily_records = store.get_daily_costs(days=30)
            total_spent = sum(r.get("total_cost_usd", 0.0) or 0.0 for r in daily_records)
            remaining = max(0.0, budget - total_spent)

            forecaster = CostForecaster()
            forecast = forecaster.forecast(daily_records)
            burn_rate = forecast.projected_daily_cost

            days_left = forecaster.days_until_budget(daily_records, budget_usd=budget)

            return {
                "budget_usd": budget,
                "total_spent_usd": round(total_spent, 6),
                "remaining_usd": round(remaining, 6),
                "burn_rate_daily_usd": round(burn_rate, 6),
                "days_until_exhausted": round(days_left, 1) if days_left is not None else None,
                "trend": forecast.trend,
            }
        except Exception:
            logger.exception("Failed to compute budget status")
            raise HTTPException(500, "Failed to compute budget status")

    @app.get("/v1/cost/optimization")
    async def cost_optimization() -> dict[str, Any]:
        """
        Return actionable optimisation suggestions with estimated monthly savings.
        """
        from ..analysis.cost_breakdown import CostBreakdown
        try:
            # Fetch recent traces for analysis (lightweight — no spans loaded)
            traces = store.list_traces(limit=200)
            # We need span data for model/context analysis; fetch full traces
            # but cap at 50 to keep response times reasonable
            full_traces = []
            for t in traces[:50]:
                full = store.get_trace(t["trace_id"])
                if full:
                    full_traces.append(full)

            breakdown = CostBreakdown()
            suggestions = breakdown.optimization_suggestions(full_traces)
            by_model = breakdown.by_model(full_traces)
            by_service = breakdown.by_service(full_traces)
            by_kind = breakdown.by_span_kind(full_traces)

            total_savings = sum(
                s.get("estimated_monthly_savings_usd", 0.0) for s in suggestions
            )
            return {
                "suggestions": suggestions,
                "total_estimated_monthly_savings_usd": round(total_savings, 4),
                "by_model": by_model,
                "by_service": by_service,
                "by_span_kind": by_kind,
            }
        except Exception:
            logger.exception("Failed to compute optimisation suggestions")
            raise HTTPException(500, "Failed to compute optimisation suggestions")

    # -----------------------------------------------------------------------
    # Patterns
    # -----------------------------------------------------------------------

    @app.get("/v1/patterns/summary")
    async def patterns_summary(
        limit: int = Query(100, ge=1, le=1000),
    ) -> dict[str, Any]:
        """
        Aggregate pattern statistics: per-kind and per-name span counts,
        plus the top recurring error messages.
        """
        try:
            return store.get_pattern_summary(limit=limit)
        except Exception:
            logger.exception("Failed to get pattern summary")
            raise HTTPException(500, "Failed to retrieve pattern summary")

    # -----------------------------------------------------------------------
    # Feedback endpoints
    # -----------------------------------------------------------------------

    @app.post("/v1/traces/{trace_id}/feedback", status_code=201)
    async def submit_feedback(trace_id: str, req: FeedbackRequest) -> dict[str, Any]:
        """Submit feedback (rating 1–5, optional comment) for a trace."""
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

    @app.get("/v1/traces/{trace_id}/feedback")
    async def get_trace_feedback(trace_id: str) -> list[dict[str, Any]]:
        """Get all feedback for a specific trace."""
        _sanitize_id(trace_id, "trace_id")
        try:
            return store.get_feedback(trace_id)
        except Exception:
            logger.exception("Failed to get feedback for trace %s", trace_id[:32])
            raise HTTPException(500, "Failed to retrieve feedback")

    @app.get("/v1/feedback/summary")
    async def feedback_summary() -> dict[str, Any]:
        """Aggregate feedback statistics: avg rating, distribution, low-rated traces."""
        try:
            return store.get_feedback_summary()
        except Exception:
            logger.exception("Failed to get feedback summary")
            raise HTTPException(500, "Failed to retrieve feedback summary")

    # -----------------------------------------------------------------------
    # Metrics — users and experiments
    # -----------------------------------------------------------------------

    @app.get("/v1/metrics/users")
    async def user_metrics() -> list[dict[str, Any]]:
        """Per-user stats: trace count, error rate, avg cost."""
        try:
            return store.get_user_metrics()
        except Exception:
            logger.exception("Failed to get user metrics")
            raise HTTPException(500, "Failed to retrieve user metrics")

    @app.get("/v1/metrics/experiments")
    async def experiment_metrics() -> list[dict[str, Any]]:
        """Per-experiment comparison: trace count, error rate, avg cost, avg duration."""
        try:
            return store.get_experiment_metrics()
        except Exception:
            logger.exception("Failed to get experiment metrics")
            raise HTTPException(500, "Failed to retrieve experiment metrics")

    # -----------------------------------------------------------------------
    # Stats
    # -----------------------------------------------------------------------

    @app.get("/v1/stats")
    async def get_stats() -> StatsResponse:
        """Global aggregate statistics."""
        try:
            stats = store.get_stats()
        except Exception:
            logger.exception("Failed to get stats")
            raise HTTPException(500, "Failed to retrieve statistics")
        return StatsResponse(
            total_traces=stats.get("total_traces") or 0,
            total_spans=stats.get("total_spans") or 0,
            total_tokens=stats.get("total_tokens") or 0,
            total_cost=stats.get("total_cost") or 0,
            error_traces=stats.get("error_traces") or 0,
            avg_duration_ms=stats.get("avg_duration_ms") or 0,
        )

    # -----------------------------------------------------------------------
    # Stats trends + summary
    # -----------------------------------------------------------------------

    @app.get("/v1/stats/trends")
    async def stats_trends(hours: int = 24, bucket_minutes: int = 60) -> JSONResponse:
        """Return trace count and error count bucketed by time.

        Returns data suitable for a line chart showing activity over time.
        """
        hours = min(hours, 168)  # Max 1 week
        bucket_minutes = max(5, min(bucket_minutes, 1440))

        now = time.time()
        start = now - (hours * 3600)
        bucket_size = bucket_minutes * 60

        # Query traces in time range
        try:
            traces = store.get_traces_by_time_range(start=start, end=now)
        except Exception:
            logger.exception("Failed to get traces for trends")
            raise HTTPException(500, "Failed to retrieve traces for trends")

        # Bucket them
        buckets: dict[float, dict[str, Any]] = {}
        for t in traces:
            bucket_key = int((t["start_time"] - start) / bucket_size)
            bucket_time = start + bucket_key * bucket_size
            if bucket_time not in buckets:
                buckets[bucket_time] = {"timestamp": bucket_time, "traces": 0, "errors": 0, "cost": 0.0}
            buckets[bucket_time]["traces"] += 1
            if t.get("has_errors"):
                buckets[bucket_time]["errors"] += 1
            buckets[bucket_time]["cost"] += t.get("total_cost_usd", 0)

        # Fill gaps with zeros
        result = []
        current = start
        while current < now:
            if current in buckets:
                result.append(buckets[current])
            else:
                result.append({"timestamp": current, "traces": 0, "errors": 0, "cost": 0.0})
            current += bucket_size

        return JSONResponse({"buckets": result, "hours": hours, "bucket_minutes": bucket_minutes})

    @app.get("/v1/stats/summary")
    async def stats_summary() -> JSONResponse:
        """Enhanced stats with per-agent breakdown."""
        try:
            basic = store.get_stats()
        except Exception:
            logger.exception("Failed to get basic stats for summary")
            raise HTTPException(500, "Failed to retrieve statistics")

        # Get agent breakdown
        try:
            traces = store.list_traces(limit=1000)
        except Exception:
            logger.exception("Failed to list traces for stats summary")
            raise HTTPException(500, "Failed to retrieve traces")

        agent_stats: dict[str, dict[str, Any]] = {}
        for t in traces:
            tags = t.get("tags") or {}
            if isinstance(tags, str):
                import json as _json
                tags = _json.loads(tags)
            agent = tags.get("agent", "unknown")
            if agent not in agent_stats:
                agent_stats[agent] = {"traces": 0, "errors": 0, "cost": 0.0, "spans": 0}
            agent_stats[agent]["traces"] += 1
            if t.get("has_errors"):
                agent_stats[agent]["errors"] += 1
            agent_stats[agent]["cost"] += t.get("total_cost_usd", 0)
            agent_stats[agent]["spans"] += t.get("span_count", 0)

        return JSONResponse({
            **basic,
            "agent_breakdown": agent_stats,
        })

    # -----------------------------------------------------------------------
    # Health
    # -----------------------------------------------------------------------

    @app.get("/health")
    async def health() -> dict[str, Any]:
        """
        Health check endpoint.

        Returns server status, version, uptime, and database metrics.
        """
        uptime_seconds = int(time.time() - _server_start_time)
        stats = store.get_stats()

        # Get database file size in bytes
        db_file_path = Path(store.db_path)
        db_size_bytes = db_file_path.stat().st_size if db_file_path.exists() else 0

        return {
            "status": "healthy",
            "version": "0.5.0",
            "uptime_seconds": uptime_seconds,
            "trace_count": stats.get("total_traces") or 0,
            "db_size_bytes": db_size_bytes,
        }

    # -----------------------------------------------------------------------
    # Alerting
    # -----------------------------------------------------------------------

    @app.post("/v1/alerts/rules", status_code=201)
    async def create_alert_rule(req: AlertRuleCreate) -> dict[str, Any]:
        """Create or replace an alert rule."""
        rule = AlertRule(
            name=req.name,
            condition=req.condition,
            severity=req.severity,
            webhook_url=req.webhook_url,
            cooldown_seconds=req.cooldown_seconds,
            enabled=req.enabled,
        )
        try:
            store.save_alert_rule(rule.to_dict())
            alert_engine.add_rule(rule)
        except Exception:
            logger.exception("Failed to save alert rule %s", req.name)
            raise HTTPException(500, "Failed to save alert rule")
        return {"status": "created", "name": req.name}

    @app.get("/v1/alerts/rules")
    async def list_alert_rules() -> list[dict[str, Any]]:
        """List all configured alert rules."""
        try:
            return store.list_alert_rules()
        except Exception:
            logger.exception("Failed to list alert rules")
            raise HTTPException(500, "Failed to retrieve alert rules")

    @app.delete("/v1/alerts/rules/{name}", status_code=200)
    async def delete_alert_rule(name: str) -> dict[str, str]:
        """Delete an alert rule by name."""
        _sanitize_id(name, "rule name")
        try:
            deleted = store.delete_alert_rule(name)
            alert_engine.remove_rule(name)
        except Exception:
            logger.exception("Failed to delete alert rule %s", name)
            raise HTTPException(500, "Failed to delete alert rule")
        if not deleted:
            raise HTTPException(404, f"Alert rule '{name}' not found")
        return {"status": "deleted", "name": name}

    @app.get("/v1/alerts/history")
    async def get_alert_history(
        limit: int = Query(100, ge=1, le=1000),
    ) -> list[dict[str, Any]]:
        """Return recent fired alerts (most recent first)."""
        try:
            return store.get_alert_history(limit=limit)
        except Exception:
            logger.exception("Failed to retrieve alert history")
            raise HTTPException(500, "Failed to retrieve alert history")

    @app.post("/v1/alerts/test", status_code=200)
    async def test_webhook(req: AlertWebhookTest) -> dict[str, Any]:
        """Send a test alert to the specified webhook URL."""
        test_alert = Alert(
            rule_name="test",
            severity="info",
            message="This is a test alert from FlowLens.",
            trace_id=None,
            metrics={"test": True},
        )
        try:
            success = await _send_webhook(
                url=req.webhook_url,
                alert_dict=test_alert.to_dict(),
                trace_context=None,
            )
        except Exception as exc:
            logger.warning("Test webhook to %s failed: %s", req.webhook_url, exc)
            success = False
        return {"delivered": success, "webhook_url": req.webhook_url}

    # -----------------------------------------------------------------------
    # Agents summary
    # -----------------------------------------------------------------------

    @app.get("/v1/agents/summary")
    async def agents_summary() -> JSONResponse:
        """Aggregate trace statistics grouped by agent name.

        Extracts agent info from trace tags (tags.agent) or span attributes.
        Returns a list of agent summaries with trace count, error rate,
        avg latency, total cost, and span count.
        """
        try:
            traces = store.list_traces(limit=10_000)
        except Exception:
            logger.exception("Failed to list traces for agents summary")
            raise HTTPException(500, "Failed to retrieve traces")

        # Group metrics by agent name extracted from tags["agent"]
        agent_stats: dict[str, dict[str, Any]] = {}
        for trace in traces:
            tags = trace.get("tags") or {}
            if isinstance(tags, str):
                try:
                    tags = json.loads(tags)
                except Exception:
                    tags = {}
            agent_name: str = tags.get("agent") or "unknown"

            if agent_name not in agent_stats:
                agent_stats[agent_name] = {
                    "agent": agent_name,
                    "trace_count": 0,
                    "error_count": 0,
                    "total_duration_ms": 0.0,
                    "total_cost_usd": 0.0,
                    "total_spans": 0,
                }
            bucket = agent_stats[agent_name]
            bucket["trace_count"] += 1
            if trace.get("has_errors"):
                bucket["error_count"] += 1
            bucket["total_duration_ms"] += trace.get("duration_ms") or 0.0
            bucket["total_cost_usd"] += trace.get("total_cost_usd") or 0.0
            bucket["total_spans"] += trace.get("span_count") or 0

        result = []
        for bucket in agent_stats.values():
            tc = bucket["trace_count"]
            result.append({
                "agent": bucket["agent"],
                "trace_count": tc,
                "error_count": bucket["error_count"],
                "error_rate": round(bucket["error_count"] / tc, 4) if tc else 0.0,
                "avg_duration_ms": round(bucket["total_duration_ms"] / tc, 2) if tc else 0.0,
                "total_cost_usd": round(bucket["total_cost_usd"], 6),
                "total_spans": bucket["total_spans"],
            })

        result.sort(key=lambda x: x["trace_count"], reverse=True)
        return JSONResponse({"agents": result})

    # -----------------------------------------------------------------------
    # Agents activity
    # -----------------------------------------------------------------------

    @app.get("/v1/agents/activity")
    async def agents_activity() -> JSONResponse:
        """Return recent activity for each known agent.

        For each agent, returns:
        - last_seen: timestamp of most recent trace
        - status: "active" if last seen within 5 min, else "idle"
        - recent_tools: list of recent tool names used (from span names)
        - current_task: description from most recent span attributes
        - trace_count_1h: traces in last hour
        """
        now = time.time()
        one_hour_ago = now - 3600.0
        active_threshold = now - 300.0  # 5 minutes

        try:
            recent_traces = store.get_traces_by_time_range(start=one_hour_ago, end=now + 1)
        except Exception:
            logger.exception("Failed to list traces for agents activity")
            raise HTTPException(500, "Failed to retrieve agent activity")

        # Group traces by agent
        agent_buckets: dict[str, dict[str, Any]] = {}
        for trace in recent_traces:
            tags = trace.get("tags") or {}
            if isinstance(tags, str):
                try:
                    tags = json.loads(tags)
                except Exception:
                    tags = {}
            agent_name: str = tags.get("agent") or "unknown"

            if agent_name not in agent_buckets:
                agent_buckets[agent_name] = {
                    "agent": agent_name,
                    "last_seen": 0.0,
                    "trace_count_1h": 0,
                    "all_tool_names": [],
                    "latest_trace_id": None,
                }
            bucket = agent_buckets[agent_name]
            bucket["trace_count_1h"] += 1
            start_time = trace.get("start_time") or 0.0
            if start_time > bucket["last_seen"]:
                bucket["last_seen"] = start_time
                bucket["latest_trace_id"] = trace.get("trace_id")

        # For each agent, fetch the most recent trace's spans to extract tool names
        result = []
        for agent_name, bucket in agent_buckets.items():
            recent_tools: list[str] = []
            current_task: str | None = None

            latest_tid = bucket["latest_trace_id"]
            if latest_tid:
                try:
                    full_trace = store.get_trace(latest_tid)
                    if full_trace:
                        spans = full_trace.get("spans") or []
                        # Collect span names, extract tool name after last "/"
                        tool_names_seen: list[str] = []
                        for span in spans:
                            span_name = span.get("name") or ""
                            # "vr-alpha/Read" -> "Read"; "Read" -> "Read"
                            tool_name = span_name.split("/")[-1] if "/" in span_name else span_name
                            if tool_name and tool_name not in tool_names_seen:
                                tool_names_seen.append(tool_name)
                        recent_tools = tool_names_seen[:5]

                        # current_task: description from the last span's attributes
                        if spans:
                            last_span = spans[-1]
                            attrs = last_span.get("attributes") or {}
                            current_task = attrs.get("description") or attrs.get("task") or None
                except Exception:
                    logger.debug("Failed to fetch spans for agent %s trace %s", agent_name, latest_tid)

            last_seen = bucket["last_seen"]
            status = "active" if last_seen >= active_threshold else "idle"

            result.append({
                "agent": agent_name,
                "last_seen": last_seen,
                "status": status,
                "recent_tools": recent_tools,
                "current_task": current_task,
                "trace_count_1h": bucket["trace_count_1h"],
            })

        # Sort: active agents first, then by last_seen descending
        result.sort(key=lambda x: (0 if x["status"] == "active" else 1, -x["last_seen"]))
        return JSONResponse({"agents": result})

    # -----------------------------------------------------------------------
    # Agents profiles
    # -----------------------------------------------------------------------

    @app.get("/v1/agents/profiles")
    async def agents_profiles() -> JSONResponse:
        """Return profile info for all known agents.

        Merges built-in profiles with dynamically discovered agents from traces.
        """
        # Get all known agent names from traces
        traces = store.list_traces(limit=1000)
        discovered = set()
        for t in traces:
            tags = t.get("tags") or {}
            if isinstance(tags, str):
                import json as _json
                tags = _json.loads(tags)
            agent = tags.get("agent")
            if agent:
                discovered.add(agent)

        result = []
        # Add all built-in profiles
        for agent_name, profile in _AGENT_PROFILES.items():
            result.append({
                "agent": agent_name,
                "known": True,
                **profile,
            })

        # Add any discovered agents not in built-in
        for agent_name in discovered:
            if agent_name not in _AGENT_PROFILES:
                result.append({
                    "agent": agent_name,
                    "name": agent_name,
                    "role": "Agent",
                    "color": "#9ca3af",
                    "icon": "user",
                    "known": False,
                })

        return JSONResponse({"agents": result})

    # -----------------------------------------------------------------------
    # Agent spawn relationships
    # -----------------------------------------------------------------------

    @app.get("/v1/agents/relationships")
    async def agents_relationships() -> JSONResponse:
        """Return agent spawn relationships for visualization.

        Analyzes spans where tool_name contains 'Agent' or 'spawn' to build
        a parent-child graph of which agents spawned which others.

        Span naming conventions recognized:
        - ``subagent/<child>``        — span name emitted by SDK subagent hook
        - ``<parent>/spawn/<child>``  — explicit spawn span with parent prefix
        - ``<parent>/Agent/<input>``  — Agent tool call (subagent_type parsed
                                       from attributes.tool.input or span name)
        """
        try:
            traces = store.list_traces(limit=500)
        except Exception:
            logger.exception("Failed to list traces for agent relationships")
            raise HTTPException(500, "Failed to retrieve traces")

        relationships: dict[str, int] = {}  # "parent->child": count

        for trace_meta in traces:
            # Extract the agent that owns this trace (default "main")
            tags = trace_meta.get("tags") or {}
            if isinstance(tags, str):
                try:
                    tags = json.loads(tags)
                except Exception:
                    tags = {}
            trace_agent: str = tags.get("agent") or "main"

            full = store.get_trace(trace_meta["trace_id"])
            if not full:
                continue

            for span in full.get("spans", []):
                name: str = span.get("name", "")
                name_lower = name.lower()
                attrs: dict[str, Any] = span.get("attributes") or {}

                # Pattern 1: "subagent/<child>" — subagent lifecycle span
                if name_lower.startswith("subagent/"):
                    child = name[len("subagent/"):]
                    if child:
                        key = f"{trace_agent}->{child}"
                        relationships[key] = relationships.get(key, 0) + 1
                    continue

                # Pattern 2: "spawn" anywhere in the name
                if "spawn" in name_lower:
                    parts = [p for p in name.split("/") if p]
                    if len(parts) >= 2:
                        parent = parts[0]
                        child = parts[-1]
                        if parent != child:
                            key = f"{parent}->{child}"
                            relationships[key] = relationships.get(key, 0) + 1
                    continue

                # Pattern 3: "<parent>/Agent/<something>" — Agent tool call
                if "Agent" in name and "/" in name:
                    parts = name.split("/")
                    if len(parts) >= 2:
                        parent = parts[0]
                        # Try to resolve the spawned agent type from attributes
                        tool_input = attrs.get("tool.input") or attrs.get("input") or ""
                        if isinstance(tool_input, dict):
                            child = tool_input.get("subagent_type") or tool_input.get("agent") or ""
                        elif isinstance(tool_input, str):
                            # Simple heuristic: look for subagent_type key in JSON-ish string
                            import re as _re
                            m = _re.search(r'"subagent_type"\s*:\s*"([^"]+)"', tool_input)
                            child = m.group(1) if m else ""
                        else:
                            child = ""
                        if not child:
                            # Fall back to last path component
                            child = parts[-1]
                        if parent and child and parent != child:
                            key = f"{parent}->{child}"
                            relationships[key] = relationships.get(key, 0) + 1

        # Build graph structure
        agents: set[str] = set()
        edges: list[dict[str, Any]] = []
        for rel, count in relationships.items():
            src, tgt = rel.split("->", 1)
            agents.add(src)
            agents.add(tgt)
            edges.append({"source": src, "target": tgt, "count": count})

        nodes = [{"id": a, "label": a} for a in sorted(agents)]
        edges.sort(key=lambda e: (-e["count"], e["source"], e["target"]))
        return JSONResponse({"nodes": nodes, "edges": edges})

    # -----------------------------------------------------------------------
    # Export report
    # -----------------------------------------------------------------------

    @app.get("/v1/export/report")
    async def export_report(hours: int = Query(24, ge=1, le=720)) -> JSONResponse:
        """Generate a comprehensive report of agent activity.

        Returns a structured report suitable for display or export to PDF/markdown.

        Query parameters:
        - ``hours`` (int, 1-720, default 24): time window to include in the report.
        """
        now = time.time()
        start = now - hours * 3600

        try:
            traces = store.get_traces_by_time_range(start=start, end=now)
        except Exception:
            logger.exception("Failed to retrieve traces for report")
            raise HTTPException(500, "Failed to retrieve traces for report")

        # Aggregate top-level stats
        total_traces = len(traces)
        total_errors = sum(1 for t in traces if t.get("has_errors"))
        total_cost = sum(t.get("total_cost_usd") or 0 for t in traces)
        total_spans = sum(t.get("span_count") or 0 for t in traces)

        # Per-agent stats
        agent_stats: dict[str, dict[str, Any]] = {}
        for t in traces:
            tags = t.get("tags") or {}
            if isinstance(tags, str):
                try:
                    tags = json.loads(tags)
                except Exception:
                    tags = {}
            agent: str = tags.get("agent") or "unknown"
            if agent not in agent_stats:
                agent_stats[agent] = {
                    "traces": 0,
                    "errors": 0,
                    "cost": 0.0,
                    "total_duration_ms": 0.0,
                    "spans": 0,
                }
            bucket = agent_stats[agent]
            bucket["traces"] += 1
            if t.get("has_errors"):
                bucket["errors"] += 1
            bucket["cost"] += t.get("total_cost_usd") or 0
            bucket["total_duration_ms"] += t.get("duration_ms") or 0
            bucket["spans"] += t.get("span_count") or 0

        # Round floats for readability
        for bucket in agent_stats.values():
            bucket["cost"] = round(bucket["cost"], 6)
            bucket["avg_duration_ms"] = (
                round(bucket["total_duration_ms"] / bucket["traces"], 2)
                if bucket["traces"] else 0.0
            )
            del bucket["total_duration_ms"]

        return JSONResponse({
            "report": {
                "period_hours": hours,
                "generated_at": now,
                "summary": {
                    "total_traces": total_traces,
                    "total_errors": total_errors,
                    "error_rate": round(total_errors / max(1, total_traces), 4),
                    "total_cost_usd": round(total_cost, 4),
                    "total_spans": total_spans,
                },
                "agents": agent_stats,
            }
        })

    # -----------------------------------------------------------------------
    # Activity stream
    # -----------------------------------------------------------------------

    @app.get("/v1/activity/stream")
    async def activity_stream(limit: int = 50) -> JSONResponse:
        """Return recent activity events across all agents.

        Extracts individual tool calls from spans, ordered by time (newest first).
        Used for the Activity Timeline view.
        """
        limit = min(limit, 200)

        # Get recent traces
        recent = store.list_traces(limit=100)

        events = []
        for trace_meta in recent:
            trace_id = trace_meta["trace_id"]
            tags = trace_meta.get("tags") or {}
            if isinstance(tags, str):
                import json as _json
                tags = _json.loads(tags)
            agent = tags.get("agent", "unknown")

            # Get full trace with spans
            full = store.get_trace(trace_id)
            if not full or not full.get("spans"):
                continue

            for span in full["spans"]:
                tool_name = span.get("name", "")
                # Extract tool from "agent/Tool" format
                if "/" in tool_name:
                    tool_name = tool_name.split("/", 1)[1]

                events.append({
                    "agent": agent,
                    "tool": tool_name,
                    "status": span.get("status", "ok"),
                    "timestamp": span.get("start_time", 0),
                    "duration_ms": span.get("duration_ms", 0),
                    "trace_id": trace_id,
                    "error": span.get("error_message") or (span.get("error", {}) or {}).get("message"),
                })

        # Sort by timestamp descending and limit
        events.sort(key=lambda e: e["timestamp"], reverse=True)
        events = events[:limit]

        return JSONResponse({"events": events, "total": len(events)})

    # -----------------------------------------------------------------------
    # Dashboard
    # -----------------------------------------------------------------------

    _dashboard_html: str | None = None

    def _load_dashboard() -> str:
        nonlocal _dashboard_html
        if _dashboard_html is None:
            dashboard_path = Path(__file__).parent / "dashboard.html"
            _dashboard_html = dashboard_path.read_text(encoding="utf-8")
        return _dashboard_html

    @app.get("/", response_class=HTMLResponse)
    async def dashboard_root() -> HTMLResponse:
        """Serve the FlowLens dashboard."""
        return HTMLResponse(content=_load_dashboard())

    @app.get("/dashboard", response_class=HTMLResponse)
    async def dashboard_alias() -> HTMLResponse:
        """Serve the FlowLens dashboard (alias)."""
        return HTMLResponse(content=_load_dashboard())

    @app.get("/static/{filename}")
    async def serve_static(filename: str) -> Response:
        """Serve bundled static assets (Tailwind fallback, etc.)."""
        import re
        if not re.match(r'^[a-zA-Z0-9._-]+$', filename):
            return JSONResponse({"detail": "invalid filename"}, status_code=400)
        static_path = Path(__file__).parent / filename
        if not static_path.exists():
            return JSONResponse({"detail": "not found"}, status_code=404)
        content_types = {".js": "application/javascript", ".css": "text/css"}
        ct = content_types.get(static_path.suffix, "application/octet-stream")
        return Response(content=static_path.read_bytes(), media_type=ct,
                        headers={"Cache-Control": "public, max-age=86400"})

    return app


# ---------------------------------------------------------------------------
# Helper — path containment check
# ---------------------------------------------------------------------------

def _is_subpath(child: Path, parent: Path) -> bool:
    """Return True if *child* is the same as or inside *parent*."""
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Helper — reconstruct Trace object from stored dict
# ---------------------------------------------------------------------------

def _reconstruct_trace(trace_data: dict[str, Any]) -> Trace:
    """Rebuild a Trace domain object from a storage dict (used for analysis)."""
    trace = Trace(
        trace_id=trace_data["trace_id"],
        service_name=trace_data.get("service_name", ""),
        start_time=trace_data.get("start_time", 0),
        end_time=trace_data.get("end_time", 0),
    )

    for sd in trace_data.get("spans", []):
        span = Span(
            span_id=sd["span_id"],
            trace_id=sd["trace_id"],
            parent_span_id=sd.get("parent_span_id"),
            name=sd["name"],
            kind=SpanKind(sd["kind"]),
            status=SpanStatus(sd["status"]),
            start_time=sd.get("start_time", 0),
            end_time=sd.get("end_time", 0),
            attributes=sd.get("attributes", {}),
        )

        tu = sd.get("token_usage")
        if tu:
            span.token_usage = TokenUsage(
                input_tokens=tu.get("input_tokens", 0),
                output_tokens=tu.get("output_tokens", 0),
                total_tokens=tu.get("input_tokens", 0) + tu.get("output_tokens", 0),
                total_cost_usd=tu.get("total_cost_usd", 0),
            )

        err = sd.get("error")
        if isinstance(err, dict):
            span.error_message = err.get("message")
            span.error_type = err.get("type")

        trace.spans.append(span)

    return trace

# NOTE: The new cost intelligence endpoints below are appended at module level
# but are registered inside the existing create_app() factory.  We instead
# patch them in via a secondary factory call.
