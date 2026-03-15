"""
Stats and patterns route handlers.

Endpoints:
- GET /v1/stats
- GET /v1/stats/trends
- GET /v1/stats/summary
- GET /v1/patterns/summary
- GET /v1/feedback/summary
- GET /v1/feedback/recent
- GET /v1/metrics/users
- GET /v1/metrics/experiments
- GET /v1/analysis/fleet
- GET /v1/analysis/regressions
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ...analysis.smart_advisor import SmartAdvisor as _SmartAdvisor
from ..storage import TraceStore
from ..utils import _MAX_ID_LENGTH, _parse_tags, _reconstruct_trace, _sanitize_id

logger = logging.getLogger(__name__)


class StatsResponse(BaseModel):
    total_traces: int = 0
    total_spans: int = 0
    total_tokens: int = 0
    total_cost: float = 0
    error_traces: int = 0
    avg_duration_ms: float = 0


def create_stats_router(store: TraceStore) -> APIRouter:
    """Create and return the stats router."""
    router = APIRouter()

    @router.get("/v1/stats")
    async def get_stats() -> StatsResponse:
        """Global aggregate statistics."""
        try:
            stats = store.get_stats()
        except Exception:
            logger.exception("Failed to get stats")
            raise HTTPException(500, "Failed to retrieve statistics")
        return StatsResponse(
            total_traces=stats.get("total_traces") or 0,
            total_spans=stats.get("total_spans") or 0,
            total_tokens=stats.get("total_tokens") or 0,
            total_cost=stats.get("total_cost") or 0,
            error_traces=stats.get("error_traces") or 0,
            avg_duration_ms=stats.get("avg_duration_ms") or 0,
        )

    @router.get("/v1/stats/trends")
    async def stats_trends(hours: int = 24, bucket_minutes: int = 60) -> JSONResponse:
        """Return trace count and error count bucketed by time.

        Returns data suitable for a line chart showing activity over time.
        """
        hours = min(hours, 168)  # Max 1 week
        bucket_minutes = max(5, min(bucket_minutes, 1440))

        now = time.time()
        start = now - (hours * 3600)
        bucket_size = bucket_minutes * 60

        # Query traces in time range
        try:
            traces = store.get_traces_by_time_range(start=start, end=now)
        except Exception:
            logger.exception("Failed to get traces for trends")
            raise HTTPException(500, "Failed to retrieve traces for trends")

        # Bucket them
        buckets: dict[float, dict[str, Any]] = {}
        for t in traces:
            bucket_key = int((t["start_time"] - start) / bucket_size)
            bucket_time = start + bucket_key * bucket_size
            if bucket_time not in buckets:
                buckets[bucket_time] = {"timestamp": bucket_time, "traces": 0, "errors": 0, "cost": 0.0}
            buckets[bucket_time]["traces"] += 1
            if t.get("has_errors"):
                buckets[bucket_time]["errors"] += 1
            buckets[bucket_time]["cost"] += t.get("total_cost_usd", 0)

        # Fill gaps with zeros
        result = []
        current = start
        while current < now:
            if current in buckets:
                result.append(buckets[current])
            else:
                result.append({"timestamp": current, "traces": 0, "errors": 0, "cost": 0.0})
            current += bucket_size

        return JSONResponse({"buckets": result, "hours": hours, "bucket_minutes": bucket_minutes})

    @router.get("/v1/stats/summary")
    async def stats_summary() -> JSONResponse:
        """Enhanced stats with per-agent breakdown."""
        try:
            basic = store.get_stats()
        except Exception:
            logger.exception("Failed to get basic stats for summary")
            raise HTTPException(500, "Failed to retrieve statistics")

        # Get agent breakdown
        try:
            traces = store.list_traces(limit=1000)
        except Exception:
            logger.exception("Failed to list traces for stats summary")
            raise HTTPException(500, "Failed to retrieve traces")

        agent_stats: dict[str, dict[str, Any]] = {}
        for t in traces:
            tags = _parse_tags(t.get("tags") or {})
            agent = tags.get("agent", "unknown")
            if agent not in agent_stats:
                agent_stats[agent] = {"traces": 0, "errors": 0, "cost": 0.0, "spans": 0}
            agent_stats[agent]["traces"] += 1
            if t.get("has_errors"):
                agent_stats[agent]["errors"] += 1
            agent_stats[agent]["cost"] += t.get("total_cost_usd", 0)
            agent_stats[agent]["spans"] += t.get("span_count", 0)

        return JSONResponse({
            **basic,
            "agent_breakdown": agent_stats,
        })

    @router.get("/v1/patterns/summary")
    async def patterns_summary(
        limit: int = Query(100, ge=1, le=1000),
    ) -> dict[str, Any]:
        """
        Aggregate pattern statistics: per-kind and per-name span counts,
        plus the top recurring error messages.
        """
        try:
            return store.get_pattern_summary(limit=limit)
        except Exception:
            logger.exception("Failed to get pattern summary")
            raise HTTPException(500, "Failed to retrieve pattern summary")

    @router.get("/v1/feedback/summary")
    async def feedback_summary() -> dict[str, Any]:
        """Aggregate feedback statistics: avg rating, distribution, low-rated traces."""
        try:
            return store.get_feedback_summary()
        except Exception:
            logger.exception("Failed to get feedback summary")
            raise HTTPException(500, "Failed to retrieve feedback summary")

    @router.get("/v1/feedback/recent")
    async def feedback_recent(
        limit: int = Query(10, ge=1, le=100, description="Max number of feedback entries to return"),
    ) -> list[dict[str, Any]]:
        """Return the most recent feedback entries across all traces, newest first."""
        try:
            return store.get_recent_feedback(limit=limit)
        except Exception:
            logger.exception("Failed to get recent feedback")
            raise HTTPException(500, "Failed to retrieve recent feedback")

    @router.get("/v1/metrics/users")
    async def user_metrics() -> list[dict[str, Any]]:
        """Per-user stats: trace count, error rate, avg cost."""
        try:
            return store.get_user_metrics()
        except Exception:
            logger.exception("Failed to get user metrics")
            raise HTTPException(500, "Failed to retrieve user metrics")

    @router.get("/v1/metrics/experiments")
    async def experiment_metrics() -> list[dict[str, Any]]:
        """Per-experiment comparison: trace count, error rate, avg cost, avg duration."""
        try:
            return store.get_experiment_metrics()
        except Exception:
            logger.exception("Failed to get experiment metrics")
            raise HTTPException(500, "Failed to retrieve experiment metrics")

    @router.get("/v1/analysis/fleet")
    async def fleet_analysis(
        limit: int = Query(500, ge=1, le=2000),
        service: str | None = Query(None, max_length=_MAX_ID_LENGTH),
    ) -> dict[str, Any]:
        """Fleet-wide analysis and recommendations."""
        if service is not None:
            _sanitize_id(service, "service")
        try:
            raw_traces = store.list_traces(limit=limit, service_name=service)
        except Exception:
            logger.exception("Failed to list traces for fleet analysis")
            raise HTTPException(500, "Failed to retrieve traces")
        try:
            traces = [_reconstruct_trace(t) for t in raw_traces]
            advisor = _SmartAdvisor()
            return advisor.analyze_fleet(traces)
        except Exception:
            logger.exception("Fleet analysis failed")
            raise HTTPException(500, "Fleet analysis failed")

    @router.get("/v1/analysis/regressions")
    async def regression_analysis(
        days: int = Query(7, ge=1, le=365, description="Days to treat as recent"),
        service: str | None = Query(None, max_length=_MAX_ID_LENGTH),
        limit: int = Query(500, ge=1, le=2000),
    ) -> dict[str, Any]:
        """Detect regressions by comparing recent traces against baseline."""
        if service is not None:
            _sanitize_id(service, "service")
        cutoff = time.time() - days * 86_400
        try:
            all_raw = store.list_traces(limit=limit, service_name=service)
        except Exception:
            logger.exception("Failed to list traces for regression analysis")
            raise HTTPException(500, "Failed to retrieve traces")
        try:
            all_traces = [_reconstruct_trace(t) for t in all_raw]
            recent_traces = [t for t in all_traces if t.start_time >= cutoff]
            baseline_traces = [t for t in all_traces if t.start_time < cutoff]
            if not recent_traces:
                return {
                    "regressions": [],
                    "summary": f"No traces found in the last {days} day(s).",
                    "recent_count": 0,
                    "baseline_count": len(baseline_traces),
                }
            if not baseline_traces:
                return {
                    "regressions": [],
                    "summary": "No baseline traces available for comparison.",
                    "recent_count": len(recent_traces),
                    "baseline_count": 0,
                }
            advisor = _SmartAdvisor()
            reports = advisor.detect_regression(
                recent_traces, baseline_traces, service_name=service or "all services"
            )
            return {
                "regressions": [r.to_dict() for r in reports],
                "summary": (
                    f"Detected {len(reports)} regression(s) comparing last {days} day(s) "
                    f"({len(recent_traces)} traces) against baseline "
                    f"({len(baseline_traces)} traces)."
                ),
                "recent_count": len(recent_traces),
                "baseline_count": len(baseline_traces),
            }
        except Exception:
            logger.exception("Regression analysis failed")
            raise HTTPException(500, "Regression analysis failed")

    return router
