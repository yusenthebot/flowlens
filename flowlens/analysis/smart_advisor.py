"""
Smart Recommendations Engine — fleet-wide analysis, regression detection,
and pipeline-order suggestions.

SmartAdvisor complements the single-trace TraceAdvisor with cross-trace
intelligence:

- analyze_fleet(traces)          Fleet-wide cost hotspots, failure patterns,
                                 model downgrade opportunities.
- suggest_pipeline_reorder(traces) Order analysis: which span sequences
                                 correlate with success vs failure?
- detect_regression(recent, baseline) Flag latency / error-rate regressions
                                 relative to a baseline set of traces.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from ..sdk.models import Span, SpanKind, SpanStatus, Trace


# ---------------------------------------------------------------------------
# Fleet recommendation model
# ---------------------------------------------------------------------------


@dataclass
class FleetRecommendation:
    """A single actionable fleet-wide recommendation."""

    category: str          # "cost", "reliability", "performance", "model"
    title: str
    description: str
    severity: str = "info"  # "info" | "warning" | "critical"
    estimated_savings_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "title": self.title,
            "description": self.description,
            "severity": self.severity,
            "estimated_savings_usd": round(self.estimated_savings_usd, 6),
        }


# ---------------------------------------------------------------------------
# Regression report model
# ---------------------------------------------------------------------------


@dataclass
class RegressionReport:
    """Summary of a detected regression between recent and baseline traces."""

    metric: str           # "error_rate" | "latency" | "cost"
    service_name: str
    baseline_value: float
    recent_value: float
    change_pct: float     # positive = worsened
    description: str
    severity: str = "warning"

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "service_name": self.service_name,
            "baseline_value": round(self.baseline_value, 4),
            "recent_value": round(self.recent_value, 4),
            "change_pct": round(self.change_pct, 2),
            "description": self.description,
            "severity": self.severity,
        }


# ---------------------------------------------------------------------------
# Pipeline reorder suggestion model
# ---------------------------------------------------------------------------


@dataclass
class PipelineReorderSuggestion:
    """Suggested pipeline reorder based on success/failure correlation."""

    current_sequence: list[str]
    suggested_sequence: list[str]
    success_rate_current: float
    success_rate_suggested: float
    description: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "current_sequence": self.current_sequence,
            "suggested_sequence": self.suggested_sequence,
            "success_rate_current": round(self.success_rate_current, 4),
            "success_rate_suggested": round(self.success_rate_suggested, 4),
            "description": self.description,
        }


# ---------------------------------------------------------------------------
# SmartAdvisor
# ---------------------------------------------------------------------------


class SmartAdvisor:
    """
    Fleet-wide intelligence layer on top of individual :class:`TraceAdvisor`.

    All methods accept plain :class:`~flowlens.sdk.models.Trace` objects and
    return JSON-serialisable dicts (or lists of dataclass instances).
    """

    # Thresholds
    _COST_TOP_N = 3
    _FAILURE_RATE_THRESHOLD = 0.05  # 5% of traces
    _OPUS_MODEL_KEYWORDS = ("opus",)
    _SONNET_MODEL_KEYWORDS = ("sonnet",)
    _REGRESSION_THRESHOLD = 0.20  # 20% worsening triggers a regression flag
    _MIN_TRACES_FOR_STATS = 2

    # ------------------------------------------------------------------
    # Fleet analysis
    # ------------------------------------------------------------------

    def analyze_fleet(self, traces: list[Trace]) -> dict[str, Any]:
        """
        Produce fleet-wide recommendations from a collection of traces.

        Returns
        -------
        dict with keys:
            ``recommendations`` — list of :class:`FleetRecommendation` dicts.
            ``top_expensive_spans`` — top-N most expensive spans across all traces.
            ``most_common_failure`` — most frequent error message and its rate.
            ``summary`` — human-readable paragraph.
        """
        if not traces:
            return {
                "recommendations": [],
                "top_expensive_spans": [],
                "most_common_failure": None,
                "summary": "No traces available for fleet analysis.",
            }

        recommendations: list[FleetRecommendation] = []

        top_spans = self._top_expensive_spans(traces)
        failure_info = self._most_common_failure(traces)
        downgrade_recs = self._model_downgrade_suggestions(traces)

        recommendations.extend(self._cost_recommendations(top_spans))
        if failure_info:
            recommendations.extend(self._failure_recommendations(failure_info, traces))
        recommendations.extend(downgrade_recs)

        summary_parts = []
        if top_spans:
            span_names = ", ".join(f"'{s['name']}'" for s in top_spans[:3])
            summary_parts.append(
                f"Top expensive spans: {span_names}."
            )
        if failure_info:
            summary_parts.append(
                f"Most common failure: '{failure_info['error_message']}' "
                f"(affects {failure_info['rate']:.1%} of traces)."
            )
        if not summary_parts:
            summary_parts.append("Fleet looks healthy with no obvious hotspots.")

        return {
            "recommendations": [r.to_dict() for r in recommendations],
            "top_expensive_spans": top_spans,
            "most_common_failure": failure_info,
            "summary": " ".join(summary_parts),
        }

    # ------------------------------------------------------------------
    # Pipeline reorder suggestions
    # ------------------------------------------------------------------

    def suggest_pipeline_reorder(
        self, traces: list[Trace]
    ) -> list[PipelineReorderSuggestion]:
        """
        Analyse span sequences in successful vs failed traces.

        For each 2-span transition pair found in traces, compute the success
        rate when that pair appears as (A→B) vs (B→A).  If one order is
        materially better, return a suggestion.

        Returns
        -------
        list of :class:`PipelineReorderSuggestion`
        """
        if len(traces) < self._MIN_TRACES_FOR_STATS:
            return []

        # Map: (a_name, b_name) -> [is_success]
        pair_outcomes: dict[tuple[str, str], list[bool]] = defaultdict(list)

        for trace in traces:
            success = not trace.has_errors
            # Get ordered span names (by start_time)
            ordered = sorted(trace.spans, key=lambda s: s.start_time)
            names = [s.name for s in ordered]
            for i in range(len(names) - 1):
                pair = (names[i], names[i + 1])
                pair_outcomes[pair].append(success)

        suggestions: list[PipelineReorderSuggestion] = []
        seen_pairs: set[frozenset[str]] = set()

        for (a, b), outcomes_ab in pair_outcomes.items():
            reverse = (b, a)
            if reverse not in pair_outcomes:
                continue
            key = frozenset({a, b})
            if key in seen_pairs:
                continue
            seen_pairs.add(key)

            outcomes_ba = pair_outcomes[reverse]
            if len(outcomes_ab) < 2 or len(outcomes_ba) < 2:
                continue

            rate_ab = sum(outcomes_ab) / len(outcomes_ab)
            rate_ba = sum(outcomes_ba) / len(outcomes_ba)

            # Only suggest if one order is at least 10 percentage points better
            if rate_ab > rate_ba + 0.10:
                suggestions.append(
                    PipelineReorderSuggestion(
                        current_sequence=[b, a],
                        suggested_sequence=[a, b],
                        success_rate_current=rate_ba,
                        success_rate_suggested=rate_ab,
                        description=(
                            f"Traces with '{a}' before '{b}' succeed "
                            f"{rate_ab:.0%} of the time vs {rate_ba:.0%} "
                            f"when the order is reversed. Consider running "
                            f"'{a}' first."
                        ),
                    )
                )
            elif rate_ba > rate_ab + 0.10:
                suggestions.append(
                    PipelineReorderSuggestion(
                        current_sequence=[a, b],
                        suggested_sequence=[b, a],
                        success_rate_current=rate_ab,
                        success_rate_suggested=rate_ba,
                        description=(
                            f"Traces with '{b}' before '{a}' succeed "
                            f"{rate_ba:.0%} of the time vs {rate_ab:.0%} "
                            f"when the order is reversed. Consider running "
                            f"'{b}' first."
                        ),
                    )
                )

        return suggestions

    # ------------------------------------------------------------------
    # Regression detection
    # ------------------------------------------------------------------

    def detect_regression(
        self,
        recent_traces: list[Trace],
        baseline_traces: list[Trace],
        service_name: str = "",
    ) -> list[RegressionReport]:
        """
        Compare *recent_traces* against *baseline_traces* and flag regressions.

        A regression is flagged when a metric worsens by more than
        ``_REGRESSION_THRESHOLD`` (default 20 %).

        Checks
        ------
        - Error rate increase
        - Average latency increase
        - Average cost increase

        Parameters
        ----------
        recent_traces:
            Traces collected from the recent period.
        baseline_traces:
            Traces that represent the healthy baseline.
        service_name:
            Optional label used in regression descriptions (e.g. experiment
            name or service label).

        Returns
        -------
        list of :class:`RegressionReport`
        """
        reports: list[RegressionReport] = []
        label = service_name or "the service"

        if not baseline_traces or not recent_traces:
            return reports

        # --- error rate ---
        baseline_err = _error_rate(baseline_traces)
        recent_err = _error_rate(recent_traces)
        if baseline_err < 1.0:
            if baseline_err == 0 and recent_err > 0:
                change_pct = 100.0
            elif baseline_err > 0:
                change_pct = (recent_err - baseline_err) / baseline_err * 100
            else:
                change_pct = 0.0

            if change_pct > self._REGRESSION_THRESHOLD * 100:
                severity = "critical" if change_pct >= 100 else "warning"
                reports.append(
                    RegressionReport(
                        metric="error_rate",
                        service_name=label,
                        baseline_value=baseline_err,
                        recent_value=recent_err,
                        change_pct=change_pct,
                        description=(
                            f"Error rate increased from {baseline_err:.1%} to "
                            f"{recent_err:.1%} (+{change_pct:.0f}%) for {label}."
                        ),
                        severity=severity,
                    )
                )

        # --- average latency ---
        baseline_dur = _mean_duration(baseline_traces)
        recent_dur = _mean_duration(recent_traces)
        if baseline_dur > 0:
            change_pct = (recent_dur - baseline_dur) / baseline_dur * 100
            if change_pct > self._REGRESSION_THRESHOLD * 100:
                reports.append(
                    RegressionReport(
                        metric="latency",
                        service_name=label,
                        baseline_value=baseline_dur,
                        recent_value=recent_dur,
                        change_pct=change_pct,
                        description=(
                            f"Avg latency increased by {change_pct:.0f}% for {label} "
                            f"({baseline_dur:.0f} ms → {recent_dur:.0f} ms)."
                        ),
                        severity="warning",
                    )
                )

        # --- average cost ---
        baseline_cost = _mean_cost(baseline_traces)
        recent_cost = _mean_cost(recent_traces)
        if baseline_cost > 0:
            change_pct = (recent_cost - baseline_cost) / baseline_cost * 100
            if change_pct > self._REGRESSION_THRESHOLD * 100:
                reports.append(
                    RegressionReport(
                        metric="cost",
                        service_name=label,
                        baseline_value=baseline_cost,
                        recent_value=recent_cost,
                        change_pct=change_pct,
                        description=(
                            f"Avg cost per trace increased by {change_pct:.0f}% for {label} "
                            f"(${baseline_cost:.4f} → ${recent_cost:.4f})."
                        ),
                        severity="warning",
                    )
                )

        return reports

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _top_expensive_spans(
        self, traces: list[Trace]
    ) -> list[dict[str, Any]]:
        """Return the top-N most expensive span names by total cost."""
        cost_by_name: dict[str, float] = defaultdict(float)
        count_by_name: dict[str, int] = defaultdict(int)

        for trace in traces:
            for span in trace.spans:
                if span.token_usage and span.token_usage.total_cost_usd > 0:
                    cost_by_name[span.name] += span.token_usage.total_cost_usd
                    count_by_name[span.name] += 1

        ranked = sorted(cost_by_name.items(), key=lambda kv: kv[1], reverse=True)
        return [
            {
                "name": name,
                "total_cost_usd": round(cost, 6),
                "occurrence_count": count_by_name[name],
                "avg_cost_usd": round(cost / count_by_name[name], 6),
            }
            for name, cost in ranked[: self._COST_TOP_N]
        ]

    def _most_common_failure(
        self, traces: list[Trace]
    ) -> dict[str, Any] | None:
        """Find the single most common error message across all traces."""
        error_counts: Counter[str] = Counter()
        total_traces = len(traces)

        for trace in traces:
            for span in trace.spans:
                if span.status == SpanStatus.ERROR and span.error_message:
                    error_counts[span.error_message] += 1

        if not error_counts:
            return None

        most_common_msg, count = error_counts.most_common(1)[0]
        # Rate = fraction of traces that contain this error at least once
        affected_traces = sum(
            1
            for t in traces
            if any(
                s.status == SpanStatus.ERROR and s.error_message == most_common_msg
                for s in t.spans
            )
        )
        rate = affected_traces / total_traces if total_traces > 0 else 0.0

        return {
            "error_message": most_common_msg,
            "total_occurrences": count,
            "affected_traces": affected_traces,
            "rate": rate,
        }

    def _model_downgrade_suggestions(
        self, traces: list[Trace]
    ) -> list[FleetRecommendation]:
        """
        Suggest cheaper model alternatives for spans using expensive models.

        Currently checks: if a span consistently uses an opus-class model
        with low output-to-input ratio (< 0.05), suggest sonnet instead.
        """
        recs: list[FleetRecommendation] = []
        # Aggregate per model: (total_input, total_output)
        model_tokens: dict[str, list[tuple[int, int]]] = defaultdict(list)

        for trace in traces:
            for span in trace.spans:
                if not span.token_usage:
                    continue
                model = span.attributes.get("gen_ai.request.model", "")
                if not model:
                    continue
                model_lower = model.lower()
                if any(k in model_lower for k in self._OPUS_MODEL_KEYWORDS):
                    model_tokens[model].append(
                        (span.token_usage.input_tokens, span.token_usage.output_tokens)
                    )

        for model, samples in model_tokens.items():
            if len(samples) < self._MIN_TRACES_FOR_STATS:
                continue
            total_in = sum(s[0] for s in samples)
            total_out = sum(s[1] for s in samples)
            if total_in == 0:
                continue
            ratio = total_out / total_in
            if ratio < 0.05:
                # Low output ratio suggests the expensive model may be overkill
                recs.append(
                    FleetRecommendation(
                        category="model",
                        title=f"Consider downgrading '{model}' to sonnet",
                        description=(
                            f"Span(s) using '{model}' have a very low "
                            f"output/input ratio ({ratio:.3f}), suggesting the "
                            f"expensive model may be overkill. A sonnet-class "
                            f"model could achieve similar quality at lower cost."
                        ),
                        severity="info",
                    )
                )

        return recs

    def _cost_recommendations(
        self, top_spans: list[dict[str, Any]]
    ) -> list[FleetRecommendation]:
        recs: list[FleetRecommendation] = []
        for span_info in top_spans:
            recs.append(
                FleetRecommendation(
                    category="cost",
                    title=f"Optimise span '{span_info['name']}' (top cost driver)",
                    description=(
                        f"Span '{span_info['name']}' accounted for "
                        f"${span_info['total_cost_usd']:.4f} total cost across "
                        f"{span_info['occurrence_count']} occurrences "
                        f"(avg ${span_info['avg_cost_usd']:.4f}/call). "
                        f"Consider caching, prompt compression, or routing to "
                        f"a cheaper model."
                    ),
                    severity="warning",
                    estimated_savings_usd=span_info["total_cost_usd"] * 0.3,
                )
            )
        return recs

    def _failure_recommendations(
        self,
        failure_info: dict[str, Any],
        traces: list[Trace],
    ) -> list[FleetRecommendation]:
        rate = failure_info["rate"]
        severity = "critical" if rate >= 0.10 else "warning" if rate >= 0.05 else "info"
        return [
            FleetRecommendation(
                category="reliability",
                title=f"Fix recurring failure: '{failure_info['error_message']}'",
                description=(
                    f"Error '{failure_info['error_message']}' affects "
                    f"{failure_info['affected_traces']} of {len(traces)} traces "
                    f"({rate:.1%}). Add retry logic or validate inputs to "
                    f"eliminate this recurring failure."
                ),
                severity=severity,
            )
        ]


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _error_rate(traces: list[Trace]) -> float:
    if not traces:
        return 0.0
    return sum(1 for t in traces if t.has_errors) / len(traces)


def _mean_duration(traces: list[Trace]) -> float:
    durations = [t.duration_ms for t in traces if t.duration_ms > 0]
    return statistics.mean(durations) if durations else 0.0


def _mean_cost(traces: list[Trace]) -> float:
    costs = [t.total_cost_usd for t in traces]
    return statistics.mean(costs) if costs else 0.0
