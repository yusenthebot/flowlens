"""
FlowLens server route modules.

Provides ``register_routes`` which mounts all API routers onto a FastAPI app.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from ..storage import TraceStore
from .traces import create_traces_router, create_experiments_router
from .cost import create_cost_router
from .agents import create_agents_router
from .stats import create_stats_router
from .alerts import create_alerts_router
from .system import create_system_router
from .sessions import create_sessions_router


def register_routes(
    app: FastAPI,
    store: TraceStore,
    ws_manager: Any,
    alert_engine: Any,
    server_start_time: float,
) -> None:
    """Mount all route modules onto *app*.

    Args:
        app: The FastAPI application instance.
        store: TraceStore for data persistence.
        ws_manager: ConnectionManager for WebSocket broadcast.
        alert_engine: AlertEngine for evaluating alert rules.
        server_start_time: Unix timestamp when the server started (for uptime).
    """
    app.include_router(create_traces_router(store, ws_manager, alert_engine))
    app.include_router(create_experiments_router(store))
    app.include_router(create_cost_router(store))
    app.include_router(create_agents_router(store))
    app.include_router(create_stats_router(store))
    app.include_router(create_alerts_router(store, alert_engine))
    app.include_router(create_system_router(store, server_start_time))
    app.include_router(create_sessions_router(store))
