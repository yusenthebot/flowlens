"""
Trace Diff Engine — compare two traces or two groups of traces (experiments).

TraceDiff.diff(trace_a, trace_b) returns a DiffResult dataclass with:
- duration_diff_ms, cost_diff_usd, token_diff
- span_diffs: per-span comparisons matched by name
- only_in_a / only_in_b: spans exclusive to one side
- pattern_diffs: patterns present in one trace but not the other
- summary: human-readable summary string

TraceDiff.diff_experiments(traces_a, traces_b) aggregates across lists of
traces and compares averages, p95 latency and error rates between the groups.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any

from ..sdk.models import Span, Trace
from .dag_builder import build_causal_dag
from .patterns import detect_patterns

# ---------------------------------------------------------------------------
# Per-span comparison result
# ---------------------------------------------------------------------------


@dataclass
class SpanComparison:
    """Side-by-side comparison of a single span (matched by name)."""

    name: str
    a_duration_ms: float | None = None
    b_duration_ms: float | None = None
    a_tokens: int | None = None
    b_tokens: int | None = None
    a_status: str | None = None
    b_status: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "a_duration_ms": self.a_duration_ms,
            "b_duration_ms": self.b_duration_ms,
            "duration_diff_ms": (
                round((self.b_duration_ms or 0) - (self.a_duration_ms or 0), 2)
                if self.a_duration_ms is not None and self.b_duration_ms is not None
                else None
            ),
            "a_tokens": self.a_tokens,
            "b_tokens": self.b_tokens,
            "a_status": self.a_status,
            "b_status": self.b_status,
        }


# ---------------------------------------------------------------------------
# DiffResult
# ---------------------------------------------------------------------------


@dataclass
class DiffResult:
    """
    Complete diff between two traces (A and B).

    Positive deltas mean B is larger/slower/more expensive than A.
    Negative deltas mean B improved over A.
    """

    trace_a_id: str
    trace_b_id: str

    # Aggregate metric deltas (B minus A)
    duration_diff_ms: float = 0.0
    cost_diff_usd: float = 0.0
    token_diff: int = 0

    # Per-span comparisons (spans that exist in both traces, matched by name)
    span_diffs: list[SpanComparison] = field(default_factory=list)

    # Spans exclusive to one side
    only_in_a: list[str] = field(default_factory=list)
    only_in_b: list[str] = field(default_factory=list)

    # Pattern-level diff
    # patterns that appeared in A but not B (resolved)
    patterns_only_in_a: list[str] = field(default_factory=list)
    # patterns that appeared in B but not A (new issues)
    patterns_only_in_b: list[str] = field(default_factory=list)

    # Human-readable summary
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_a_id": self.trace_a_id,
            "trace_b_id": self.trace_b_id,
            "duration_diff_ms": round(self.duration_diff_ms, 2),
            "cost_diff_usd": round(self.cost_diff_usd, 6),
            "token_diff": self.token_diff,
            "span_diffs": [s.to_dict() for s in self.span_diffs],
            "only_in_a": self.only_in_a,
            "only_in_b": self.only_in_b,
            "pattern_diffs": {
                "resolved_in_b": self.patterns_only_in_a,
                "new_in_b": self.patterns_only_in_b,
            },
            "summary": self.summary,
        }


# ---------------------------------------------------------------------------
# ExperimentDiffResult
# ---------------------------------------------------------------------------


@dataclass
class ExperimentDiffResult:
    """
    Aggregate diff between two groups (experiments) of traces.

    All statistics are computed over the full list of traces in each group.
    """

    experiment_a: str
    experiment_b: str

    # Averages
    avg_duration_diff_ms: float = 0.0
    avg_cost_diff_usd: float = 0.0
    avg_token_diff: float = 0.0

    # p95 latency
    p95_duration_a_ms: float = 0.0
    p95_duration_b_ms: float = 0.0
    p95_duration_diff_ms: float = 0.0

    # Error rates
    error_rate_a: float = 0.0
    error_rate_b: float = 0.0
    error_rate_diff: float = 0.0

    # Human-readable summary
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_a": self.experiment_a,
            "experiment_b": self.experiment_b,
            "avg_duration_diff_ms": round(self.avg_duration_diff_ms, 2),
            "avg_cost_diff_usd": round(self.avg_cost_diff_usd, 6),
            "avg_token_diff": round(self.avg_token_diff, 1),
            "p95_duration_a_ms": round(self.p95_duration_a_ms, 2),
            "p95_duration_b_ms": round(self.p95_duration_b_ms, 2),
            "p95_duration_diff_ms": round(self.p95_duration_diff_ms, 2),
            "error_rate_a": round(self.error_rate_a, 4),
            "error_rate_b": round(self.error_rate_b, 4),
            "error_rate_diff": round(self.error_rate_diff, 4),
            "summary": self.summary,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _p95(values: list[float]) -> float:
    """Return the 95th-percentile of *values*; returns 0 for empty lists."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    idx = max(0, int(len(sorted_vals) * 0.95) - 1)
    return sorted_vals[idx]


def _get_patterns(trace: Trace) -> set[str]:
    """Return the set of PatternType values detected in *trace*."""
    try:
        dag = build_causal_dag(trace)
        patterns = detect_patterns(trace, dag)
        return {p.pattern_type.value for p in patterns}
    except Exception:
        return set()


def _error_rate(traces: list[Trace]) -> float:
    """Fraction of traces that have at least one error span."""
    if not traces:
        return 0.0
    return sum(1 for t in traces if t.has_errors) / len(traces)


# ---------------------------------------------------------------------------
# TraceDiff
# ---------------------------------------------------------------------------


class TraceDiff:
    """
    Compare individual traces or groups of traces (experiments).

    Usage
    -----
    >>> differ = TraceDiff()
    >>> result = differ.diff(trace_a, trace_b)
    >>> print(result.summary)
    """

    def diff(self, trace_a: Trace, trace_b: Trace) -> DiffResult:
        """
        Compare two individual traces and return a :class:`DiffResult`.

        Spans are matched by *name* (first occurrence per name wins when there
        are duplicate names in a trace).
        """
        result = DiffResult(
            trace_a_id=trace_a.trace_id,
            trace_b_id=trace_b.trace_id,
        )

        # --- aggregate metric deltas ---
        result.duration_diff_ms = trace_b.duration_ms - trace_a.duration_ms
        result.cost_diff_usd = trace_b.total_cost_usd - trace_a.total_cost_usd
        result.token_diff = trace_b.total_tokens - trace_a.total_tokens

        # --- span matching by name ---
        map_a: dict[str, Span] = {}
        for s in trace_a.spans:
            map_a.setdefault(s.name, s)

        map_b: dict[str, Span] = {}
        for s in trace_b.spans:
            map_b.setdefault(s.name, s)

        names_a = set(map_a.keys())
        names_b = set(map_b.keys())

        result.only_in_a = sorted(names_a - names_b)
        result.only_in_b = sorted(names_b - names_a)

        for name in sorted(names_a & names_b):
            sa = map_a[name]
            sb = map_b[name]
            cmp = SpanComparison(
                name=name,
                a_duration_ms=round(sa.duration_ms, 2),
                b_duration_ms=round(sb.duration_ms, 2),
                a_tokens=sa.token_usage.total_tokens if sa.token_usage else 0,
                b_tokens=sb.token_usage.total_tokens if sb.token_usage else 0,
                a_status=sa.status.value,
                b_status=sb.status.value,
            )
            result.span_diffs.append(cmp)

        # --- pattern diff ---
        patterns_a = _get_patterns(trace_a)
        patterns_b = _get_patterns(trace_b)
        result.patterns_only_in_a = sorted(patterns_a - patterns_b)
        result.patterns_only_in_b = sorted(patterns_b - patterns_a)

        # --- human-readable summary ---
        result.summary = self._build_summary(result)

        return result

    def diff_experiments(
        self,
        traces_a: list[Trace],
        traces_b: list[Trace],
        name_a: str = "experiment_a",
        name_b: str = "experiment_b",
    ) -> ExperimentDiffResult:
        """
        Aggregate diff across two groups of traces.

        Compares average duration/cost/tokens, p95 latency, and error rates
        between the two groups.
        """
        result = ExperimentDiffResult(
            experiment_a=name_a,
            experiment_b=name_b,
        )

        # --- durations ---
        durations_a = [t.duration_ms for t in traces_a]
        durations_b = [t.duration_ms for t in traces_b]

        avg_dur_a = statistics.mean(durations_a) if durations_a else 0.0
        avg_dur_b = statistics.mean(durations_b) if durations_b else 0.0
        result.avg_duration_diff_ms = avg_dur_b - avg_dur_a
        result.p95_duration_a_ms = _p95(durations_a)
        result.p95_duration_b_ms = _p95(durations_b)
        result.p95_duration_diff_ms = result.p95_duration_b_ms - result.p95_duration_a_ms

        # --- cost ---
        costs_a = [t.total_cost_usd for t in traces_a]
        costs_b = [t.total_cost_usd for t in traces_b]
        avg_cost_a = statistics.mean(costs_a) if costs_a else 0.0
        avg_cost_b = statistics.mean(costs_b) if costs_b else 0.0
        result.avg_cost_diff_usd = avg_cost_b - avg_cost_a

        # --- tokens ---
        tokens_a = [t.total_tokens for t in traces_a]
        tokens_b = [t.total_tokens for t in traces_b]
        avg_tok_a = statistics.mean(tokens_a) if tokens_a else 0.0
        avg_tok_b = statistics.mean(tokens_b) if tokens_b else 0.0
        result.avg_token_diff = avg_tok_b - avg_tok_a

        # --- error rates ---
        result.error_rate_a = _error_rate(traces_a)
        result.error_rate_b = _error_rate(traces_b)
        result.error_rate_diff = result.error_rate_b - result.error_rate_a

        # --- summary ---
        result.summary = self._build_experiment_summary(result)

        return result

    # ------------------------------------------------------------------
    # Internal summary builders
    # ------------------------------------------------------------------

    @staticmethod
    def _build_summary(r: DiffResult) -> str:
        parts: list[str] = []

        # Duration
        if abs(r.duration_diff_ms) >= 10:
            direction = "faster" if r.duration_diff_ms < 0 else "slower"
            parts.append(
                f"Trace B is {abs(r.duration_diff_ms):.1f} ms {direction} than trace A."
            )

        # Cost
        if abs(r.cost_diff_usd) >= 0.000001:
            direction = "cheaper" if r.cost_diff_usd < 0 else "more expensive"
            parts.append(
                f"Trace B costs ${abs(r.cost_diff_usd):.6f} {direction} than trace A."
            )

        # Tokens
        if r.token_diff != 0:
            direction = "fewer" if r.token_diff < 0 else "more"
            parts.append(
                f"Trace B uses {abs(r.token_diff):,} {direction} tokens."
            )

        # Span changes
        if r.only_in_a:
            parts.append(
                f"Spans only in A: {', '.join(r.only_in_a)}."
            )
        if r.only_in_b:
            parts.append(
                f"Spans only in B: {', '.join(r.only_in_b)}."
            )

        # Pattern changes
        if r.patterns_only_in_a:
            parts.append(
                f"Patterns resolved in B: {', '.join(r.patterns_only_in_a)}."
            )
        if r.patterns_only_in_b:
            parts.append(
                f"New patterns in B: {', '.join(r.patterns_only_in_b)}."
            )

        if not parts:
            parts.append("Traces are effectively identical.")

        return " ".join(parts)

    @staticmethod
    def _build_experiment_summary(r: ExperimentDiffResult) -> str:
        parts: list[str] = []

        # Duration
        if abs(r.avg_duration_diff_ms) >= 1:
            direction = "faster" if r.avg_duration_diff_ms < 0 else "slower"
            parts.append(
                f"Avg latency: {name_b_label(r)} is {abs(r.avg_duration_diff_ms):.1f} ms "
                f"{direction} than {r.experiment_a}."
            )

        # p95
        if abs(r.p95_duration_diff_ms) >= 1:
            direction = "better" if r.p95_duration_diff_ms < 0 else "worse"
            parts.append(
                f"p95 latency is {direction} by {abs(r.p95_duration_diff_ms):.1f} ms "
                f"({r.experiment_a}: {r.p95_duration_a_ms:.1f} ms, "
                f"{r.experiment_b}: {r.p95_duration_b_ms:.1f} ms)."
            )

        # Cost
        if abs(r.avg_cost_diff_usd) >= 0.000001:
            direction = "cheaper" if r.avg_cost_diff_usd < 0 else "more expensive"
            parts.append(
                f"Avg cost: {r.experiment_b} is ${abs(r.avg_cost_diff_usd):.6f} "
                f"{direction} per trace."
            )

        # Error rate
        if abs(r.error_rate_diff) >= 0.001:
            direction = "lower" if r.error_rate_diff < 0 else "higher"
            parts.append(
                f"Error rate is {direction} in {r.experiment_b}: "
                f"{r.error_rate_b:.1%} vs {r.error_rate_a:.1%}."
            )

        if not parts:
            parts.append("Both experiment groups perform similarly.")

        return " ".join(parts)


def name_b_label(r: ExperimentDiffResult) -> str:
    return r.experiment_b
