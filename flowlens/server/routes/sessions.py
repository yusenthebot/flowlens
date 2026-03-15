"""
Session grouping route handlers.

Endpoints:
- GET /v1/sessions
- GET /v1/sessions/{session_id}
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ..storage import TraceStore
from ..utils import _sanitize_id

logger = logging.getLogger(__name__)


def create_sessions_router(store: TraceStore) -> APIRouter:
    """Create and return the sessions router.

    Args:
        store: TraceStore instance for data persistence.
    """
    router = APIRouter()

    @router.get("/v1/sessions")
    async def list_sessions(
        limit: int = Query(20, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ) -> dict[str, Any]:
        """List sessions grouped by session_id, ordered by most recent activity."""
        try:
            sessions = store.list_sessions(limit=limit, offset=offset)
        except Exception:
            logger.exception("Failed to list sessions")
            raise HTTPException(500, "Failed to retrieve sessions")
        return {"sessions": sessions}

    @router.get("/v1/sessions/{session_id}")
    async def get_session(session_id: str) -> dict[str, Any]:
        """Get all traces in a session, ordered by start_time ascending."""
        _sanitize_id(session_id, "session_id")
        try:
            result = store.get_session(session_id)
        except Exception:
            logger.exception("Failed to get session %s", session_id[:32])
            raise HTTPException(500, "Failed to retrieve session")
        if result is None:
            raise HTTPException(404, "Session not found")
        return result

    return router
