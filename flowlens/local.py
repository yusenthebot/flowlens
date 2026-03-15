"""
LocalCollector — Direct SQLite trace storage without HTTP server.

For local-only usage (e.g., Claude Code agent monitoring), bypasses
the HTTP server entirely. Traces are written directly to SQLite and
can be queried immediately.

Usage:
    from flowlens.local import LocalCollector

    collector = LocalCollector("~/.claude/flowlens/local.db")
    collector.ingest(trace_data)
    traces = collector.list_traces(limit=10)
    collector.close()

Context manager usage:
    with LocalCollector("~/.claude/flowlens/local.db") as collector:
        collector.ingest(trace_data)
        traces = collector.list_traces()
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class LocalCollector:
    """
    Direct SQLite trace collector — no HTTP server required.

    Wraps TraceStore to provide a clean, minimal API for writing and
    querying traces directly from local SQLite.  Suitable for embedded
    usage such as Claude Code agent monitoring, CI pipelines, or any
    scenario where running a full HTTP server is unnecessary overhead.

    Thread-safe: the underlying TraceStore uses WAL mode and a
    per-thread connection pool so concurrent ingestion is safe.

    Args:
        db_path: Path to the SQLite database file.  Directories are
                 created automatically.  Supports ``~`` expansion.
    """

    def __init__(self, db_path: str | Path = "./flowlens.db") -> None:
        expanded = Path(db_path).expanduser()
        from flowlens.server.storage import TraceStore

        self._store = TraceStore(db_path=str(expanded))
        # Serialise all DB access from multiple threads.  TraceStore's
        # primary connection is a single sqlite3.Connection shared across
        # all calls (reads and writes alike), and sqlite3 connections are not
        # thread-safe for concurrent use even in WAL mode.  A single lock
        # here keeps things correct without introducing complexity.
        self._lock = threading.Lock()
        logger.debug("LocalCollector initialised at %s", expanded)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def ingest(self, trace_data: dict[str, Any]) -> str:
        """
        Validate and persist a trace dict.

        The ``trace_data`` dict must follow the same schema produced by
        ``Trace.to_dict()``.  At minimum it must contain a non-empty
        ``trace_id`` key.

        Args:
            trace_data: Complete trace payload including spans.

        Returns:
            The ``trace_id`` of the saved trace.

        Raises:
            ValueError: If ``trace_id`` is missing or empty.
            Exception:  Propagates any storage-level errors.
        """
        trace_id = trace_data.get("trace_id", "")
        if not trace_id:
            raise ValueError("trace_data must contain a non-empty 'trace_id'")

        with self._lock:
            self._store.save_trace(trace_data)
        logger.debug("LocalCollector: ingested trace %s", str(trace_id)[:12])
        return trace_id

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def query(self, trace_id: str) -> dict[str, Any] | None:
        """
        Retrieve a single trace with all its spans.

        Args:
            trace_id: The trace identifier to look up.

        Returns:
            A trace dict (with a ``spans`` list) or ``None`` if not found.
        """
        with self._lock:
            return self._store.get_trace(trace_id)

    def list_traces(
        self,
        limit: int = 50,
        offset: int = 0,
        service: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        List traces ordered newest-first, without span detail.

        Args:
            limit:   Maximum number of traces to return.
            offset:  Number of traces to skip (for pagination).
            service: If provided, filter to this service name only.

        Returns:
            List of trace dicts (no ``spans`` key).
        """
        with self._lock:
            return self._store.list_traces(
                limit=limit,
                offset=offset,
                service_name=service,
            )

    def search(self, q: str) -> list[dict[str, Any]]:
        """
        Search spans by name or error message (case-insensitive substring).

        Also matches on trace ``service_name``.

        Args:
            q: Search term.

        Returns:
            List of matching trace dicts (no ``spans`` key).
        """
        with self._lock:
            return self._store.search_traces(query=q)

    def stats(self) -> dict[str, Any]:
        """
        Return aggregate statistics across all stored traces.

        Returned keys:
        - ``total_traces`` — total number of traces
        - ``total_spans``  — sum of span counts
        - ``total_tokens`` — cumulative token usage
        - ``total_cost``   — cumulative cost in USD
        - ``error_traces`` — number of traces with at least one error
        - ``avg_duration_ms`` — average trace duration

        Returns:
            Dict of aggregate values.
        """
        with self._lock:
            return self._store.get_stats()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying database connections."""
        try:
            self._store._pool.close_all()
            logger.debug("LocalCollector: connections closed")
        except Exception as exc:
            logger.warning("LocalCollector: error during close — %s", exc)

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> LocalCollector:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()
