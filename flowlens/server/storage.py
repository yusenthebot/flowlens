"""
Storage Layer — trace data persistence

MVP uses SQLite + JSONL; production can switch to ClickHouse + PostgreSQL.

Schema versioning:
- Version 1: initial schema (traces + spans tables)
- Version 2: added indexes for has_errors, created_at; error_message index on spans
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Bump this whenever _migrate() gains a new migration step.
SCHEMA_VERSION = 2


class TraceStore:
    """
    SQLite storage — zero external dependencies for MVP.

    Tables:
    - schema_version: single-row version tracking for migrations
    - traces: trace-level metadata (id, service, duration, cost, errors)
    - spans: span-level data (trace FK, full JSON)
    """

    def __init__(self, db_path: str | Path = "./flowlens.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")  # better write concurrency
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_tables()
        self._migrate()

    # ------------------------------------------------------------------
    # Schema bootstrap & migrations
    # ------------------------------------------------------------------

    def _init_tables(self) -> None:
        """Create tables and base indexes if they don't yet exist."""
        self._conn.executescript("""
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
        self._conn.commit()

    def _get_version(self) -> int:
        row = self._conn.execute("SELECT version FROM schema_version").fetchone()
        return row["version"] if row else 0

    def _set_version(self, version: int) -> None:
        self._conn.execute("DELETE FROM schema_version")
        self._conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))

    def _migrate(self) -> None:
        """Run any pending schema migrations in order."""
        current = self._get_version()

        if current < 1:
            # v1 → nothing extra; tables were created in _init_tables
            logger.info("DB schema: initialised at version 1")
            self._set_version(1)
            self._conn.commit()
            current = 1

        if current < 2:
            # v2 → performance indexes for common query patterns
            logger.info("DB schema: migrating to version 2 (additional indexes)")
            self._conn.executescript("""
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
            self._conn.commit()
            current = 2

        logger.debug("DB schema is at version %d", current)

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def save_trace(self, trace_data: dict[str, Any]) -> None:
        """Save a complete trace (including all spans)."""
        try:
            self._conn.execute(
                """INSERT OR REPLACE INTO traces
                   (trace_id, service_name, start_time, end_time, duration_ms,
                    span_count, total_tokens, total_cost_usd, has_errors,
                    error_count, metadata_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                ),
            )

            for span in trace_data.get("spans", []):
                token_usage = span.get("token_usage") or {}
                self._conn.execute(
                    """INSERT OR REPLACE INTO spans
                       (span_id, trace_id, parent_span_id, name, kind, status,
                        start_time, end_time, duration_ms,
                        input_tokens, output_tokens, total_cost_usd,
                        error_message, attributes_json, events_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
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
                        span.get("error", {}).get("message")
                        if isinstance(span.get("error"), dict)
                        else None,
                        json.dumps(span.get("attributes", {})),
                        json.dumps(span.get("events", [])),
                    ),
                )

            self._conn.commit()
            logger.debug("Saved trace %s", trace_data["trace_id"][:12])

        except Exception as e:
            logger.error("Failed to save trace: %s", e)
            self._conn.rollback()
            raise

    def delete_trace(self, trace_id: str) -> bool:
        """
        Delete a trace and all its spans.

        Returns True if a trace was deleted, False if the trace_id was not found.
        Because we use ON DELETE CASCADE on the spans FK, deleting the trace
        row automatically removes all child spans.
        """
        cursor = self._conn.execute(
            "DELETE FROM traces WHERE trace_id = ?", (trace_id,)
        )
        self._conn.commit()
        deleted = cursor.rowcount > 0
        if deleted:
            logger.debug("Deleted trace %s", trace_id[:12])
        return deleted

    def cleanup_old_traces(self, days: int = 30) -> int:
        """
        Delete all traces whose created_at timestamp is older than *days* days.

        Returns the number of traces deleted.
        """
        cutoff = time.time() - days * 86_400
        cursor = self._conn.execute(
            "DELETE FROM traces WHERE created_at < ?", (cutoff,)
        )
        self._conn.commit()
        count = cursor.rowcount
        logger.info("Cleaned up %d traces older than %d days", count, days)
        return count

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    @staticmethod
    def _deserialise_trace(row: sqlite3.Row) -> dict[str, Any]:
        """Convert a raw traces row into the standard dict shape."""
        trace = dict(row)
        trace["metadata"] = json.loads(trace.pop("metadata_json"))
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
        row = self._conn.execute(
            "SELECT * FROM traces WHERE trace_id = ?", (trace_id,)
        ).fetchone()
        if not row:
            return None

        trace = self._deserialise_trace(row)

        span_rows = self._conn.execute(
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
    ) -> list[dict[str, Any]]:
        """List traces (without span detail)."""
        query = "SELECT * FROM traces WHERE 1=1"
        params: list[Any] = []

        if service_name:
            query += " AND service_name = ?"
            params.append(service_name)
        if has_errors is not None:
            query += " AND has_errors = ?"
            params.append(1 if has_errors else 0)

        query += " ORDER BY start_time DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = self._conn.execute(query, params).fetchall()
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
        rows = self._conn.execute(
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
        rows = self._conn.execute(
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
        """
        like = f"%{query}%"
        rows = self._conn.execute(
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
    # Aggregations
    # ------------------------------------------------------------------

    def get_cost_breakdown(
        self,
        group_by: str = "service_name",
    ) -> list[dict[str, Any]]:
        """Cost attribution grouped by the requested dimension."""
        if group_by == "service_name":
            rows = self._conn.execute(
                """SELECT service_name as dimension,
                   COUNT(*) as trace_count,
                   SUM(total_tokens) as total_tokens,
                   SUM(total_cost_usd) as total_cost_usd
                   FROM traces GROUP BY service_name
                   ORDER BY total_cost_usd DESC"""
            ).fetchall()
        elif group_by == "kind":
            rows = self._conn.execute(
                """SELECT kind as dimension,
                   COUNT(*) as span_count,
                   SUM(input_tokens + output_tokens) as total_tokens,
                   SUM(total_cost_usd) as total_cost_usd
                   FROM spans WHERE input_tokens > 0
                   GROUP BY kind ORDER BY total_cost_usd DESC"""
            ).fetchall()
        elif group_by == "name":
            rows = self._conn.execute(
                """SELECT name as dimension,
                   COUNT(*) as call_count,
                   SUM(input_tokens + output_tokens) as total_tokens,
                   SUM(total_cost_usd) as total_cost_usd
                   FROM spans WHERE input_tokens > 0
                   GROUP BY name ORDER BY total_cost_usd DESC"""
            ).fetchall()
        else:
            return []

        return [dict(r) for r in rows]

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
        if granularity == "hourly":
            # SQLite: strftime with %Y-%m-%dT%H gives hour bucket
            time_expr = "strftime('%Y-%m-%dT%H:00:00', start_time, 'unixepoch')"
        else:
            time_expr = "strftime('%Y-%m-%d', start_time, 'unixepoch')"

        rows = self._conn.execute(
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
        return list(reversed([dict(r) for r in rows]))

    def get_pattern_summary(
        self,
        limit: int = 100,
    ) -> dict[str, Any]:
        """
        Aggregate pattern statistics across recent traces.

        Returns per-span-kind and per-span-name counts, plus top error messages.
        """
        kind_rows = self._conn.execute(
            """SELECT kind,
                   COUNT(*)             AS span_count,
                   SUM(input_tokens + output_tokens) AS total_tokens,
                   SUM(total_cost_usd)  AS total_cost_usd,
                   AVG(duration_ms)     AS avg_duration_ms
               FROM spans
               GROUP BY kind
               ORDER BY span_count DESC"""
        ).fetchall()

        name_rows = self._conn.execute(
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

        error_rows = self._conn.execute(
            """SELECT error_message, COUNT(*) AS occurrences
               FROM spans
               WHERE error_message IS NOT NULL
               GROUP BY error_message
               ORDER BY occurrences DESC
               LIMIT 20"""
        ).fetchall()

        return {
            "by_kind": [dict(r) for r in kind_rows],
            "by_name": [dict(r) for r in name_rows],
            "top_errors": [dict(r) for r in error_rows],
        }

    def get_stats(self) -> dict[str, Any]:
        """Global aggregate statistics."""
        row = self._conn.execute(
            """SELECT
               COUNT(*) as total_traces,
               SUM(span_count) as total_spans,
               SUM(total_tokens) as total_tokens,
               SUM(total_cost_usd) as total_cost,
               SUM(has_errors) as error_traces,
               AVG(duration_ms) as avg_duration_ms
               FROM traces"""
        ).fetchone()
        return dict(row) if row else {}

    def close(self) -> None:
        self._conn.close()
