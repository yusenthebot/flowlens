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
- POST   /v1/traces/cleanup         — delete traces older than N days
- GET    /v1/cost/breakdown         — cost attribution
- GET    /v1/cost/trends            — cost over time (daily/hourly)
- GET    /v1/stats                  — global statistics
- GET    /v1/patterns/summary       — aggregate pattern statistics
- GET    /health                    — health check
- WS     /ws/traces                 — real-time trace stream
"""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

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
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .storage import TraceStore
from ..sdk.models import Span, SpanKind, SpanStatus, Trace, TokenUsage
from ..analysis.dag_builder import build_causal_dag
from ..analysis.patterns import detect_patterns
from ..config import settings
from ..logging_config import configure_logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class TraceIngestRequest(BaseModel):
    """Payload for POST /v1/traces/ingest."""
    trace_id: str = Field(..., min_length=1, description="Unique trace identifier")
    service_name: str = ""
    start_time: float = 0
    end_time: float = 0
    duration_ms: float = 0
    total_tokens: int = Field(0, ge=0)
    total_cost_usd: float = Field(0.0, ge=0)
    has_errors: bool = False
    error_count: int = Field(0, ge=0)
    span_count: int = Field(0, ge=0)
    metadata: dict[str, Any] = {}
    spans: list[dict[str, Any]] = []


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
    Very lightweight per-IP rate limiter using a sliding-window counter.

    Not suitable for multi-process deployments — use Redis for those.
    """

    def __init__(self, requests_per_minute: int = 120) -> None:
        self._limit = requests_per_minute
        self._window = 60  # seconds
        self._counts: dict[str, list[float]] = defaultdict(list)

    def check(self, client_ip: str) -> tuple[int, int, int]:
        """
        Record a request and return (remaining, limit, retry_after_seconds).

        retry_after_seconds is 0 when the request is within budget.
        """
        now = time.time()
        window_start = now - self._window
        hits = self._counts[client_ip]
        # Purge expired timestamps
        self._counts[client_ip] = [t for t in hits if t > window_start]
        self._counts[client_ip].append(now)
        used = len(self._counts[client_ip])
        remaining = max(0, self._limit - used)
        retry_after = 0 if used <= self._limit else int(self._window - (now - self._counts[client_ip][0]))
        return remaining, self._limit, retry_after


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app(db_path: str | None = None) -> FastAPI:
    """Create and return the configured FastAPI application instance."""

    configure_logging()

    store = TraceStore(db_path=db_path or settings.db_path)
    ws_manager = ConnectionManager()
    rate_limiter = _RateLimiter(requests_per_minute=settings.rate_limit)

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
        yield
        store.close()

    app = FastAPI(
        title="FlowLens",
        description="Agent Observability Platform — Chrome DevTools for LLM Agents",
        version="0.2.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # -----------------------------------------------------------------------
    # Middleware — request logging + rate-limit headers
    # -----------------------------------------------------------------------

    @app.middleware("http")
    async def logging_and_rate_limit(request: Request, call_next):  # type: ignore[no-untyped-def]
        start = time.perf_counter()
        client_ip = request.client.host if request.client else "unknown"

        remaining, limit, retry_after = rate_limiter.check(client_ip)

        response: Response = await call_next(request)

        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "%s %s %d %.1fms",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )

        # Attach standard rate-limit headers to every response
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
        payload = req.model_dump()
        store.save_trace(payload)

        # Broadcast lightweight summary (not full spans) to WS clients
        if ws_manager.connection_count:
            summary = {k: payload[k] for k in (
                "trace_id", "service_name", "start_time", "end_time",
                "duration_ms", "total_tokens", "total_cost_usd",
                "has_errors", "error_count", "span_count",
            )}
            await ws_manager.broadcast({"event": "trace_ingested", "data": summary})

        return {"status": "ok", "trace_id": req.trace_id}

    @app.post("/v1/traces/import", status_code=201)
    async def import_jsonl(file_path: str) -> dict[str, Any]:
        """Bulk-import traces from a JSONL file."""
        path = Path(file_path)
        if not path.exists():
            raise HTTPException(404, f"File not found: {file_path}")

        count = 0
        errors = 0
        with open(path) as f:
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
                    logger.warning("Failed to import trace: %s", e)

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
        traces = store.get_error_traces(limit=limit, offset=offset)
        return TraceListResponse(
            traces=traces, total=len(traces), limit=limit, offset=offset
        )

    @app.get("/v1/traces/search")
    async def search_traces(
        q: str = Query(..., min_length=1, description="Search term"),
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ) -> TraceListResponse:
        """
        Full-text search across trace service_name and span name / error_message.
        """
        if not q.strip():
            raise HTTPException(400, "Search query must not be blank")
        traces = store.search_traces(query=q.strip(), limit=limit, offset=offset)
        return TraceListResponse(
            traces=traces, total=len(traces), limit=limit, offset=offset
        )

    @app.post("/v1/traces/cleanup", status_code=200)
    async def cleanup_traces(req: CleanupRequest) -> dict[str, Any]:
        """Delete all traces older than ``req.days`` days."""
        deleted = store.cleanup_old_traces(days=req.days)
        return {"deleted": deleted, "days": req.days}

    @app.get("/v1/traces")
    async def list_traces(
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        service: Optional[str] = None,
        errors_only: bool = False,
    ) -> TraceListResponse:
        """List traces (paginated). Filter by service or errors."""
        traces = store.list_traces(
            limit=limit,
            offset=offset,
            service_name=service,
            has_errors=True if errors_only else None,
        )
        return TraceListResponse(
            traces=traces, total=len(traces), limit=limit, offset=offset
        )

    @app.get("/v1/traces/{trace_id}")
    async def get_trace(trace_id: str) -> dict[str, Any]:
        """Fetch full trace detail including all spans."""
        trace = store.get_trace(trace_id)
        if not trace:
            raise HTTPException(404, f"Trace not found: {trace_id}")
        return trace

    @app.delete("/v1/traces/{trace_id}", status_code=200)
    async def delete_trace(trace_id: str) -> dict[str, str]:
        """
        Permanently delete a trace and all its spans.

        Returns 404 if the trace does not exist.
        """
        deleted = store.delete_trace(trace_id)
        if not deleted:
            raise HTTPException(404, f"Trace not found: {trace_id}")
        return {"status": "deleted", "trace_id": trace_id}

    # -----------------------------------------------------------------------
    # Analysis
    # -----------------------------------------------------------------------

    @app.get("/v1/traces/{trace_id}/dag")
    async def get_trace_dag(trace_id: str) -> dict[str, Any]:
        """Build and return the causal DAG for a trace."""
        trace_data = store.get_trace(trace_id)
        if not trace_data:
            raise HTTPException(404, f"Trace not found: {trace_id}")

        trace = _reconstruct_trace(trace_data)
        dag = build_causal_dag(trace)
        detect_patterns(trace, dag)
        return dag.to_dict()

    # -----------------------------------------------------------------------
    # Cost
    # -----------------------------------------------------------------------

    @app.get("/v1/cost/breakdown")
    async def cost_breakdown(
        group_by: str = Query("service_name", pattern="^(service_name|kind|name)$"),
    ) -> list[dict[str, Any]]:
        """Cost attribution grouped by service, span kind, or span name."""
        return store.get_cost_breakdown(group_by=group_by)

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
        return store.get_cost_trends(granularity=granularity, limit=limit)

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
        return store.get_pattern_summary(limit=limit)

    # -----------------------------------------------------------------------
    # Stats
    # -----------------------------------------------------------------------

    @app.get("/v1/stats")
    async def get_stats() -> StatsResponse:
        """Global aggregate statistics."""
        stats = store.get_stats()
        return StatsResponse(
            total_traces=stats.get("total_traces") or 0,
            total_spans=stats.get("total_spans") or 0,
            total_tokens=stats.get("total_tokens") or 0,
            total_cost=stats.get("total_cost") or 0,
            error_traces=stats.get("error_traces") or 0,
            avg_duration_ms=stats.get("avg_duration_ms") or 0,
        )

    # -----------------------------------------------------------------------
    # Health
    # -----------------------------------------------------------------------

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": "0.2.0"}

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

    return app


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
