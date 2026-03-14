"""
Multi-Trace Correlator — find systemic patterns across a collection of traces.

This module analyses a batch of Trace objects and surfaces findings that would
not be visible from a single trace in isolation:

1. Recurring failures  — same error message appears in > 50 % of traces.
2. Performance trends  — latency is growing monotonically across traces.
3. Common anti-patterns — a PatternType occurs in the majority of traces.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from ..sdk.models import SpanStatus, Trace
from .dag_builder import build_causal_dag
from .models import DetectedPattern, PatternType
from .patterns import detect_patterns

# ---------------------------------------------------------------------------
# Result models
# ---------------------------------------------------------------------------


@dataclass
class RecurringFailure:
    """A specific error message that appears in many traces."""

    error_message: str
    occurrence_count: int
    total_traces: int
    affected_trace_ids: list[str]
    affected_span_names: list[str]

    @property
    def occurrence_rate(self) -> float:
        """Fraction of traces that contain this failure (0.0 – 1.0)."""
        if self.total_traces == 0:
            return 0.0
        return self.occurrence_count / self.total_traces

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_message": self.error_message,
            "occurrence_count": self.occurrence_count,
            "total_traces": self.total_traces,
            "occurrence_rate": round(self.occurrence_rate, 3),
            "affected_trace_ids": self.affected_trace_ids,
            "affected_span_names": self.affected_span_names,
        }


@dataclass
class PerformanceTrend:
    """Latency or cost metric that is trending upward across traces."""

    metric: str                # "duration_ms" | "total_tokens" | "total_cost_usd"
    direction: str             # "increasing" | "decreasing"
    values: list[float]        # one value per trace (in the same order as input)
    trace_ids: list[str]
    slope: float               # average delta per trace step

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "direction": self.direction,
            "values": [round(v, 4) for v in self.values],
            "trace_ids": self.trace_ids,
            "slope": round(self.slope, 4),
        }


@dataclass
class CommonAntiPattern:
    """A PatternType that appears in a significant share of the traces."""

    pattern_type: PatternType
    occurrence_count: int
    total_traces: int
    affected_trace_ids: list[str]

    @property
    def occurrence_rate(self) -> float:
        if self.total_traces == 0:
            return 0.0
        return self.occurrence_count / self.total_traces

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern_type": self.pattern_type.value,
            "occurrence_count": self.occurrence_count,
            "total_traces": self.total_traces,
            "occurrence_rate": round(self.occurrence_rate, 3),
            "affected_trace_ids": self.affected_trace_ids,
        }


@dataclass
class CorrelationReport:
    """Aggregated multi-trace correlation findings."""

    total_traces: int
    recurring_failures: list[RecurringFailure] = field(default_factory=list)
    performance_trends: list[PerformanceTrend] = field(default_factory=list)
    common_anti_patterns: list[CommonAntiPattern] = field(default_factory=list)

    # Summary metrics
    overall_error_rate: float = 0.0        # fraction of traces with at least one error
    avg_duration_ms: float = 0.0
    avg_total_tokens: float = 0.0
    avg_total_cost_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_traces": self.total_traces,
            "overall_error_rate": round(self.overall_error_rate, 3),
            "avg_duration_ms": round(self.avg_duration_ms, 2),
            "avg_total_tokens": round(self.avg_total_tokens, 1),
            "avg_total_cost_usd": round(self.avg_total_cost_usd, 6),
            "recurring_failures": [f.to_dict() for f in self.recurring_failures],
            "performance_trends": [t.to_dict() for t in self.performance_trends],
            "common_anti_patterns": [p.to_dict() for p in self.common_anti_patterns],
        }

    def summary(self) -> str:
        """Return a human-readable one-paragraph summary."""
        lines: list[str] = [
            f"Correlation report over {self.total_traces} traces.",
            f"  Overall error rate : {self.overall_error_rate:.0%}",
            f"  Avg duration       : {self.avg_duration_ms:.1f} ms",
            f"  Avg tokens         : {self.avg_total_tokens:.0f}",
            f"  Avg cost           : ${self.avg_total_cost_usd:.6f}",
        ]
        if self.recurring_failures:
            lines.append(
                f"  Recurring failures : {len(self.recurring_failures)} "
                f"(top: \"{self.recurring_failures[0].error_message[:60]}\")"
            )
        if self.performance_trends:
            trend_names = ", ".join(t.metric for t in self.performance_trends)
            lines.append(f"  Performance trends : {trend_names}")
        if self.common_anti_patterns:
            ap_names = ", ".join(
                p.pattern_type.value for p in self.common_anti_patterns
            )
            lines.append(f"  Common anti-patterns: {ap_names}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def correlate_traces(
    traces: list[Trace],
    *,
    failure_threshold: float = 0.5,
    anti_pattern_threshold: float = 0.5,
    trend_min_traces: int = 3,
) -> CorrelationReport:
    """
    Analyse a collection of traces and return a :class:`CorrelationReport`.

    Parameters
    ----------
    traces:
        Ordered list of ``Trace`` objects (oldest first for trend detection).
    failure_threshold:
        Minimum fraction of traces a given error must appear in to be reported
        as a *recurring failure* (default 0.5 = 50 %).
    anti_pattern_threshold:
        Minimum fraction of traces a ``PatternType`` must appear in to be
        reported as a *common anti-pattern* (default 0.5 = 50 %).
    trend_min_traces:
        Minimum number of traces required before a performance trend is flagged
        (default 3).

    Returns
    -------
    CorrelationReport
        Structured report with all findings.
    """
    if not traces:
        return CorrelationReport(total_traces=0)

    n = len(traces)

    # Build DAGs + run pattern detection for every trace
    dags: list[CausalDAG] = []
    patterns_per_trace: list[list[DetectedPattern]] = []
    for trace in traces:
        dag = build_causal_dag(trace)
        pats = detect_patterns(trace, dag)
        dags.append(dag)
        patterns_per_trace.append(pats)

    # --- Summary metrics ---
    traces_with_errors = sum(1 for t in traces if t.has_errors)
    overall_error_rate = traces_with_errors / n

    durations = [t.duration_ms for t in traces]
    tokens = [float(t.total_tokens) for t in traces]
    costs = [t.total_cost_usd for t in traces]

    avg_duration_ms = sum(durations) / n
    avg_total_tokens = sum(tokens) / n
    avg_total_cost_usd = sum(costs) / n

    report = CorrelationReport(
        total_traces=n,
        overall_error_rate=overall_error_rate,
        avg_duration_ms=avg_duration_ms,
        avg_total_tokens=avg_total_tokens,
        avg_total_cost_usd=avg_total_cost_usd,
    )

    # --- Recurring failures ---
    report.recurring_failures = _detect_recurring_failures(
        traces, threshold=failure_threshold
    )

    # --- Performance trends ---
    report.performance_trends = _detect_performance_trends(
        traces,
        durations=durations,
        tokens=tokens,
        costs=costs,
        min_traces=trend_min_traces,
    )

    # --- Common anti-patterns ---
    report.common_anti_patterns = _detect_common_anti_patterns(
        traces, patterns_per_trace, threshold=anti_pattern_threshold
    )

    return report


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _detect_recurring_failures(
    traces: list[Trace],
    *,
    threshold: float,
) -> list[RecurringFailure]:
    """
    Find error messages that appear in more than *threshold* fraction of traces.

    Error messages are normalised by stripping trailing punctuation and
    lowercasing so that minor formatting differences do not split the same
    root cause into separate buckets.
    """
    # Per-error: {normalised_message: {trace_id, span_name, ...}}
    error_to_traces: dict[str, set[str]] = defaultdict(set)
    error_to_spans: dict[str, list[str]] = defaultdict(list)
    raw_message: dict[str, str] = {}  # normalised → original

    for trace in traces:
        for span in trace.spans:
            if span.status != SpanStatus.ERROR or not span.error_message:
                continue
            norm = _normalise_error(span.error_message)
            error_to_traces[norm].add(trace.trace_id)
            error_to_spans[norm].append(span.name)
            raw_message.setdefault(norm, span.error_message)

    n = len(traces)
    results: list[RecurringFailure] = []
    for norm, trace_ids in error_to_traces.items():
        rate = len(trace_ids) / n
        if rate > threshold:
            results.append(RecurringFailure(
                error_message=raw_message[norm],
                occurrence_count=len(trace_ids),
                total_traces=n,
                affected_trace_ids=sorted(trace_ids),
                affected_span_names=list(dict.fromkeys(error_to_spans[norm])),
            ))

    # Sort by occurrence rate descending
    results.sort(key=lambda r: r.occurrence_rate, reverse=True)
    return results


def _detect_performance_trends(
    traces: list[Trace],
    *,
    durations: list[float],
    tokens: list[float],
    costs: list[float],
    min_traces: int,
) -> list[PerformanceTrend]:
    """
    Detect monotonic increasing trends in duration, token usage, or cost.

    A trend is flagged when the linear slope across the trace sequence is
    positive (degradation) and at least *min_traces* traces are present.
    """
    if len(traces) < min_traces:
        return []

    trace_ids = [t.trace_id for t in traces]
    results: list[PerformanceTrend] = []

    for metric, values in [
        ("duration_ms", durations),
        ("total_tokens", tokens),
        ("total_cost_usd", costs),
    ]:
        slope = _linear_slope(values)
        if slope is None:
            continue

        direction = "increasing" if slope > 0 else "decreasing"

        # Only report if there's a meaningful upward trend (degradation)
        if slope > 0 and _is_monotonic_trend(values):
            results.append(PerformanceTrend(
                metric=metric,
                direction=direction,
                values=values,
                trace_ids=trace_ids,
                slope=slope,
            ))

    return results


def _detect_common_anti_patterns(
    traces: list[Trace],
    patterns_per_trace: list[list[DetectedPattern]],
    *,
    threshold: float,
) -> list[CommonAntiPattern]:
    """
    Find PatternTypes that appear in more than *threshold* fraction of traces.
    """
    n = len(traces)
    # pattern_type -> set of trace indices that contain it
    ptype_to_trace_ids: dict[PatternType, set[str]] = defaultdict(set)

    for trace, pats in zip(traces, patterns_per_trace):
        seen_types: set[PatternType] = set()
        for p in pats:
            if p.pattern_type not in seen_types:
                ptype_to_trace_ids[p.pattern_type].add(trace.trace_id)
                seen_types.add(p.pattern_type)

    results: list[CommonAntiPattern] = []
    for ptype, trace_ids in ptype_to_trace_ids.items():
        rate = len(trace_ids) / n
        if rate > threshold:
            results.append(CommonAntiPattern(
                pattern_type=ptype,
                occurrence_count=len(trace_ids),
                total_traces=n,
                affected_trace_ids=sorted(trace_ids),
            ))

    results.sort(key=lambda p: p.occurrence_rate, reverse=True)
    return results


# ---------------------------------------------------------------------------
# Utility maths
# ---------------------------------------------------------------------------


def _normalise_error(message: str) -> str:
    """Lower-case and strip leading/trailing whitespace & punctuation."""
    return message.strip().rstrip(".!?").lower()


def _linear_slope(values: list[float]) -> float | None:
    """
    Return the slope of the best-fit line through *values* using the
    closed-form ordinary-least-squares formula.  Returns ``None`` if there
    are fewer than 2 data points.
    """
    n = len(values)
    if n < 2:
        return None
    xs = list(range(n))
    x_mean = sum(xs) / n
    y_mean = sum(values) / n
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, values))
    denominator = sum((x - x_mean) ** 2 for x in xs)
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _is_monotonic_trend(values: list[float]) -> bool:
    """
    Return ``True`` when values are *broadly* increasing: at least 2/3 of
    consecutive pairs show an increase.  This is more robust than strict
    monotonicity when traces are noisy.
    """
    if len(values) < 2:
        return False
    increases = sum(1 for a, b in zip(values, values[1:]) if b > a)
    return increases >= (len(values) - 1) * 2 / 3
