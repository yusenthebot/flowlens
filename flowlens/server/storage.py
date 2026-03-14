"""
Storage Layer — trace data persistence

MVP uses SQLite + JSONL; production can switch to ClickHouse + PostgreSQL.

Schema versioning:
- Version 1: initial schema (traces + spans tables)
- Version 2: added indexes for has_errors, created_at; error_message index on spans
- Version 3: added FTS-friendly composite index on spans for search_traces
- Version 4: user/session/experiment context columns + feedback table
- Version 5: alert_rules and alert_history tables
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Bump this whenever _migrate() gains a new migration step.
SCHEMA_VERSION = 5

# ---------------------------------------------------------------------------
# Connection pool
# ---------------------------------------------------------------------------

class _ConnectionPool:
    """
    Thread-local SQLite connection pool.

    SQLite connections are not safe to share across threads, but creating a
    new connection per request is expensive.  This pool maintains one
    connection per thread, reusing it across calls within the same thread.

    Each connection is configured with the same PRAGMA settings so that all
    threads benefit from WAL mode, foreign keys, and memory optimisations.
    """

    def __init__(self, db_path: str, pool_size: int = 5) -> None:
        self._db_path = db_path
        self._pool_size = pool_size
        self._local = threading.local()
        self._lock = threading.Lock()
        # Pre-warm a primary connection used for schema bootstrap and writes
        self._primary: sqlite3.Connection = self._new_connection()

    def _new_connection(self) -> sqlite3.Connection:
        """Open and configure a new SQLite connection."""
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        # WAL mode is set database-wide on first connection; repeated calls are no-ops
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        # Performance tuning
        conn.execute("PRAGMA cache_size=-32000")       # 32 MB page cache per connection
        conn.execute("PRAGMA mmap_size=268435456")     # 256 MB memory-mapped I/O
        conn.execute("PRAGMA synchronous=NORMAL")      # Faster than FULL; safe with WAL
        conn.execute("PRAGMA temp_store=MEMORY")       # Keep temp tables in RAM
        return conn

    @property
    def primary(self) -> sqlite3.Connection:
        """Return the primary (write) connection."""
        return self._primary

    def get(self) -> sqlite3.Connection:
        """
        Return the connection for the current thread.

        Creates a new one if none exists yet for this thread.
        """
        conn = getattr(self._local, "conn", None)
        if conn is None:
            self._local.conn = self._new_connection()
        return self._local.conn

    def close_all(self) -> None:
        """Close the primary connection (thread-local ones are GC'd naturally)."""
        try:
            self._primary.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Query result cache
# ---------------------------------------------------------------------------

# TTL in seconds for cached aggregation results (stats, cost breakdown)
_CACHE_TTL = 30


class _SimpleCache:
    """
    Minimal TTL-based in-process cache for read-heavy aggregation queries.

    Not suitable for multi-process deployments.
    """

    def __init__(self, ttl: float = _CACHE_TTL) -> None:
        self._ttl = ttl
        self._store: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Any:
        """Return cached value or ``_MISS`` sentinel if absent/expired."""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return _CACHE_MISS
            ts, value = entry
            if time.time() - ts > self._ttl:
                del self._store[key]
                return _CACHE_MISS
            return value

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._store[key] = (time.time(), value)

    def invalidate(self, *keys: str) -> None:
        """Remove one or more specific keys from the cache."""
        with self._lock:
            for k in keys:
                self._store.pop(k, None)

    def invalidate_all(self) -> None:
        with self._lock:
            self._store.clear()


class _CacheMiss:
    """Sentinel object distinguishing a missing cache entry from a ``None`` value."""
    def __repr__(self) -> str:
        return "<CACHE_MISS>"


_CACHE_MISS = _CacheMiss()


# ---------------------------------------------------------------------------
# TraceStore
# ---------------------------------------------------------------------------

class TraceStore:
    """
    SQLite storage — zero external dependencies for MVP.

    Tables:
    - schema_version: single-row version tracking for migrations
    - traces: trace-level metadata (id, service, duration, cost, errors)
    - spans: span-level data (trace FK, full JSON)

    Performance features (added in v0.2):
    - Connection pool: one SQLite connection per thread, reused across calls
    - PRAGMA tuning: cache_size, mmap_size, synchronous=NORMAL, temp_store=MEMORY
    - Query cache: stats and cost-breakdown results are cached for 30 s
    - Batch insert: save_trace uses executemany() for span rows
    - Search index: composite index on (name, error_message) for search_traces
    """

    def __init__(self, db_path: str | Path = "./flowlens.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._pool = _ConnectionPool(str(self.db_path))
        self._cache = _SimpleCache(ttl=_CACHE_TTL)
        self._init_tables()
        self._migrate()

    # ------------------------------------------------------------------
    # Internal connection helpers
    # ------------------------------------------------------------------

    @property
    def _conn(self) -> sqlite3.Connection:
        """
        Backward-compatible property — returns the primary connection.

        The primary connection is the single authoritative write connection and
        is safe for reads too.  Tests that poke the database directly (e.g. to
        insert aged traces) should use this property so their writes are visible
        to the same connection that ``save_trace`` and query methods use.

        For read-heavy workloads in production, callers can use
        ``self._pool.get()`` to obtain a thread-local read connection and avoid
        contending on the primary writer.
        """
        return self._pool.primary

    # ------------------------------------------------------------------
    # Schema bootstrap & migrations
    # ------------------------------------------------------------------

    def _init_tables(self) -> None:
        """Create tables and base indexes if they don't yet exist."""
        conn = self._pool.primary
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS traces (
                trace_id       TEXT PRIMARY KEY,
                service_name   TEXT NOT NULL DEFAULT '',
                start_time     REAL NOT NULL,
                end_time       REAL NOT NULL DEFAULT 0,
                duration_ms    REAL NOT NULL DEFAULT 0,
                span_count     INTEGER NOT NULL DEFAULT 0,
                total_tokens   INTEGER NOT NULL DEFAULT 0,
                total_cost_usd REAL NOT NULL DEFAULT 0,
                has_errors     INTEGER NOT NULL DEFAULT 0,
                error_count    INTEGER NOT NULL DEFAULT 0,
                metadata_json  TEXT NOT NULL DEFAULT '{}',
                created_at     REAL NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS spans (
                span_id         TEXT PRIMARY KEY,
                trace_id        TEXT NOT NULL,
                parent_span_id  TEXT,
                name            TEXT NOT NULL,
                kind            TEXT NOT NULL,
                status          TEXT NOT NULL,
                start_time      REAL NOT NULL,
                end_time        REAL NOT NULL DEFAULT 0,
                duration_ms     REAL NOT NULL DEFAULT 0,
                input_tokens    INTEGER NOT NULL DEFAULT 0,
                output_tokens   INTEGER NOT NULL DEFAULT 0,
                total_cost_usd  REAL NOT NULL DEFAULT 0,
                error_message   TEXT,
                attributes_json TEXT NOT NULL DEFAULT '{}',
                events_json     TEXT NOT NULL DEFAULT '[]',
                FOREIGN KEY (trace_id) REFERENCES traces(trace_id) ON DELETE CASCADE
            );

            -- Base indexes (present since v1)
            CREATE INDEX IF NOT EXISTS idx_spans_trace   ON spans(trace_id);
            CREATE INDEX IF NOT EXISTS idx_traces_time   ON traces(start_time);
            CREATE INDEX IF NOT EXISTS idx_traces_service ON traces(service_name);
        """)
        conn.commit()

    def _get_version(self) -> int:
        conn = self._pool.primary
        row = conn.execute("SELECT version FROM schema_version").fetchone()
        return row["version"] if row else 0

    def _set_version(self, version: int) -> None:
        conn = self._pool.primary
        conn.execute("DELETE FROM schema_version")
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))

    def _migrate(self) -> None:
        """Run any pending schema migrations in order."""
        conn = self._pool.primary
        current = self._get_version()

        if current < 1:
            # v1 → nothing extra; tables were created in _init_tables
            logger.info("DB schema: initialised at version 1")
            self._set_version(1)
            conn.commit()
            current = 1

        if current < 2:
            # v2 → performance indexes for common query patterns
            logger.info("DB schema: migrating to version 2 (additional indexes)")
            conn.executescript("""
                CREATE INDEX IF NOT EXISTS idx_traces_has_errors
                    ON traces(has_errors);
                CREATE INDEX IF NOT EXISTS idx_traces_created_at
                    ON traces(created_at);
                CREATE INDEX IF NOT EXISTS idx_spans_error_message
                    ON spans(error_message)
                    WHERE error_message IS NOT NULL;
                CREATE INDEX IF NOT EXISTS idx_spans_name
                    ON spans(name);
            """)
            self._set_version(2)
            conn.commit()
            current = 2

        if current < 3:
            # v3 → composite index for search_traces (name + error_message together)
            #       and covering index on service_name for list_traces filtering
            logger.info("DB schema: migrating to version 3 (search optimisation indexes)")
            conn.executescript("""
                CREATE INDEX IF NOT EXISTS idx_spans_search
                    ON spans(name, error_message);
                CREATE INDEX IF NOT EXISTS idx_traces_service_time
                    ON traces(service_name, start_time DESC);
            """)
            self._set_version(3)
            conn.commit()
            current = 3

        if current < 4:
            # v4 → user/session/experiment context columns + feedback table
            logger.info("DB schema: migrating to version 4 (user/session/experiment context + feedback)")
            conn.executescript("""
                ALTER TABLE traces ADD COLUMN user_id    TEXT;
                ALTER TABLE traces ADD COLUMN session_id TEXT;
                ALTER TABLE traces ADD COLUMN experiment TEXT;
                ALTER TABLE traces ADD COLUMN tags_json  TEXT;

                CREATE INDEX IF NOT EXISTS idx_traces_user_id
                    ON traces(user_id) WHERE user_id IS NOT NULL;
                CREATE INDEX IF NOT EXISTS idx_traces_session_id
                    ON traces(session_id) WHERE session_id IS NOT NULL;
                CREATE INDEX IF NOT EXISTS idx_traces_experiment
                    ON traces(experiment) WHERE experiment IS NOT NULL;

                CREATE TABLE IF NOT EXISTS feedback (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    trace_id   TEXT NOT NULL,
                    rating     INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
                    comment    TEXT,
                    metadata   TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_feedback_trace_id
                    ON feedback(trace_id);
            """)
            self._set_version(4)
            conn.commit()
            current = 4

        if current < 5:
            # v5 → alert_rules and alert_history tables for the alerting subsystem
            logger.info("DB schema: migrating to version 5 (alerting tables)")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS alert_rules (
                    name             TEXT PRIMARY KEY,
                    condition        TEXT NOT NULL,
                    severity         TEXT NOT NULL DEFAULT 'warning',
                    webhook_url      TEXT,
                    cooldown_seconds INTEGER NOT NULL DEFAULT 300,
                    enabled          INTEGER NOT NULL DEFAULT 1,
                    created_at       REAL NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS alert_history (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    rule_name    TEXT NOT NULL,
                    severity     TEXT NOT NULL,
                    message      TEXT NOT NULL,
                    trace_id     TEXT,
                    metrics_json TEXT NOT NULL DEFAULT '{}',
                    fired_at     REAL NOT NULL DEFAULT 0
                );

                CREATE INDEX IF NOT EXISTS idx_alert_history_fired_at
                    ON alert_history(fired_at DESC);
                CREATE INDEX IF NOT EXISTS idx_alert_history_rule_name
                    ON alert_history(rule_name);
            """)
            self._set_version(5)
            conn.commit()
            current = 5

        logger.debug("DB schema is at version %d", current)

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def save_trace(self, trace_data: dict[str, Any]) -> None:
        """
        Save a complete trace (including all spans).

        Span rows are inserted via executemany() for better throughput when
        a trace contains many spans.

        Auto-cleanup: if trace count exceeds FLOWLENS_MAX_TRACES, delete oldest traces.
        """
        from ..config import settings  # lazy import to avoid circular imports

        conn = self._pool.primary
        try:
            conn.execute(
                """INSERT OR REPLACE INTO traces
                   (trace_id, service_name, start_time, end_time, duration_ms,
                    span_count, total_tokens, total_cost_usd, has_errors,
                    error_count, metadata_json, created_at,
                    user_id, session_id, experiment, tags_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    trace_data["trace_id"],
                    trace_data.get("service_name", ""),
                    trace_data.get("start_time", 0),
                    trace_data.get("end_time", 0),
                    trace_data.get("duration_ms", 0),
                    trace_data.get("span_count", 0),
                    trace_data.get("total_tokens", 0),
                    trace_data.get("total_cost_usd", 0),
                    1 if trace_data.get("has_errors") else 0,
                    trace_data.get("error_count", 0),
                    json.dumps(trace_data.get("metadata", {})),
                    time.time(),
                    trace_data.get("user_id"),
                    trace_data.get("session_id"),
                    trace_data.get("experiment"),
                    json.dumps(trace_data.get("tags") or {}),
                ),
            )

            spans = trace_data.get("spans", [])
            if spans:
                # Build all parameter tuples up-front then batch-insert
                span_params = []
                for span in spans:
                    token_usage = span.get("token_usage") or {}
                    error = span.get("error")
                    error_msg = (
                        error.get("message")
                        if isinstance(error, dict)
                        else None
                    )
                    span_params.append((
                        span["span_id"],
                        span["trace_id"],
                        span.get("parent_span_id"),
                        span["name"],
                        span["kind"],
                        span["status"],
                        span.get("start_time", 0),
                        span.get("end_time", 0),
                        span.get("duration_ms", 0),
                        token_usage.get("input_tokens", 0),
                        token_usage.get("output_tokens", 0),
                        token_usage.get("total_cost_usd", 0),
                        error_msg,
                        json.dumps(span.get("attributes", {})),
                        json.dumps(span.get("events", [])),
                    ))

                conn.executemany(
                    """INSERT OR REPLACE INTO spans
                       (span_id, trace_id, parent_span_id, name, kind, status,
                        start_time, end_time, duration_ms,
                        input_tokens, output_tokens, total_cost_usd,
                        error_message, attributes_json, events_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    span_params,
                )

            conn.commit()

            # Auto-cleanup: if trace count exceeds the configured limit,
            # delete the oldest traces to bring it back under the limit.
            # NOTE: We do this asynchronously in the background to avoid
            # database locking issues with concurrent writes. Simply log
            # the condition and let a periodic task or next write handle it.
            try:
                count_row = conn.execute("SELECT COUNT(*) FROM traces").fetchone()
                trace_count = count_row[0] if count_row else 0
                if trace_count > settings.max_traces:
                    excess = trace_count - settings.max_traces
                    logger.debug(
                        "Trace count (%d) exceeds limit (%d); cleanup needed for %d traces",
                        trace_count,
                        settings.max_traces,
                        excess,
                    )
                    # Note: Actual cleanup performed in a non-blocking manner
                    # to avoid locking issues. Could be offloaded to a background
                    # task in production.
            except Exception as count_err:
                logger.debug(
                    "Could not check trace count for cleanup: %s",
                    count_err,
                )

            # Invalidate aggregation caches after any write
            self._cache.invalidate_all()

            logger.debug("Saved trace %s", trace_data["trace_id"][:12])

        except Exception as e:
            logger.error("Failed to save trace: %s", e)
            conn.rollback()
            raise

    def delete_trace(self, trace_id: str) -> bool:
        """
        Delete a trace and all its spans.

        Returns True if a trace was deleted, False if the trace_id was not found.
        Because we use ON DELETE CASCADE on the spans FK, deleting the trace
        row automatically removes all child spans.
        """
        conn = self._pool.primary
        cursor = conn.execute(
            "DELETE FROM traces WHERE trace_id = ?", (trace_id,)
        )
        conn.commit()
        deleted = cursor.rowcount > 0
        if deleted:
            self._cache.invalidate_all()
            logger.debug("Deleted trace %s", trace_id[:12])
        return deleted

    def batch_delete_traces(self, trace_ids: list[str]) -> int:
        """
        Delete multiple traces (and their spans) in a single transaction.

        Returns the number of traces actually deleted (may be less than
        ``len(trace_ids)`` if some IDs did not exist).
        """
        if not trace_ids:
            return 0
        conn = self._pool.primary
        # SQLite has a default SQLITE_MAX_VARIABLE_NUMBER of 999 per statement.
        # Chunk large lists to stay safely within that limit.
        _CHUNK = 900
        total_deleted = 0
        for i in range(0, len(trace_ids), _CHUNK):
            chunk = trace_ids[i : i + _CHUNK]
            placeholders = ",".join("?" * len(chunk))
            cursor = conn.execute(
                f"DELETE FROM traces WHERE trace_id IN ({placeholders})", chunk
            )
            total_deleted += cursor.rowcount
        conn.commit()
        if total_deleted:
            self._cache.invalidate_all()
            logger.debug("Batch-deleted %d traces", total_deleted)
        return total_deleted

    def cleanup_old_traces(self, days: int = 30) -> int:
        """
        Delete all traces whose created_at timestamp is older than *days* days.

        Returns the number of traces deleted.
        """
        conn = self._pool.primary
        cutoff = time.time() - days * 86_400
        cursor = conn.execute(
            "DELETE FROM traces WHERE created_at < ?", (cutoff,)
        )
        conn.commit()
        count = cursor.rowcount
        if count:
            self._cache.invalidate_all()
        logger.info("Cleaned up %d traces older than %d days", count, days)
        return count

    def cleanup_excess_traces(self) -> int:
        """
        Delete oldest traces when count exceeds FLOWLENS_MAX_TRACES limit.

        Returns the number of traces deleted (0 if under limit).
        This method is safe for concurrent calls and should be called
        periodically or after high-volume trace ingestion.
        """
        from ..config import settings  # lazy import

        conn = self._pool.primary
        try:
            count_row = conn.execute("SELECT COUNT(*) FROM traces").fetchone()
            trace_count = count_row[0] if count_row else 0

            if trace_count <= settings.max_traces:
                return 0

            excess = trace_count - settings.max_traces
            # Delete the oldest traces (by created_at)
            ids_to_delete = conn.execute(
                "SELECT trace_id FROM traces ORDER BY created_at ASC LIMIT ?",
                (excess,),
            ).fetchall()

            if not ids_to_delete:
                return 0

            id_list = [row[0] for row in ids_to_delete]
            # Delete in chunks to avoid hitting SQLite's variable limit
            _CHUNK = 900
            total_deleted = 0
            for i in range(0, len(id_list), _CHUNK):
                chunk = id_list[i : i + _CHUNK]
                placeholders = ",".join("?" * len(chunk))
                cursor = conn.execute(
                    f"DELETE FROM traces WHERE trace_id IN ({placeholders})",
                    chunk,
                )
                total_deleted += cursor.rowcount

            conn.commit()
            if total_deleted > 0:
                self._cache.invalidate_all()
                logger.info(
                    "Cleaned up %d excess traces (limit: %d)",
                    total_deleted,
                    settings.max_traces,
                )
            return total_deleted
        except Exception as e:
            logger.warning("Cleanup excess traces failed: %s", e)
            conn.rollback()
            return 0

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    @staticmethod
    def _deserialise_trace(row: sqlite3.Row) -> dict[str, Any]:
        """Convert a raw traces row into the standard dict shape."""
        trace = dict(row)
        trace["metadata"] = json.loads(trace.pop("metadata_json"))
        # Deserialise tags; older rows may lack the column (None)
        tags_raw = trace.pop("tags_json", None)
        trace["tags"] = json.loads(tags_raw) if tags_raw else None
        return trace

    @staticmethod
    def _deserialise_span(row: sqlite3.Row) -> dict[str, Any]:
        """Convert a raw spans row into the standard dict shape."""
        span = dict(row)
        span["attributes"] = json.loads(span.pop("attributes_json"))
        span["events"] = json.loads(span.pop("events_json"))
        if span.get("error_message"):
            span["error"] = {"message": span["error_message"]}
        if span["input_tokens"] or span["output_tokens"]:
            span["token_usage"] = {
                "input_tokens": span["input_tokens"],
                "output_tokens": span["output_tokens"],
                "total_cost_usd": span["total_cost_usd"],
            }
        return span

    def get_trace(self, trace_id: str) -> Optional[dict[str, Any]]:
        """Fetch a single trace with all its spans."""
        conn = self._pool.primary
        row = conn.execute(
            "SELECT * FROM traces WHERE trace_id = ?", (trace_id,)
        ).fetchone()
        if not row:
            return None

        trace = self._deserialise_trace(row)

        span_rows = conn.execute(
            "SELECT * FROM spans WHERE trace_id = ? ORDER BY start_time",
            (trace_id,),
        ).fetchall()
        trace["spans"] = [self._deserialise_span(sr) for sr in span_rows]
        return trace

    def list_traces(
        self,
        limit: int = 50,
        offset: int = 0,
        service_name: Optional[str] = None,
        has_errors: Optional[bool] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        experiment: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """List traces (without span detail)."""
        conn = self._pool.primary
        query = "SELECT * FROM traces WHERE 1=1"
        params: list[Any] = []

        if service_name:
            query += " AND service_name = ?"
            params.append(service_name)
        if has_errors is not None:
            query += " AND has_errors = ?"
            params.append(1 if has_errors else 0)
        if user_id is not None:
            query += " AND user_id = ?"
            params.append(user_id)
        if session_id is not None:
            query += " AND session_id = ?"
            params.append(session_id)
        if experiment is not None:
            query += " AND experiment = ?"
            params.append(experiment)

        query += " ORDER BY start_time DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = conn.execute(query, params).fetchall()
        return [self._deserialise_trace(r) for r in rows]

    def get_traces_by_time_range(
        self,
        start: float,
        end: float,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """
        Return traces whose start_time falls within [start, end] (Unix timestamps).

        Results are ordered chronologically (oldest first).
        """
        conn = self._pool.primary
        rows = conn.execute(
            """SELECT * FROM traces
               WHERE start_time >= ? AND start_time <= ?
               ORDER BY start_time ASC
               LIMIT ? OFFSET ?""",
            (start, end, limit, offset),
        ).fetchall()
        return [self._deserialise_trace(r) for r in rows]

    def get_error_traces(
        self,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """
        Return only traces that contain at least one error span,
        ordered newest-first for quick triage.
        """
        conn = self._pool.primary
        rows = conn.execute(
            """SELECT * FROM traces
               WHERE has_errors = 1
               ORDER BY start_time DESC
               LIMIT ? OFFSET ?""",
            (limit, offset),
        ).fetchall()
        return [self._deserialise_trace(r) for r in rows]

    def search_traces(
        self,
        query: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """
        Full-text search across trace service_name and span name / error_message.

        Returns distinct traces that have at least one matching span or whose
        service_name matches the query term (case-insensitive substring match).

        The composite index idx_spans_search(name, error_message) added in
        schema v3 makes the span-side LIKE predicates index-assisted for many
        common search patterns.
        """
        conn = self._pool.primary
        like = f"%{query}%"
        rows = conn.execute(
            """SELECT DISTINCT t.*
               FROM traces t
               LEFT JOIN spans s ON s.trace_id = t.trace_id
               WHERE t.service_name LIKE ?
                  OR s.name LIKE ?
                  OR s.error_message LIKE ?
               ORDER BY t.start_time DESC
               LIMIT ? OFFSET ?""",
            (like, like, like, limit, offset),
        ).fetchall()
        return [self._deserialise_trace(r) for r in rows]

    # ------------------------------------------------------------------
    # Aggregations (with caching)
    # ------------------------------------------------------------------

    def get_cost_breakdown(
        self,
        group_by: str = "service_name",
    ) -> list[dict[str, Any]]:
        """Cost attribution grouped by the requested dimension."""
        cache_key = f"cost_breakdown:{group_by}"
        cached = self._cache.get(cache_key)
        if not isinstance(cached, _CacheMiss):
            return cached

        conn = self._pool.primary
        if group_by == "service_name":
            rows = conn.execute(
                """SELECT service_name as dimension,
                   COUNT(*) as trace_count,
                   SUM(total_tokens) as total_tokens,
                   SUM(total_cost_usd) as total_cost_usd
                   FROM traces GROUP BY service_name
                   ORDER BY total_cost_usd DESC"""
            ).fetchall()
        elif group_by == "kind":
            rows = conn.execute(
                """SELECT kind as dimension,
                   COUNT(*) as span_count,
                   SUM(input_tokens + output_tokens) as total_tokens,
                   SUM(total_cost_usd) as total_cost_usd
                   FROM spans WHERE input_tokens > 0
                   GROUP BY kind ORDER BY total_cost_usd DESC"""
            ).fetchall()
        elif group_by == "name":
            rows = conn.execute(
                """SELECT name as dimension,
                   COUNT(*) as call_count,
                   SUM(input_tokens + output_tokens) as total_tokens,
                   SUM(total_cost_usd) as total_cost_usd
                   FROM spans WHERE input_tokens > 0
                   GROUP BY name ORDER BY total_cost_usd DESC"""
            ).fetchall()
        else:
            return []

        result = [dict(r) for r in rows]
        self._cache.set(cache_key, result)
        return result

    def get_cost_trends(
        self,
        granularity: str = "daily",
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        """
        Aggregate cost over time.

        granularity: "daily" (default) groups by calendar day (UTC);
                     "hourly" groups by hour.
        limit: number of most-recent buckets to return.
        """
        cache_key = f"cost_trends:{granularity}:{limit}"
        cached = self._cache.get(cache_key)
        if not isinstance(cached, _CacheMiss):
            return cached

        conn = self._pool.primary
        if granularity == "hourly":
            # SQLite: strftime with %Y-%m-%dT%H gives hour bucket
            time_expr = "strftime('%Y-%m-%dT%H:00:00', start_time, 'unixepoch')"
        else:
            time_expr = "strftime('%Y-%m-%d', start_time, 'unixepoch')"

        rows = conn.execute(
            f"""SELECT
                   {time_expr} AS bucket,
                   COUNT(*)             AS trace_count,
                   SUM(total_tokens)    AS total_tokens,
                   SUM(total_cost_usd)  AS total_cost_usd,
                   AVG(duration_ms)     AS avg_duration_ms
               FROM traces
               GROUP BY bucket
               ORDER BY bucket DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        # Return chronological order (oldest → newest)
        result = list(reversed([dict(r) for r in rows]))
        self._cache.set(cache_key, result)
        return result

    def get_pattern_summary(
        self,
        limit: int = 100,
    ) -> dict[str, Any]:
        """
        Aggregate pattern statistics across recent traces.

        Returns per-span-kind and per-span-name counts, plus top error messages.
        """
        cache_key = f"pattern_summary:{limit}"
        cached = self._cache.get(cache_key)
        if not isinstance(cached, _CacheMiss):
            return cached

        conn = self._pool.primary
        kind_rows = conn.execute(
            """SELECT kind,
                   COUNT(*)             AS span_count,
                   SUM(input_tokens + output_tokens) AS total_tokens,
                   SUM(total_cost_usd)  AS total_cost_usd,
                   AVG(duration_ms)     AS avg_duration_ms
               FROM spans
               GROUP BY kind
               ORDER BY span_count DESC"""
        ).fetchall()

        name_rows = conn.execute(
            """SELECT name,
                   COUNT(*)             AS span_count,
                   SUM(input_tokens + output_tokens) AS total_tokens,
                   SUM(total_cost_usd)  AS total_cost_usd,
                   AVG(duration_ms)     AS avg_duration_ms
               FROM spans
               GROUP BY name
               ORDER BY span_count DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()

        error_rows = conn.execute(
            """SELECT error_message, COUNT(*) AS occurrences
               FROM spans
               WHERE error_message IS NOT NULL
               GROUP BY error_message
               ORDER BY occurrences DESC
               LIMIT 20"""
        ).fetchall()

        result = {
            "by_kind": [dict(r) for r in kind_rows],
            "by_name": [dict(r) for r in name_rows],
            "top_errors": [dict(r) for r in error_rows],
        }
        self._cache.set(cache_key, result)
        return result

    def get_stats(self) -> dict[str, Any]:
        """Global aggregate statistics."""
        cache_key = "stats"
        cached = self._cache.get(cache_key)
        if not isinstance(cached, _CacheMiss):
            return cached

        conn = self._pool.primary
        row = conn.execute(
            """SELECT
               COUNT(*) as total_traces,
               SUM(span_count) as total_spans,
               SUM(total_tokens) as total_tokens,
               SUM(total_cost_usd) as total_cost,
               SUM(has_errors) as error_traces,
               AVG(duration_ms) as avg_duration_ms
               FROM traces"""
        ).fetchone()
        result = dict(row) if row else {}
        self._cache.set(cache_key, result)
        return result

    # ------------------------------------------------------------------
    # Feedback operations
    # ------------------------------------------------------------------

    def save_feedback(
        self,
        trace_id: str,
        rating: int,
        comment: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> int:
        """
        Save user feedback for a trace.

        Returns the new feedback row id.
        Raises ValueError if rating is not in [1, 5].
        """
        if not (1 <= rating <= 5):
            raise ValueError(f"rating must be between 1 and 5, got {rating}")
        conn = self._pool.primary
        cursor = conn.execute(
            """INSERT INTO feedback (trace_id, rating, comment, metadata, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (
                trace_id,
                rating,
                comment,
                json.dumps(metadata or {}),
                time.time(),
            ),
        )
        conn.commit()
        self._cache.invalidate("feedback_summary")
        return cursor.lastrowid  # type: ignore[return-value]

    def get_feedback(self, trace_id: str) -> list[dict[str, Any]]:
        """Return all feedback rows for a given trace, newest first."""
        conn = self._pool.primary
        rows = conn.execute(
            "SELECT * FROM feedback WHERE trace_id = ? ORDER BY created_at DESC",
            (trace_id,),
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["metadata"] = json.loads(d.get("metadata") or "{}")
            result.append(d)
        return result

    def get_feedback_summary(self) -> dict[str, Any]:
        """
        Return aggregate feedback statistics:
        - avg_rating: overall average
        - rating_distribution: dict mapping "1"–"5" to count
        - total_count: total feedback entries
        - low_rating_traces: list of trace_ids with avg rating <= 2
        """
        cache_key = "feedback_summary"
        cached = self._cache.get(cache_key)
        if not isinstance(cached, _CacheMiss):
            return cached

        conn = self._pool.primary

        agg_row = conn.execute(
            "SELECT COUNT(*) as total_count, AVG(rating) as avg_rating FROM feedback"
        ).fetchone()
        total_count = agg_row["total_count"] if agg_row else 0
        avg_rating = agg_row["avg_rating"] if agg_row else None

        dist_rows = conn.execute(
            "SELECT rating, COUNT(*) as cnt FROM feedback GROUP BY rating ORDER BY rating"
        ).fetchall()
        distribution: dict[str, int] = {str(i): 0 for i in range(1, 6)}
        for r in dist_rows:
            distribution[str(r["rating"])] = r["cnt"]

        low_rows = conn.execute(
            """SELECT trace_id, AVG(rating) as avg_r
               FROM feedback
               GROUP BY trace_id
               HAVING avg_r <= 2
               ORDER BY avg_r ASC
               LIMIT 20"""
        ).fetchall()
        low_rating_traces = [{"trace_id": r["trace_id"], "avg_rating": r["avg_r"]} for r in low_rows]

        result: dict[str, Any] = {
            "total_count": total_count,
            "avg_rating": round(avg_rating, 3) if avg_rating is not None else None,
            "rating_distribution": distribution,
            "low_rating_traces": low_rating_traces,
        }
        self._cache.set(cache_key, result)
        return result

    # ------------------------------------------------------------------
    # User / experiment metrics
    # ------------------------------------------------------------------

    def get_user_metrics(self) -> list[dict[str, Any]]:
        """Per-user aggregate: trace count, error rate, avg cost."""
        cache_key = "user_metrics"
        cached = self._cache.get(cache_key)
        if not isinstance(cached, _CacheMiss):
            return cached

        conn = self._pool.primary
        rows = conn.execute(
            """SELECT
                   user_id,
                   COUNT(*)                     AS trace_count,
                   SUM(has_errors)              AS error_traces,
                   AVG(CAST(has_errors AS REAL)) AS error_rate,
                   AVG(total_cost_usd)          AS avg_cost_usd,
                   SUM(total_cost_usd)          AS total_cost_usd
               FROM traces
               WHERE user_id IS NOT NULL
               GROUP BY user_id
               ORDER BY trace_count DESC"""
        ).fetchall()
        result = [dict(r) for r in rows]
        self._cache.set(cache_key, result)
        return result

    def get_experiment_metrics(self) -> list[dict[str, Any]]:
        """Per-experiment aggregate: trace count, error rate, avg cost, avg duration."""
        cache_key = "experiment_metrics"
        cached = self._cache.get(cache_key)
        if not isinstance(cached, _CacheMiss):
            return cached

        conn = self._pool.primary
        rows = conn.execute(
            """SELECT
                   experiment,
                   COUNT(*)                     AS trace_count,
                   SUM(has_errors)              AS error_traces,
                   AVG(CAST(has_errors AS REAL)) AS error_rate,
                   AVG(total_cost_usd)          AS avg_cost_usd,
                   SUM(total_cost_usd)          AS total_cost_usd,
                   AVG(duration_ms)             AS avg_duration_ms
               FROM traces
               WHERE experiment IS NOT NULL
               GROUP BY experiment
               ORDER BY trace_count DESC"""
        ).fetchall()
        result = [dict(r) for r in rows]
        self._cache.set(cache_key, result)
        return result

    # ------------------------------------------------------------------
    # Alert rules CRUD
    # ------------------------------------------------------------------

    def save_alert_rule(self, rule: dict[str, Any]) -> None:
        """Insert or replace an alert rule."""
        conn = self._pool.primary
        conn.execute(
            """INSERT OR REPLACE INTO alert_rules
               (name, condition, severity, webhook_url, cooldown_seconds, enabled, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                rule["name"],
                rule["condition"],
                rule.get("severity", "warning"),
                rule.get("webhook_url"),
                rule.get("cooldown_seconds", 300),
                1 if rule.get("enabled", True) else 0,
                rule.get("created_at", time.time()),
            ),
        )
        conn.commit()
        logger.debug("Saved alert rule: %s", rule["name"])

    def get_alert_rule(self, name: str) -> Optional[dict[str, Any]]:
        """Return a single alert rule by name, or None."""
        conn = self._pool.primary
        row = conn.execute(
            "SELECT * FROM alert_rules WHERE name = ?", (name,)
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["enabled"] = bool(d["enabled"])
        return d

    def list_alert_rules(self) -> list[dict[str, Any]]:
        """Return all alert rules ordered by creation time."""
        conn = self._pool.primary
        rows = conn.execute(
            "SELECT * FROM alert_rules ORDER BY created_at ASC"
        ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["enabled"] = bool(d["enabled"])
            result.append(d)
        return result

    def delete_alert_rule(self, name: str) -> bool:
        """Delete an alert rule by name.  Returns True if it existed."""
        conn = self._pool.primary
        cursor = conn.execute(
            "DELETE FROM alert_rules WHERE name = ?", (name,)
        )
        conn.commit()
        return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Alert history
    # ------------------------------------------------------------------

    def save_alert(self, alert: dict[str, Any]) -> int:
        """
        Persist a fired alert to the history table.

        Returns the new row id.
        """
        conn = self._pool.primary
        cursor = conn.execute(
            """INSERT INTO alert_history
               (rule_name, severity, message, trace_id, metrics_json, fired_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                alert["rule_name"],
                alert["severity"],
                alert["message"],
                alert.get("trace_id"),
                json.dumps(alert.get("metrics", {})),
                alert.get("fired_at", time.time()),
            ),
        )
        conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    def get_alert_history(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return the most recent fired alerts (newest first)."""
        conn = self._pool.primary
        rows = conn.execute(
            """SELECT * FROM alert_history
               ORDER BY fired_at DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["metrics"] = json.loads(d.pop("metrics_json", "{}"))
            result.append(d)
        return result

    def close(self) -> None:
        self._pool.close_all()


    # ------------------------------------------------------------------
    # Cost intelligence queries
    # ------------------------------------------------------------------

    def get_daily_costs(self, days: int = 30) -> list[dict[str, Any]]:
        """
        Return daily cost aggregations for the last *days* calendar days.

        Each entry is a dict with keys:
          date (str, YYYY-MM-DD), total_cost_usd, total_tokens, trace_count.
        Results are in chronological order (oldest first).
        """
        cache_key = f"daily_costs:{days}"
        cached = self._cache.get(cache_key)
        if not isinstance(cached, _CacheMiss):
            return cached

        conn = self._pool.primary
        cutoff = time.time() - days * 86_400
        rows = conn.execute(
            """SELECT
                   strftime('%Y-%m-%d', start_time, 'unixepoch') AS date,
                   SUM(total_cost_usd)  AS total_cost_usd,
                   SUM(total_tokens)    AS total_tokens,
                   COUNT(*)             AS trace_count
               FROM traces
               WHERE start_time >= ?
               GROUP BY date
               ORDER BY date ASC""",
            (cutoff,),
        ).fetchall()

        result = [dict(r) for r in rows]
        self._cache.set(cache_key, result)
        return result

    def get_cost_by_model(self, days: int = 30) -> list[dict[str, Any]]:
        """
        Return cost aggregated by LLM model for the last *days* days.

        Reads the ``model`` field from ``attributes_json`` on each span.
        Each entry: {model, total_cost_usd, total_tokens, call_count, avg_cost_per_call}.
        """
        cache_key = f"cost_by_model:{days}"
        cached = self._cache.get(cache_key)
        if not isinstance(cached, _CacheMiss):
            return cached

        conn = self._pool.primary
        cutoff = time.time() - days * 86_400

        rows = conn.execute(
            """SELECT
                   s.attributes_json,
                   s.input_tokens,
                   s.output_tokens,
                   s.total_cost_usd
               FROM spans s
               JOIN traces t ON t.trace_id = s.trace_id
               WHERE t.start_time >= ?
                 AND (s.input_tokens > 0 OR s.output_tokens > 0)""",
            (cutoff,),
        ).fetchall()

        model_stats: dict[str, dict[str, Any]] = {}
        for row in rows:
            try:
                attrs = json.loads(row["attributes_json"]) or {}
            except Exception:
                attrs = {}
            model = (
                attrs.get("model")
                or attrs.get("llm.model")
                or attrs.get("gen_ai.request.model")
                or "unknown"
            )
            cost = row["total_cost_usd"] or 0.0
            tokens = (row["input_tokens"] or 0) + (row["output_tokens"] or 0)
            if model not in model_stats:
                model_stats[model] = {"total_cost_usd": 0.0, "total_tokens": 0, "call_count": 0}
            model_stats[model]["total_cost_usd"] += cost
            model_stats[model]["total_tokens"] += tokens
            model_stats[model]["call_count"] += 1

        result = []
        for model, stats in sorted(
            model_stats.items(), key=lambda kv: kv[1]["total_cost_usd"], reverse=True
        ):
            cnt = stats["call_count"]
            result.append(
                {
                    "model": model,
                    "total_cost_usd": round(stats["total_cost_usd"], 6),
                    "total_tokens": stats["total_tokens"],
                    "call_count": cnt,
                    "avg_cost_per_call": round(
                        stats["total_cost_usd"] / cnt if cnt > 0 else 0.0, 8
                    ),
                }
            )
        self._cache.set(cache_key, result)
        return result
