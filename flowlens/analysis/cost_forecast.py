"""
Cost Forecasting — project future costs from historical trace data.

CostForecaster uses simple linear regression on daily costs to project
forward without any ML library dependencies.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class CostForecast:
    """
    Result of a cost projection analysis.

    Attributes
    ----------
    projected_daily_cost:
        Estimated USD cost per day going forward.
    projected_monthly_cost:
        projected_daily_cost × 30.
    trend:
        'increasing', 'decreasing', or 'stable'.
    confidence_interval:
        (lower, upper) 95 % CI on the projected_daily_cost.
    days_of_data:
        How many distinct days of data were used.
    slope:
        Daily cost change per day (positive → increasing).
    r_squared:
        Coefficient of determination; 1.0 = perfect linear fit.
    """

    projected_daily_cost: float
    projected_monthly_cost: float
    trend: str
    confidence_interval: tuple[float, float]
    days_of_data: int = 0
    slope: float = 0.0
    r_squared: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "projected_daily_cost": round(self.projected_daily_cost, 6),
            "projected_monthly_cost": round(self.projected_monthly_cost, 6),
            "trend": self.trend,
            "confidence_interval": {
                "lower": round(self.confidence_interval[0], 6),
                "upper": round(self.confidence_interval[1], 6),
            },
            "days_of_data": self.days_of_data,
            "slope": round(self.slope, 8),
            "r_squared": round(self.r_squared, 4),
        }


# ---------------------------------------------------------------------------
# Helper — pure-Python linear regression
# ---------------------------------------------------------------------------


def _linear_regression(x: list[float], y: list[float]) -> tuple[float, float, float]:
    """
    Fit y = slope * x + intercept using OLS.

    Returns (slope, intercept, r_squared).
    """
    n = len(x)
    if n < 2:
        return 0.0, y[0] if y else 0.0, 0.0

    sum_x = sum(x)
    sum_y = sum(y)
    sum_xx = sum(xi * xi for xi in x)
    sum_xy = sum(xi * yi for xi, yi in zip(x, y, strict=False))

    denom = n * sum_xx - sum_x * sum_x
    if denom == 0:
        return 0.0, sum_y / n, 0.0

    slope = (n * sum_xy - sum_x * sum_y) / denom
    intercept = (sum_y - slope * sum_x) / n

    # R²
    y_mean = sum_y / n
    ss_tot = sum((yi - y_mean) ** 2 for yi in y)
    ss_res = sum((yi - (slope * xi + intercept)) ** 2 for xi, yi in zip(x, y, strict=False))
    r_squared = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

    return slope, intercept, r_squared


def _residual_std(x: list[float], y: list[float], slope: float, intercept: float) -> float:
    """Standard error of regression residuals."""
    n = len(x)
    if n < 3:
        return 0.0
    residuals = [yi - (slope * xi + intercept) for xi, yi in zip(x, y, strict=False)]
    sse = sum(r * r for r in residuals)
    return math.sqrt(sse / (n - 2))


# ---------------------------------------------------------------------------
# CostForecaster
# ---------------------------------------------------------------------------


class CostForecaster:
    """
    Project future costs from a list of daily cost records.

    The records can come either from pre-aggregated storage results
    (list of dicts with 'date', 'total_cost_usd') or from raw trace dicts
    with a 'start_time' (Unix timestamp) and 'total_cost_usd'.
    """

    # Trend thresholds: slope relative to mean daily cost
    _STABLE_THRESHOLD = 0.02  # < 2 % per day change → stable

    # ---------------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------------

    def forecast(
        self,
        traces: list[dict[str, Any]],
        days: int = 30,
    ) -> CostForecast:
        """
        Project costs forward by *days* days.

        Parameters
        ----------
        traces:
            Either raw trace dicts (with ``start_time`` + ``total_cost_usd``)
            or pre-aggregated daily records (with ``date`` + ``total_cost_usd``).
        days:
            Horizon for the projection (not currently used in the output beyond
            determining projected_monthly_cost via the daily rate).

        Returns
        -------
        CostForecast
        """
        daily = self._aggregate_daily(traces)

        if not daily:
            return CostForecast(
                projected_daily_cost=0.0,
                projected_monthly_cost=0.0,
                trend="stable",
                confidence_interval=(0.0, 0.0),
                days_of_data=0,
                slope=0.0,
                r_squared=0.0,
            )

        dates = sorted(daily.keys())
        # Convert dates to integer indices (0, 1, 2, …) for regression
        base = dates[0]
        x = [(d - base) for d in dates]
        y = [daily[d] for d in dates]

        slope, intercept, r_squared = _linear_regression(x, y)

        # Project to "now + 1 day" as the representative daily cost
        last_x = x[-1] + 1
        projected_daily = max(0.0, slope * last_x + intercept)
        projected_monthly = projected_daily * 30

        # Confidence interval (±1.96 × SE of residuals)
        se = _residual_std(x, y, slope, intercept)
        margin = 1.96 * se
        ci = (max(0.0, projected_daily - margin), projected_daily + margin)

        # Trend classification
        mean_daily = sum(y) / len(y) if y else 1.0
        relative_slope = slope / mean_daily if mean_daily > 0 else slope
        if abs(relative_slope) < self._STABLE_THRESHOLD:
            trend = "stable"
        elif relative_slope > 0:
            trend = "increasing"
        else:
            trend = "decreasing"

        return CostForecast(
            projected_daily_cost=round(projected_daily, 6),
            projected_monthly_cost=round(projected_monthly, 6),
            trend=trend,
            confidence_interval=(round(ci[0], 6), round(ci[1], 6)),
            days_of_data=len(dates),
            slope=round(slope, 8),
            r_squared=round(r_squared, 4),
        )

    def days_until_budget(
        self,
        traces: list[dict[str, Any]],
        budget_usd: float,
    ) -> float | None:
        """
        Estimate how many days until the cumulative cost reaches *budget_usd*.

        Returns None if the trend is not increasing or there is insufficient data.
        Returns a positive float (possibly fractional) when a crossing is expected.
        """
        if budget_usd <= 0:
            return 0.0

        daily = self._aggregate_daily(traces)
        if not daily:
            return None

        dates = sorted(daily.keys())
        cumulative = sum(daily[d] for d in dates)

        if cumulative >= budget_usd:
            return 0.0

        forecast = self.forecast(traces)
        if forecast.projected_daily_cost <= 0:
            return None

        remaining = budget_usd - cumulative
        return remaining / forecast.projected_daily_cost

    def detect_cost_anomaly_window(
        self,
        traces: list[dict[str, Any]],
        window_hours: int = 24,
    ) -> list[dict[str, Any]]:
        """
        Detect time windows where cost deviated significantly from the norm.

        A window is flagged as anomalous when its cost exceeds
        mean + 2 × std across all windows of the same size.

        Parameters
        ----------
        traces:
            Raw trace dicts with ``start_time`` (Unix timestamp) and
            ``total_cost_usd``.
        window_hours:
            Size of each bucket in hours.

        Returns
        -------
        list of dicts: {window_start, window_end, total_cost, z_score}
        """
        if not traces:
            return []

        window_seconds = window_hours * 3600
        # Bucket traces into time windows
        buckets: dict[int, float] = {}
        for t in traces:
            ts = t.get("start_time", 0)
            cost = t.get("total_cost_usd", 0.0) or 0.0
            bucket = int(ts // window_seconds)
            buckets[bucket] = buckets.get(bucket, 0.0) + cost

        if len(buckets) < 2:
            return []

        costs = list(buckets.values())
        mean_cost = sum(costs) / len(costs)
        variance = sum((c - mean_cost) ** 2 for c in costs) / len(costs)
        std_cost = math.sqrt(variance) if variance > 0 else 0.0

        anomalies: list[dict[str, Any]] = []
        for bucket_idx, total_cost in sorted(buckets.items()):
            z_score = (total_cost - mean_cost) / std_cost if std_cost > 0 else 0.0
            if abs(z_score) >= 2.0:
                window_start = bucket_idx * window_seconds
                anomalies.append(
                    {
                        "window_start": window_start,
                        "window_end": window_start + window_seconds,
                        "total_cost": round(total_cost, 6),
                        "z_score": round(z_score, 3),
                    }
                )

        return anomalies

    # ---------------------------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------------------------

    @staticmethod
    def _aggregate_daily(
        traces: list[dict[str, Any]],
    ) -> dict[int, float]:
        """
        Convert a list of trace / daily-record dicts into a mapping of
        day_index (days since epoch) → total_cost_usd.

        Accepts both:
        - Raw traces: {start_time: float (unix), total_cost_usd: float}
        - Pre-aggregated: {date: "YYYY-MM-DD", total_cost_usd: float}
        """
        daily: dict[int, float] = {}
        for record in traces:
            cost = record.get("total_cost_usd", 0.0) or 0.0

            if "date" in record:
                # Pre-aggregated record — parse YYYY-MM-DD
                try:
                    dt = datetime.strptime(record["date"], "%Y-%m-%d")
                    day_idx = int(dt.timestamp()) // 86400
                except (ValueError, TypeError):
                    continue
            elif "start_time" in record:
                ts = record.get("start_time", 0) or 0
                day_idx = int(ts) // 86400
            else:
                continue

            daily[day_idx] = daily.get(day_idx, 0.0) + cost

        return daily
