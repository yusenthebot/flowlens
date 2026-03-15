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
- GET    /v1/agents/network        — richer agent network for 3D visualization
- GET    /v1/activity/stream        — recent activity events across all agents
- GET    /v1/export/report          — summary activity report (last N hours)
- GET    /health                    — health check
- WS     /ws/traces                 — real-time trace stream
"""

from __future__ import annotations

import logging
import os
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import Any

from fastapi import (
    FastAPI,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from ..alerting import AlertRule
from ..alerting.engine import AlertEngine
from ..config import settings
from ..logging_config import configure_logging
from .routes import register_routes
from .storage import TraceStore
from .utils import (
    _AGENT_PROFILES,
    _ALLOWED_IMPORT_DIRS,
    _MAX_SPANS_PER_INGEST,
    _reconstruct_trace,
    _sanitize_id,
)

logger = logging.getLogger(__name__)

# Re-export for backward compatibility with tests
__all__ = [
    "create_app",
    "_ALLOWED_IMPORT_DIRS",
    "_MAX_SPANS_PER_INGEST",
    "_RateLimiter",
    "_sanitize_id",
    "_reconstruct_trace",
    "_AGENT_PROFILES",
]


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
            k for k, hits in self._counts.items() if not any(t > window_start for t in hits)
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
        limit_override: int | None = None,
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
        retry_after = 0 if allowed else int(self._window - (now - self._counts[key][0]))
        return allowed, remaining, limit, retry_after


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
                client_ip,
                path,
                limit_key,
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
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' "
            "https://cdn.tailwindcss.com https://cdnjs.cloudflare.com "
            "https://cdn.jsdelivr.net https://unpkg.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "connect-src 'self' ws://localhost:* wss://localhost:*; "
            "img-src 'self' data: blob:"
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
    # Register all route modules
    # -----------------------------------------------------------------------

    register_routes(
        app=app,
        store=store,
        ws_manager=ws_manager,
        alert_engine=alert_engine,
        server_start_time=_server_start_time,
    )

    return app
