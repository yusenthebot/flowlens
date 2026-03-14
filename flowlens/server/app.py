"""
FlowLens API Server — FastAPI 应用

端点：
- POST /v1/traces/ingest     — 接收 trace 数据
- GET  /v1/traces             — 列出 traces
- GET  /v1/traces/{id}        — 获取 trace 详情
- GET  /v1/traces/{id}/dag    — 获取因果 DAG
- GET  /v1/cost/breakdown     — 成本归因
- GET  /v1/stats              — 全局统计
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .storage import TraceStore
from ..sdk.models import Span, SpanKind, SpanStatus, Trace, TokenUsage
from ..analysis.dag_builder import build_causal_dag
from ..analysis.patterns import detect_patterns

logger = logging.getLogger(__name__)


# ===== Pydantic Models =====

class TraceIngestRequest(BaseModel):
    """Trace 导入请求"""
    trace_id: str
    service_name: str = ""
    start_time: float = 0
    end_time: float = 0
    duration_ms: float = 0
    total_tokens: int = 0
    total_cost_usd: float = 0
    has_errors: bool = False
    error_count: int = 0
    span_count: int = 0
    metadata: dict[str, Any] = {}
    spans: list[dict[str, Any]] = []


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


# ===== App Factory =====

def create_app(db_path: str = "./flowlens.db") -> FastAPI:
    """创建 FastAPI 应用实例"""

    app = FastAPI(
        title="FlowLens",
        description="Agent Observability Platform — Chrome DevTools for LLM Agents",
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    store = TraceStore(db_path=db_path)

    # ===== Ingest =====

    @app.post("/v1/traces/ingest", status_code=201)
    async def ingest_trace(req: TraceIngestRequest) -> dict[str, str]:
        """接收并存储 trace 数据"""
        store.save_trace(req.model_dump())
        return {"status": "ok", "trace_id": req.trace_id}

    @app.post("/v1/traces/import", status_code=201)
    async def import_jsonl(file_path: str) -> dict[str, Any]:
        """从 JSONL 文件批量导入"""
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
                    logger.warning(f"Failed to import trace: {e}")

        return {"imported": count, "errors": errors}

    # ===== Query =====

    @app.get("/v1/traces")
    async def list_traces(
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        service: Optional[str] = None,
        errors_only: bool = False,
    ) -> TraceListResponse:
        """列出 traces"""
        traces = store.list_traces(
            limit=limit,
            offset=offset,
            service_name=service,
            has_errors=True if errors_only else None,
        )
        return TraceListResponse(
            traces=traces,
            total=len(traces),
            limit=limit,
            offset=offset,
        )

    @app.get("/v1/traces/{trace_id}")
    async def get_trace(trace_id: str) -> dict[str, Any]:
        """获取 trace 详情（含所有 spans）"""
        trace = store.get_trace(trace_id)
        if not trace:
            raise HTTPException(404, f"Trace not found: {trace_id}")
        return trace

    # ===== Analysis =====

    @app.get("/v1/traces/{trace_id}/dag")
    async def get_trace_dag(trace_id: str) -> dict[str, Any]:
        """获取 trace 的因果 DAG"""
        trace_data = store.get_trace(trace_id)
        if not trace_data:
            raise HTTPException(404, f"Trace not found: {trace_id}")

        # 重建 Trace 对象用于分析
        trace = _reconstruct_trace(trace_data)
        dag = build_causal_dag(trace)
        detect_patterns(trace, dag)
        return dag.to_dict()

    # ===== Cost =====

    @app.get("/v1/cost/breakdown")
    async def cost_breakdown(
        group_by: str = Query("service_name", pattern="^(service_name|kind|name)$"),
    ) -> list[dict[str, Any]]:
        """成本归因"""
        return store.get_cost_breakdown(group_by=group_by)

    # ===== Stats =====

    @app.get("/v1/stats")
    async def get_stats() -> StatsResponse:
        """全局统计"""
        stats = store.get_stats()
        return StatsResponse(
            total_traces=stats.get("total_traces") or 0,
            total_spans=stats.get("total_spans") or 0,
            total_tokens=stats.get("total_tokens") or 0,
            total_cost=stats.get("total_cost") or 0,
            error_traces=stats.get("error_traces") or 0,
            avg_duration_ms=stats.get("avg_duration_ms") or 0,
        )

    # ===== Health =====

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": "0.1.0"}

    @app.on_event("shutdown")
    def shutdown() -> None:
        store.close()

    return app


def _reconstruct_trace(trace_data: dict[str, Any]) -> Trace:
    """从存储的 dict 重建 Trace 对象（用于分析）"""
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

        # Token usage
        tu = sd.get("token_usage")
        if tu:
            span.token_usage = TokenUsage(
                input_tokens=tu.get("input_tokens", 0),
                output_tokens=tu.get("output_tokens", 0),
                total_tokens=tu.get("input_tokens", 0) + tu.get("output_tokens", 0),
                total_cost_usd=tu.get("total_cost_usd", 0),
            )

        # Error
        err = sd.get("error")
        if isinstance(err, dict):
            span.error_message = err.get("message")
            span.error_type = err.get("type")

        trace.spans.append(span)

    return trace
