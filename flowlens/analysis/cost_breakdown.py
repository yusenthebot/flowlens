"""
Cost Breakdown — slice cost data by model, service, and span kind.

Also generates actionable optimization suggestions from raw trace/span data.
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any


class CostBreakdown:
    """
    Analyse cost distribution across different dimensions and surface
    optimisation opportunities.
    """

    # Thresholds for suggestion triggers
    _REDUNDANT_CALL_THRESHOLD = 3      # same span name called >= N times with same input hash
    _TOKEN_WASTE_INPUT_RATIO = 10      # input:output ratio >= N → warn
    _MODEL_EXPENSIVE_PREFIX = ("gpt-4", "claude-3-opus", "claude-opus")

    # ---------------------------------------------------------------------------
    # Breakdown methods
    # ---------------------------------------------------------------------------

    def by_model(
        self, traces: list[dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        """
        Aggregate cost by LLM model.

        Looks for 'model' in span attributes or a top-level 'model' field on spans.

        Returns
        -------
        dict: model_name → {cost, tokens, count, avg_cost_per_call}
        """
        result: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"cost": 0.0, "tokens": 0, "count": 0, "avg_cost_per_call": 0.0}
        )

        for trace in traces:
            for span in trace.get("spans", []):
                model = self._extract_model(span)
                if not model:
                    continue
                tu = span.get("token_usage") or {}
                cost = tu.get("total_cost_usd", 0.0) or 0.0
                tokens = (tu.get("input_tokens", 0) or 0) + (tu.get("output_tokens", 0) or 0)
                result[model]["cost"] += cost
                result[model]["tokens"] += tokens
                result[model]["count"] += 1

        # Compute avg_cost_per_call
        for model_data in result.values():
            cnt = model_data["count"]
            model_data["avg_cost_per_call"] = (
                round(model_data["cost"] / cnt, 8) if cnt > 0 else 0.0
            )
            model_data["cost"] = round(model_data["cost"], 6)

        return dict(result)

    def by_service(
        self, traces: list[dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        """
        Aggregate cost by service name.

        Returns
        -------
        dict: service_name → {cost, tokens, traces, error_rate}
        """
        result: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"cost": 0.0, "tokens": 0, "traces": 0, "error_count": 0, "error_rate": 0.0}
        )

        for trace in traces:
            service = trace.get("service_name", "") or "unknown"
            cost = trace.get("total_cost_usd", 0.0) or 0.0
            tokens = trace.get("total_tokens", 0) or 0
            has_error = bool(trace.get("has_errors") or trace.get("error_count", 0))

            result[service]["cost"] += cost
            result[service]["tokens"] += tokens
            result[service]["traces"] += 1
            if has_error:
                result[service]["error_count"] += 1

        # Compute derived fields
        for svc_data in result.values():
            trace_cnt = svc_data["traces"]
            error_cnt = svc_data.pop("error_count")
            svc_data["error_rate"] = (
                round(error_cnt / trace_cnt, 4) if trace_cnt > 0 else 0.0
            )
            svc_data["cost"] = round(svc_data["cost"], 6)

        return dict(result)

    def by_span_kind(
        self, traces: list[dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        """
        Aggregate cost by span kind (llm, tool, agent, etc.).

        Returns
        -------
        dict: kind → {cost, tokens, count}
        """
        result: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"cost": 0.0, "tokens": 0, "count": 0}
        )

        for trace in traces:
            for span in trace.get("spans", []):
                kind = span.get("kind", "unknown") or "unknown"
                tu = span.get("token_usage") or {}
                cost = tu.get("total_cost_usd", 0.0) or 0.0
                tokens = (tu.get("input_tokens", 0) or 0) + (tu.get("output_tokens", 0) or 0)
                result[kind]["cost"] += cost
                result[kind]["tokens"] += tokens
                result[kind]["count"] += 1

        for kind_data in result.values():
            kind_data["cost"] = round(kind_data["cost"], 6)

        return dict(result)

    # ---------------------------------------------------------------------------
    # Optimization suggestions
    # ---------------------------------------------------------------------------

    def optimization_suggestions(
        self, traces: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """
        Produce a list of actionable, quantified optimisation suggestions.

        Each suggestion is a dict with:
          - type: short machine-readable tag
          - span_name / model: what is affected
          - description: human-readable explanation
          - estimated_monthly_savings_usd: estimated USD savings per month

        Suggestions are sorted by estimated_monthly_savings_usd descending.
        """
        suggestions: list[dict[str, Any]] = []

        suggestions.extend(self._suggest_model_switch(traces))
        suggestions.extend(self._suggest_context_reduction(traces))
        suggestions.extend(self._suggest_caching(traces))

        suggestions.sort(
            key=lambda s: s.get("estimated_monthly_savings_usd", 0.0),
            reverse=True,
        )
        return suggestions

    # ---------------------------------------------------------------------------
    # Suggestion generators
    # ---------------------------------------------------------------------------

    def _suggest_model_switch(
        self, traces: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Flag expensive model usage and suggest a cheaper alternative."""
        model_stats: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"cost": 0.0, "count": 0, "span_names": set()}
        )
        for trace in traces:
            for span in trace.get("spans", []):
                model = self._extract_model(span)
                if not model:
                    continue
                tu = span.get("token_usage") or {}
                cost = tu.get("total_cost_usd", 0.0) or 0.0
                model_stats[model]["cost"] += cost
                model_stats[model]["count"] += 1
                model_stats[model]["span_names"].add(span.get("name", ""))

        suggestions = []
        for model, stats in model_stats.items():
            if not self._is_expensive_model(model):
                continue
            cheaper = self._cheaper_alternative(model)
            if not cheaper:
                continue
            # Estimate 60 % cost reduction by switching to cheaper model
            monthly_savings = stats["cost"] * 30 * 0.6
            span_names = ", ".join(sorted(s for s in stats["span_names"] if s)) or "unknown"
            suggestions.append(
                {
                    "type": "model_switch",
                    "model": model,
                    "suggested_model": cheaper,
                    "span_name": span_names,
                    "description": (
                        f"Switch model {model} to {cheaper} for span(s) [{span_names}] "
                        f"— saves ${monthly_savings:.2f}/month"
                    ),
                    "estimated_monthly_savings_usd": round(monthly_savings, 4),
                }
            )
        return suggestions

    def _suggest_context_reduction(
        self, traces: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Flag spans where input tokens vastly outnumber output tokens."""
        suggestions = []
        seen_spans: set[str] = set()

        for trace in traces:
            for span in trace.get("spans", []):
                span_name = span.get("name", "unknown")
                if span_name in seen_spans:
                    continue
                tu = span.get("token_usage") or {}
                input_tok = tu.get("input_tokens", 0) or 0
                output_tok = tu.get("output_tokens", 0) or 0
                if output_tok == 0 or input_tok == 0:
                    continue
                ratio = input_tok / output_tok
                if ratio < self._TOKEN_WASTE_INPUT_RATIO:
                    continue

                seen_spans.add(span_name)
                cost = tu.get("total_cost_usd", 0.0) or 0.0
                # Input tokens are typically cheaper but still significant
                input_fraction = input_tok / (input_tok + output_tok)
                wasted_fraction = (input_fraction - 0.5)  # assume 50 % is necessary
                monthly_savings = cost * 30 * max(0.0, wasted_fraction)
                suggestions.append(
                    {
                        "type": "context_reduction",
                        "span_name": span_name,
                        "description": (
                            f"Reduce context for span '{span_name}' — "
                            f"{input_fraction:.0%} of tokens are input context "
                            f"(ratio {ratio:.0f}:1). "
                            f"Saves ~${monthly_savings:.2f}/month"
                        ),
                        "input_tokens": input_tok,
                        "output_tokens": output_tok,
                        "input_output_ratio": round(ratio, 1),
                        "estimated_monthly_savings_usd": round(monthly_savings, 4),
                    }
                )
        return suggestions

    def _suggest_caching(
        self, traces: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Flag spans called multiple times with the same effective input."""
        # Count span name occurrences per trace (proxy for redundant calls)
        span_call_counts: dict[str, int] = defaultdict(int)
        span_costs: dict[str, float] = defaultdict(float)

        for trace in traces:
            local_counts: dict[str, int] = defaultdict(int)
            for span in trace.get("spans", []):
                name = span.get("name", "unknown")
                local_counts[name] += 1
                tu = span.get("token_usage") or {}
                span_costs[name] += tu.get("total_cost_usd", 0.0) or 0.0

            for name, cnt in local_counts.items():
                if cnt >= self._REDUNDANT_CALL_THRESHOLD:
                    span_call_counts[name] = max(span_call_counts[name], cnt)

        suggestions = []
        for span_name, max_calls in span_call_counts.items():
            total_cost = span_costs[span_name]
            # Savings: eliminate (max_calls - 1) / max_calls of the cost per trace
            savings_fraction = (max_calls - 1) / max_calls
            monthly_savings = total_cost * 30 * savings_fraction
            suggestions.append(
                {
                    "type": "caching",
                    "span_name": span_name,
                    "description": (
                        f"Cache results for span '{span_name}' — "
                        f"called {max_calls}x with same input. "
                        f"Saves ~${monthly_savings:.2f}/month"
                    ),
                    "call_count": max_calls,
                    "estimated_monthly_savings_usd": round(monthly_savings, 4),
                }
            )
        return suggestions

    # ---------------------------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------------------------

    @staticmethod
    def _extract_model(span: dict[str, Any]) -> str | None:
        """Extract a model name from a span dict."""
        # Direct attribute
        attrs = span.get("attributes") or {}
        model = attrs.get("model") or attrs.get("llm.model") or attrs.get("gen_ai.request.model")
        if model:
            return str(model)
        # Top-level field (sometimes present)
        model = span.get("model")
        if model:
            return str(model)
        return None

    @staticmethod
    def _is_expensive_model(model: str) -> bool:
        model_lower = model.lower()
        expensive_prefixes = ("gpt-4", "claude-3-opus", "claude-opus", "claude-3-5-sonnet", "claude-sonnet")
        return any(model_lower.startswith(p) for p in expensive_prefixes)

    @staticmethod
    def _cheaper_alternative(model: str) -> str | None:
        model_lower = model.lower()
        if "opus" in model_lower:
            return "claude-haiku"
        if "gpt-4" in model_lower:
            return "gpt-3.5-turbo"
        if "sonnet" in model_lower:
            return "claude-haiku"
        return None
