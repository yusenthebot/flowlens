"""
System-level route handlers: health, export, activity stream, static files, dashboard.

Endpoints:
- GET /health
- GET /v1/export/report
- GET /v1/activity/stream
- GET /
- GET /dashboard
- GET /static/{filename}
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, Response

from ..storage import TraceStore
from ..utils import _parse_tags

logger = logging.getLogger(__name__)


def create_system_router(store: TraceStore, server_start_time: float) -> APIRouter:
    """Create and return the system router.

    Args:
        store: TraceStore instance for data persistence.
        server_start_time: Unix timestamp of when the server started.
    """
    router = APIRouter()

    @router.get("/health")
    async def health() -> dict[str, Any]:
        """
        Health check endpoint.

        Returns server status, version, uptime, and database metrics.
        """
        uptime_seconds = int(time.time() - server_start_time)
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

    @router.get("/v1/export/report")
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
            tags = _parse_tags(t.get("tags") or {})
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

    @router.get("/v1/activity/stream")
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
            tags = _parse_tags(trace_meta.get("tags") or {})
            agent = tags.get("agent", "unknown")

            # Get full trace with spans
            full = store.get_trace(trace_id)
            if not full or not full.get("spans"):
                continue

            for span in full["spans"]:
                tool_name = span.get("name", "")
                # Extract agent from span attributes or "agent/Tool" name format
                span_attrs = span.get("attributes") or {}
                span_agent = span_attrs.get("agent.name") or agent
                if span_agent == "unknown" and "/" in tool_name:
                    span_agent = tool_name.split("/", 1)[0]
                # Extract tool from "agent/Tool" format
                if "/" in tool_name:
                    tool_name = tool_name.split("/", 1)[1]

                events.append({
                    "agent": span_agent,
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
    # Dashboard HTML
    # -----------------------------------------------------------------------

    _dashboard_html: str | None = None

    def _load_dashboard() -> str:
        nonlocal _dashboard_html
        if _dashboard_html is None:
            dashboard_path = Path(__file__).parent.parent / "dashboard.html"
            _dashboard_html = dashboard_path.read_text(encoding="utf-8")
        return _dashboard_html

    @router.get("/", response_class=HTMLResponse)
    async def dashboard_root() -> HTMLResponse:
        """Serve the FlowLens dashboard."""
        return HTMLResponse(content=_load_dashboard())

    @router.get("/dashboard", response_class=HTMLResponse)
    async def dashboard_alias() -> HTMLResponse:
        """Serve the FlowLens dashboard (alias)."""
        return HTMLResponse(content=_load_dashboard())

    @router.get("/static/{filename}")
    async def serve_static(filename: str) -> Response:
        """Serve bundled static assets (Tailwind fallback, dashboard modules, etc.).

        Looks first in the ``static/`` subdirectory (for modular CSS/JS files),
        then falls back to the parent ``server/`` directory (for legacy .min.js
        bundles that were placed there before the modular split).
        """
        if not re.match(r'^[a-zA-Z0-9._-]+$', filename):
            return JSONResponse({"detail": "invalid filename"}, status_code=400)
        server_dir = Path(__file__).parent.parent
        # Prefer files in the static/ sub-directory (modular assets)
        static_subdir_path = server_dir / "static" / filename
        # Fall back to legacy location directly in server/ directory
        legacy_path = server_dir / filename
        if static_subdir_path.exists():
            static_path = static_subdir_path
        elif legacy_path.exists():
            static_path = legacy_path
        else:
            return JSONResponse({"detail": "not found"}, status_code=404)
        content_types = {".js": "application/javascript", ".css": "text/css"}
        ct = content_types.get(static_path.suffix, "application/octet-stream")
        return Response(content=static_path.read_bytes(), media_type=ct,
                        headers={"Cache-Control": "public, max-age=86400"})

    return router
