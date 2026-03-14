"""
Storage Layer — trace 数据的持久化存储

MVP 使用 SQLite + JSONL，生产环境可切换到 ClickHouse + PostgreSQL。
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class TraceStore:
    """
    SQLite 存储 — MVP 零外部依赖

    表结构：
    - traces: trace 级别元数据（id, service, duration, cost, errors）
    - spans: span 级别数据（trace 外键, 完整 JSON）
    """

    def __init__(self, db_path: str | Path = "./flowlens.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_tables()

    def _init_tables(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS traces (
                trace_id TEXT PRIMARY KEY,
                service_name TEXT NOT NULL DEFAULT '',
                start_time REAL NOT NULL,
                end_time REAL NOT NULL DEFAULT 0,
                duration_ms REAL NOT NULL DEFAULT 0,
                span_count INTEGER NOT NULL DEFAULT 0,
                total_tokens INTEGER NOT NULL DEFAULT 0,
                total_cost_usd REAL NOT NULL DEFAULT 0,
                has_errors INTEGER NOT NULL DEFAULT 0,
                error_count INTEGER NOT NULL DEFAULT 0,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS spans (
                span_id TEXT PRIMARY KEY,
                trace_id TEXT NOT NULL,
                parent_span_id TEXT,
                name TEXT NOT NULL,
                kind TEXT NOT NULL,
                status TEXT NOT NULL,
                start_time REAL NOT NULL,
                end_time REAL NOT NULL DEFAULT 0,
                duration_ms REAL NOT NULL DEFAULT 0,
                input_tokens INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER NOT NULL DEFAULT 0,
                total_cost_usd REAL NOT NULL DEFAULT 0,
                error_message TEXT,
                attributes_json TEXT NOT NULL DEFAULT '{}',
                events_json TEXT NOT NULL DEFAULT '[]',
                FOREIGN KEY (trace_id) REFERENCES traces(trace_id)
            );

            CREATE INDEX IF NOT EXISTS idx_spans_trace ON spans(trace_id);
            CREATE INDEX IF NOT EXISTS idx_traces_time ON traces(start_time);
            CREATE INDEX IF NOT EXISTS idx_traces_service ON traces(service_name);
        """)
        self._conn.commit()

    def save_trace(self, trace_data: dict[str, Any]) -> None:
        """保存一条完整的 trace（含所有 spans）"""
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

            # 保存 spans
            for span in trace_data.get("spans", []):
                token_usage = span.get("token_usage", {})
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
                        span.get("error", {}).get("message") if isinstance(span.get("error"), dict) else None,
                        json.dumps(span.get("attributes", {})),
                        json.dumps(span.get("events", [])),
                    ),
                )

            self._conn.commit()
            logger.debug(f"Saved trace {trace_data['trace_id'][:12]}")

        except Exception as e:
            logger.error(f"Failed to save trace: {e}")
            self._conn.rollback()
            raise

    def get_trace(self, trace_id: str) -> Optional[dict[str, Any]]:
        """获取单个 trace（含所有 spans）"""
        row = self._conn.execute(
            "SELECT * FROM traces WHERE trace_id = ?", (trace_id,)
        ).fetchone()
        if not row:
            return None

        trace = dict(row)
        trace["metadata"] = json.loads(trace.pop("metadata_json"))

        # 获取 spans
        span_rows = self._conn.execute(
            "SELECT * FROM spans WHERE trace_id = ? ORDER BY start_time",
            (trace_id,),
        ).fetchall()

        spans = []
        for sr in span_rows:
            span = dict(sr)
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
            spans.append(span)

        trace["spans"] = spans
        return trace

    def list_traces(
        self,
        limit: int = 50,
        offset: int = 0,
        service_name: Optional[str] = None,
        has_errors: Optional[bool] = None,
    ) -> list[dict[str, Any]]:
        """列出 traces（不含 spans 详情）"""
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
        results = []
        for row in rows:
            trace = dict(row)
            trace["metadata"] = json.loads(trace.pop("metadata_json"))
            results.append(trace)

        return results

    def get_cost_breakdown(
        self,
        group_by: str = "service_name",
    ) -> list[dict[str, Any]]:
        """成本归因 — 按维度分组"""
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

    def get_stats(self) -> dict[str, Any]:
        """全局统计"""
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
