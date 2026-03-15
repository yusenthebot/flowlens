"""
Cost analysis route handlers.

Endpoints:
- GET /v1/cost/breakdown
- GET /v1/cost/trends
- GET /v1/cost/forecast
- GET /v1/cost/budget
- GET /v1/cost/optimization
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ..storage import TraceStore

logger = logging.getLogger(__name__)


def create_cost_router(store: TraceStore) -> APIRouter:
    """Create and return the cost router."""
    router = APIRouter()

    @router.get("/v1/cost/breakdown")
    async def cost_breakdown(
        group_by: str = Query("service_name", pattern="^(service_name|kind|name)$"),
    ) -> list[dict[str, Any]]:
        """Cost attribution grouped by service, span kind, or span name."""
        try:
            return store.get_cost_breakdown(group_by=group_by)
        except Exception:
            logger.exception("Failed to get cost breakdown")
            raise HTTPException(500, "Failed to retrieve cost breakdown")

    @router.get("/v1/cost/trends")
    async def cost_trends(
        granularity: str = Query("daily", pattern="^(daily|hourly)$"),
        limit: int = Query(30, ge=1, le=365),
    ) -> list[dict[str, Any]]:
        """
        Aggregate cost over time.

        ``granularity`` is either ``daily`` (default) or ``hourly``.
        ``limit`` controls how many time buckets are returned (most recent first
        in the raw query; the response is sorted oldest-to-newest).
        """
        try:
            return store.get_cost_trends(granularity=granularity, limit=limit)
        except Exception:
            logger.exception("Failed to get cost trends")
            raise HTTPException(500, "Failed to retrieve cost trends")

    @router.get("/v1/cost/forecast")
    async def cost_forecast(
        days: int = Query(30, ge=1, le=365, description="Forecast horizon in days"),
        forecast_days: int = Query(7, ge=1, le=30, description="Number of days to forecast forward"),
    ) -> dict[str, Any]:
        """
        Project future costs using linear regression on daily cost data.

        Returns projected_daily_cost, projected_monthly_cost, trend,
        confidence_interval, days_of_data, slope, r_squared,
        daily_costs (last N days actual), and forecast (next forecast_days).
        """
        from ...analysis.cost_forecast import CostForecaster
        from datetime import datetime, timezone, timedelta
        try:
            history_days = max(days, 14)
            daily_records = store.get_daily_costs(days=history_days)
            forecaster = CostForecaster()
            fc = forecaster.forecast(daily_records, days=days)
            result = fc.to_dict()

            # Build daily_costs list (last 7 days of actual data)
            result["daily_costs"] = [
                {"date": r["date"], "cost": round(r.get("total_cost_usd", 0.0) or 0.0, 6)}
                for r in daily_records[-7:]
            ]

            # Build forecast list (next forecast_days days using linear projection)
            forecast_list = []
            slope = fc.slope
            # Use last known day as baseline
            if daily_records:
                last_date_str = daily_records[-1]["date"]
                try:
                    last_date = datetime.strptime(last_date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                except (ValueError, TypeError):
                    last_date = datetime.now(timezone.utc)
            else:
                last_date = datetime.now(timezone.utc)

            base_cost = fc.projected_daily_cost
            ci_lower_base = fc.confidence_interval[0]
            ci_upper_base = fc.confidence_interval[1]
            half_range = (ci_upper_base - ci_lower_base) / 2.0

            for i in range(1, forecast_days + 1):
                future_date = last_date + timedelta(days=i)
                projected = max(0.0, base_cost + slope * i)
                ci_lo = max(0.0, projected - half_range)
                ci_hi = projected + half_range
                forecast_list.append({
                    "date": future_date.strftime("%Y-%m-%d"),
                    "cost": round(projected, 6),
                    "ci_lower": round(ci_lo, 6),
                    "ci_upper": round(ci_hi, 6),
                })
            result["forecast"] = forecast_list
            result["daily_avg_usd"] = round(fc.projected_daily_cost, 6)
            result["monthly_projection_usd"] = round(fc.projected_monthly_cost, 6)
            return result
        except Exception:
            logger.exception("Failed to compute cost forecast")
            raise HTTPException(500, "Failed to compute cost forecast")

    @router.get("/v1/cost/budget")
    async def cost_budget(
        budget: float = Query(..., gt=0, description="Budget cap in USD"),
    ) -> dict[str, Any]:
        """
        Return budget status: how much has been spent, what remains,
        the current daily burn rate, and estimated days until the budget is exhausted.
        """
        from ...analysis.cost_forecast import CostForecaster
        try:
            daily_records = store.get_daily_costs(days=30)
            total_spent = sum(r.get("total_cost_usd", 0.0) or 0.0 for r in daily_records)
            remaining = max(0.0, budget - total_spent)

            forecaster = CostForecaster()
            forecast = forecaster.forecast(daily_records)
            burn_rate = forecast.projected_daily_cost

            days_left = forecaster.days_until_budget(daily_records, budget_usd=budget)

            return {
                "budget_usd": budget,
                "total_spent_usd": round(total_spent, 6),
                "remaining_usd": round(remaining, 6),
                "burn_rate_daily_usd": round(burn_rate, 6),
                "days_until_exhausted": round(days_left, 1) if days_left is not None else None,
                "trend": forecast.trend,
            }
        except Exception:
            logger.exception("Failed to compute budget status")
            raise HTTPException(500, "Failed to compute budget status")

    @router.get("/v1/cost/optimization")
    async def cost_optimization() -> dict[str, Any]:
        """Return actionable optimisation suggestions with estimated monthly savings."""
        from ...analysis.cost_breakdown import CostBreakdown
        try:
            # Fetch recent traces for analysis (lightweight — no spans loaded)
            traces = store.list_traces(limit=200)
            # We need span data for model/context analysis; fetch full traces
            # but cap at 50 to keep response times reasonable
            full_traces = []
            for t in traces[:50]:
                full = store.get_trace(t["trace_id"])
                if full:
                    full_traces.append(full)

            breakdown = CostBreakdown()
            suggestions = breakdown.optimization_suggestions(full_traces)
            by_model = breakdown.by_model(full_traces)
            by_service = breakdown.by_service(full_traces)
            by_kind = breakdown.by_span_kind(full_traces)

            total_savings = sum(
                s.get("estimated_monthly_savings_usd", 0.0) for s in suggestions
            )
            return {
                "suggestions": suggestions,
                "total_estimated_monthly_savings_usd": round(total_savings, 4),
                "by_model": by_model,
                "by_service": by_service,
                "by_span_kind": by_kind,
            }
        except Exception:
            logger.exception("Failed to compute optimisation suggestions")
            raise HTTPException(500, "Failed to compute optimisation suggestions")

    return router
