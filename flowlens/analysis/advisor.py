"""
Advisor Engine — generate actionable recommendations from detected patterns and DAGs.

TraceAdvisor analyses a trace, its causal DAG, and the patterns found in it to
produce:
- A severity score (0–100) that factors in cost impact.
- Human-readable recommendations, each accompanied by a concrete code snippet.
- Estimated per-trace savings (tokens, USD, milliseconds).
- Estimated *monthly* cost savings given a call frequency assumption.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..sdk.models import Trace
from .models import CausalDAG, DetectedPattern, PatternType


# ---------------------------------------------------------------------------
# Recommendation model
# ---------------------------------------------------------------------------


@dataclass
class Recommendation:
    """
    A single actionable recommendation for improving an agent trace.

    Attributes
    ----------
    pattern_type:
        The :class:`PatternType` that triggered this recommendation.
    title:
        Short one-line description of the recommended fix.
    description:
        Longer explanation of why this matters and what to do.
    code_snippet:
        Optional Python code illustrating the fix.
    severity:
        Inherited from the detected pattern (``"info"``, ``"warning"``,
        ``"critical"``).
    cost_impact_usd:
        Estimated single-trace USD saving from applying this recommendation.
    """

    pattern_type: PatternType
    title: str
    description: str
    code_snippet: str = ""
    severity: str = "info"
    cost_impact_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern_type": self.pattern_type.value,
            "title": self.title,
            "description": self.description,
            "code_snippet": self.code_snippet,
            "severity": self.severity,
            "cost_impact_usd": round(self.cost_impact_usd, 6),
        }


# ---------------------------------------------------------------------------
# TraceAdvisor
# ---------------------------------------------------------------------------


@dataclass
class TraceAdvisor:
    """
    Automatic recommendation engine.

    Parameters
    ----------
    trace:
        The complete agent execution trace.
    dag:
        The causal DAG built from ``trace``.
    patterns:
        Detected patterns from :func:`~flowlens.analysis.patterns.detect_patterns`.
    traces_per_month:
        Expected number of times this trace (or equivalent workflow) runs per
        month.  Used to compute *estimated_monthly_savings*.  Defaults to 1 000.
    """

    trace: Trace
    dag: CausalDAG
    patterns: list[DetectedPattern]
    traces_per_month: int = 1_000

    # ------------------------------------------------------------------
    # Severity score
    # ------------------------------------------------------------------

    @property
    def severity_score(self) -> int:
        """
        Compute a 0–100 severity score that reflects both operational risk and
        cost impact.

        Breakdown
        ---------
        - Critical patterns: +30 pts each (capped at 60)
        - Warning patterns:  +15 pts each (capped at 30)
        - Info patterns:     +5  pts each (capped at 10)
        - Error count:       +5  per error span (capped at 20)
        - Cascade depth:     +5  per level (capped at 15)
        - Cost impact:       up to +10 extra pts when total cost > $0.10 per trace
        """
        score = 0

        # --- Pattern contributions ---
        critical_pts = 0
        warning_pts = 0
        info_pts = 0

        for p in self.patterns:
            # Positive patterns (error_recovery) should not inflate severity
            if p.pattern_type == PatternType.ERROR_RECOVERY:
                continue
            if p.severity == "critical":
                critical_pts += 30
            elif p.severity == "warning":
                warning_pts += 15
            elif p.severity == "info":
                info_pts += 5

        score += min(60, critical_pts)
        score += min(30, warning_pts)
        score += min(10, info_pts)

        # --- Error count ---
        error_count = self.trace.error_count
        if error_count > 0:
            score += min(20, error_count * 5)

        # --- Cascade depth ---
        cascade_depth = self.dag.cascade_depth
        if cascade_depth > 0:
            score += min(15, cascade_depth * 5)

        # --- Cost impact bonus ---
        total_cost = self.trace.total_cost_usd
        if total_cost >= 0.10:
            score += min(10, int(total_cost * 10))

        return min(100, score)

    # ------------------------------------------------------------------
    # Savings estimation
    # ------------------------------------------------------------------

    @property
    def estimated_savings(self) -> dict[str, Any]:
        """
        Estimate potential per-trace savings from fixing detected patterns.

        Returns
        -------
        dict with keys:
            ``token_savings`` (int), ``cost_savings_usd`` (float),
            ``time_savings_ms`` (float).
        """
        token_savings = 0
        cost_savings = 0.0
        time_savings = 0.0

        for pattern in self.patterns:
            ptype = pattern.pattern_type

            if ptype == PatternType.REDUNDANT_CALLS:
                call_count = pattern.details.get("call_count", 2)
                savings_count = call_count - 1
                token_savings += savings_count * 500
                cost_savings += savings_count * 0.01
                time_savings += savings_count * 100

            elif ptype == PatternType.SLOW_TOOL:
                slowness = pattern.details.get("slowness_factor", 3.0)
                duration = pattern.details.get("duration_ms", 0.0)
                avg_duration = duration / slowness
                time_savings += duration - avg_duration

            elif ptype == PatternType.COST_SPIKE:
                cost_usd = pattern.details.get("cost_usd", 0.0)
                cost_savings += cost_usd * 0.3
                tokens = pattern.details.get("token_count", 0)
                token_savings += int(tokens * 0.3)

            elif ptype == PatternType.CONTEXT_OVERFLOW:
                usage_ratio = pattern.details.get("usage_ratio", 0.95)
                if usage_ratio >= 0.95:
                    tokens = pattern.details.get("total_tokens", 0)
                    token_savings += int(tokens * 0.2)
                    cost_savings += 0.05

            elif ptype == PatternType.TOKEN_WASTE:
                wasted_cost = pattern.details.get("wasted_cost_usd", 0.0)
                input_tokens = pattern.details.get("input_tokens", 0)
                # Assume we can cut 50% of input by shortening the prompt
                cost_savings += wasted_cost * 0.5
                token_savings += int(input_tokens * 0.5)

            elif ptype == PatternType.SEQUENTIAL_BOTTLENECK:
                savings_ms = pattern.details.get("potential_savings_ms", 0.0)
                time_savings += savings_ms

        return {
            "token_savings": token_savings,
            "cost_savings_usd": round(cost_savings, 4),
            "time_savings_ms": round(time_savings, 1),
        }

    @property
    def estimated_monthly_savings(self) -> dict[str, Any]:
        """
        Project per-trace savings to a monthly figure based on
        ``self.traces_per_month``.

        Returns
        -------
        dict with keys:
            ``token_savings_monthly`` (int),
            ``cost_savings_usd_monthly`` (float),
            ``time_savings_ms_monthly`` (float),
            ``traces_per_month`` (int).
        """
        per_trace = self.estimated_savings
        return {
            "token_savings_monthly": per_trace["token_savings"] * self.traces_per_month,
            "cost_savings_usd_monthly": round(
                per_trace["cost_savings_usd"] * self.traces_per_month, 2
            ),
            "time_savings_ms_monthly": round(
                per_trace["time_savings_ms"] * self.traces_per_month, 1
            ),
            "traces_per_month": self.traces_per_month,
        }

    # ------------------------------------------------------------------
    # Report generation
    # ------------------------------------------------------------------

    def generate_report(self) -> dict[str, Any]:
        """
        Generate a complete structured analysis report.

        Returns
        -------
        dict with keys:
            ``severity_score``, ``severity_level``, ``error_summary``,
            ``pattern_summary``, ``recommendations``, ``estimated_savings``,
            ``estimated_monthly_savings``, ``patterns_detail``.
        """
        score = self.severity_score
        if score >= 80:
            severity_level = "critical"
        elif score >= 60:
            severity_level = "high"
        elif score >= 40:
            severity_level = "medium"
        else:
            severity_level = "low"

        recommendations_objs = self._generate_recommendations()

        return {
            "severity_score": score,
            "severity_level": severity_level,
            "error_summary": self._generate_error_summary(),
            "pattern_summary": self._generate_pattern_summary(),
            # Keep backward-compatible plain-string list as well
            "recommendations": [r.title for r in recommendations_objs],
            "recommendations_detail": [r.to_dict() for r in recommendations_objs],
            "estimated_savings": self.estimated_savings,
            "estimated_monthly_savings": self.estimated_monthly_savings,
            "patterns_detail": [p.to_dict() for p in self.patterns],
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _generate_error_summary(self) -> str:
        """Build a human-readable error summary string."""
        error_count = self.trace.error_count
        total_spans = len(self.trace.spans)
        error_rate = self.trace.error_rate
        cascade_depth = self.dag.cascade_depth
        root_causes = len(self.dag.root_causes)

        if error_count == 0:
            return "Trace executed successfully with no errors."

        parts = [
            f"Detected {error_count}/{total_spans} error spans "
            f"(error rate {error_rate:.0%})"
        ]
        if root_causes > 0:
            parts.append(f"{root_causes} root cause(s)")
        if cascade_depth > 0:
            parts.append(f"max cascade depth {cascade_depth}")

        return "; ".join(parts) + "."

    def _generate_pattern_summary(self) -> list[str]:
        """Return one summary string per distinct PatternType found."""
        if not self.patterns:
            return ["No known patterns detected."]

        by_type: dict[PatternType, int] = {}
        for p in self.patterns:
            by_type[p.pattern_type] = by_type.get(p.pattern_type, 0) + 1

        return [
            f"Detected {count}x {ptype.value}"
            for ptype, count in by_type.items()
        ]

    def _generate_recommendations(self) -> list[Recommendation]:
        """
        Build a deduplicated list of :class:`Recommendation` objects ordered
        by severity (critical → warning → info).
        """
        recommendations: list[Recommendation] = []
        seen: set[str] = set()

        for pattern in self.patterns:
            rec = self._recommendation_for(pattern)
            if rec is None:
                continue
            dedup_key = f"{pattern.pattern_type.value}:{rec.title[:40]}"
            if dedup_key not in seen:
                recommendations.append(rec)
                seen.add(dedup_key)

        # Sort: critical first, then warning, then info
        _order = {"critical": 0, "warning": 1, "info": 2}
        recommendations.sort(key=lambda r: _order.get(r.severity, 3))

        return recommendations if recommendations else [
            Recommendation(
                pattern_type=PatternType.REDUNDANT_CALLS,  # placeholder
                title="No optimisation recommendations.",
                description="This trace looks healthy — no significant issues found.",
                severity="info",
            )
        ]

    def _recommendation_for(self, pattern: DetectedPattern) -> Recommendation | None:  # noqa: C901
        """Map a single :class:`DetectedPattern` to a :class:`Recommendation`."""
        ptype = pattern.pattern_type
        d = pattern.details

        if ptype == PatternType.RETRY_STORM:
            tool_name = d.get("tool_name", "unknown_tool")
            count = d.get("call_count", 0)
            return Recommendation(
                pattern_type=ptype,
                title=f"Add exponential back-off retry for '{tool_name}'",
                description=(
                    f"'{tool_name}' was called {count} times, indicating a retry "
                    f"storm. Limit retries to 3–5 attempts with exponential back-off "
                    f"and jitter to avoid overwhelming the downstream service."
                ),
                code_snippet=(
                    "import time, random\n"
                    "\n"
                    "def call_with_backoff(fn, max_retries=5):\n"
                    "    for attempt in range(max_retries):\n"
                    "        try:\n"
                    "            return fn()\n"
                    "        except Exception:\n"
                    "            if attempt == max_retries - 1:\n"
                    "                raise\n"
                    "            time.sleep((2 ** attempt) + random.random())\n"
                ),
                severity=pattern.severity,
                cost_impact_usd=round(count * 0.002, 4),
            )

        if ptype == PatternType.INFINITE_LOOP:
            cycle = d.get("cycle", [])
            repeats = d.get("repeat_count", 0)
            cycle_str = " → ".join(cycle)
            return Recommendation(
                pattern_type=ptype,
                title=f"Break the '{cycle_str}' infinite loop",
                description=(
                    f"The agent cycled through [{cycle_str}] {repeats} times. "
                    f"Add a loop-break condition such as a maximum iteration counter "
                    f"or state-change guard."
                ),
                code_snippet=(
                    "MAX_ITERATIONS = 10\n"
                    "iteration = 0\n"
                    "while not done and iteration < MAX_ITERATIONS:\n"
                    "    # ... agent loop body ...\n"
                    "    iteration += 1\n"
                    "    if state_unchanged(prev_state, current_state):\n"
                    "        break  # no progress — exit early\n"
                ),
                severity=pattern.severity,
                cost_impact_usd=round(repeats * 0.01, 4),
            )

        if ptype == PatternType.CONTEXT_OVERFLOW:
            model = d.get("model", "unknown_model")
            usage_ratio = d.get("usage_ratio", 0.95)
            tokens = d.get("total_tokens", 0)
            return Recommendation(
                pattern_type=ptype,
                title=f"Reduce context window usage for '{model}'",
                description=(
                    f"Token usage reached {usage_ratio:.0%} of the context limit "
                    f"({tokens:,} tokens). Summarise older conversation turns, use "
                    f"retrieval-augmented generation, or enable sliding-window "
                    f"truncation."
                ),
                code_snippet=(
                    "# Summarise older turns to free up context\n"
                    "def compress_history(messages, max_tokens=50_000):\n"
                    "    if token_count(messages) < max_tokens:\n"
                    "        return messages\n"
                    "    summary = llm.summarise(messages[:-10])\n"
                    "    return [{'role': 'system', 'content': summary}] + messages[-10:]\n"
                ),
                severity=pattern.severity,
                cost_impact_usd=round(tokens * 0.000003 * 0.2, 6),
            )

        if ptype == PatternType.TIMEOUT_CASCADE:
            timeout_span = d.get("timeout_span", "unknown")
            cascade_count = d.get("cascade_count", 0)
            return Recommendation(
                pattern_type=ptype,
                title=f"Add fallback handling for '{timeout_span}' timeouts",
                description=(
                    f"A timeout in '{timeout_span}' caused {cascade_count} downstream "
                    f"failures. Increase the timeout budget, add a circuit-breaker, or "
                    f"implement a fallback response."
                ),
                code_snippet=(
                    "import asyncio\n"
                    "\n"
                    "async def with_timeout_fallback(coro, timeout_s, fallback):\n"
                    "    try:\n"
                    "        return await asyncio.wait_for(coro, timeout=timeout_s)\n"
                    "    except asyncio.TimeoutError:\n"
                    "        return fallback\n"
                ),
                severity=pattern.severity,
                cost_impact_usd=round(cascade_count * 0.005, 4),
            )

        if ptype == PatternType.EMPTY_RESPONSE:
            return Recommendation(
                pattern_type=ptype,
                title="Fix prompt that causes empty LLM response",
                description=(
                    "An LLM returned 0 output tokens. This usually means the system "
                    "prompt is contradictory or the stop-sequence was triggered "
                    "prematurely. Review the prompt and ensure stop sequences are "
                    "appropriate."
                ),
                code_snippet=(
                    "# Validate LLM output before using it\n"
                    "response = llm.generate(prompt)\n"
                    "if not response or not response.strip():\n"
                    "    raise ValueError('LLM returned empty response — check your prompt')\n"
                ),
                severity=pattern.severity,
                cost_impact_usd=0.0,
            )

        if ptype == PatternType.HALLUCINATION_CASCADE:
            tool_span = d.get("tool_span", "unknown")
            return Recommendation(
                pattern_type=ptype,
                title=f"Add input validation for '{tool_span}'",
                description=(
                    f"'{tool_span}' failed after receiving LLM output as input. "
                    f"Validate LLM-generated parameters against a schema before "
                    f"passing them to tools."
                ),
                code_snippet=(
                    "from pydantic import BaseModel, ValidationError\n"
                    "\n"
                    "class ToolInput(BaseModel):\n"
                    "    query: str\n"
                    "    limit: int\n"
                    "\n"
                    "def safe_tool_call(raw_llm_output: dict):\n"
                    "    try:\n"
                    "        params = ToolInput(**raw_llm_output)\n"
                    "    except ValidationError as e:\n"
                    "        raise ValueError(f'Invalid LLM output: {e}')\n"
                    "    return tool(params.query, params.limit)\n"
                ),
                severity=pattern.severity,
                cost_impact_usd=0.005,
            )

        if ptype == PatternType.COST_SPIKE:
            llm_name = d.get("llm_name", "unknown")
            cost_usd = d.get("cost_usd", 0.0)
            cost_pct = d.get("cost_pct", 0.0)
            return Recommendation(
                pattern_type=ptype,
                title=f"Reduce input size for '{llm_name}' ({cost_pct:.0f}% of trace cost)",
                description=(
                    f"'{llm_name}' consumed ${cost_usd:.4f} — {cost_pct:.0f}% of "
                    f"the total trace cost. Shorten the system prompt, truncate "
                    f"retrieved context, or route to a cheaper model for this step."
                ),
                code_snippet=(
                    "# Route large-context calls to a cheaper model\n"
                    "model = 'claude-opus-4' if token_count < 10_000 else 'claude-haiku-4'\n"
                    "response = llm.generate(prompt, model=model)\n"
                ),
                severity=pattern.severity,
                cost_impact_usd=round(cost_usd * 0.3, 6),
            )

        if ptype == PatternType.SLOW_TOOL:
            tool_name = d.get("tool_name", "unknown")
            slowness = d.get("slowness_factor", 1.0)
            duration_ms = d.get("duration_ms", 0.0)
            return Recommendation(
                pattern_type=ptype,
                title=f"Optimise '{tool_name}' ({slowness:.1f}x slower than average)",
                description=(
                    f"'{tool_name}' took {duration_ms:.0f} ms — {slowness:.1f}x "
                    f"slower than its average. Add caching, pre-warm connections, or "
                    f"use a faster API endpoint."
                ),
                code_snippet=(
                    "import functools\n"
                    "\n"
                    "@functools.lru_cache(maxsize=256)\n"
                    "def cached_tool_call(query: str):\n"
                    "    return slow_external_api(query)\n"
                ),
                severity=pattern.severity,
                cost_impact_usd=0.001,
            )

        if ptype == PatternType.REDUNDANT_CALLS:
            tool_name = d.get("tool_name", "unknown")
            call_count = d.get("call_count", 2)
            return Recommendation(
                pattern_type=ptype,
                title=f"Cache results for '{tool_name}' (called {call_count}x with same args)",
                description=(
                    f"'{tool_name}' was called {call_count} times with identical "
                    f"arguments. Cache the result for the duration of the agent run "
                    f"to avoid redundant API calls and reduce cost."
                ),
                code_snippet=(
                    "_tool_cache: dict = {}\n"
                    "\n"
                    "def memoised_tool(query: str):\n"
                    "    if query not in _tool_cache:\n"
                    "        _tool_cache[query] = expensive_tool(query)\n"
                    "    return _tool_cache[query]\n"
                ),
                severity=pattern.severity,
                cost_impact_usd=round((call_count - 1) * 0.01, 4),
            )

        if ptype == PatternType.TOKEN_WASTE:
            span_name = d.get("span_name", "unknown")
            ratio = d.get("ratio", 0.0)
            input_tokens = d.get("input_tokens", 0)
            wasted_cost = d.get("wasted_cost_usd", 0.0)
            return Recommendation(
                pattern_type=ptype,
                title=f"Shorten prompt for '{span_name}' (input/output ratio {ratio:.0f}:1)",
                description=(
                    f"'{span_name}' used {input_tokens:,} input tokens but produced "
                    f"very few output tokens (ratio {ratio:.1f}:1). This suggests the "
                    f"prompt is oversized relative to the task. Consider trimming the "
                    f"system prompt, removing redundant context, or using a summarised "
                    f"representation.  Estimated wasted input cost: ${wasted_cost:.4f} "
                    f"per trace."
                ),
                code_snippet=(
                    "# Truncate retrieved context to the most relevant chunks\n"
                    "MAX_CONTEXT_TOKENS = 4_000\n"
                    "chunks = retrieve(query, top_k=20)\n"
                    "context = '\\n'.join(chunks)  # naive join\n"
                    "# Better: rank and truncate\n"
                    "context = truncate_to_tokens(\n"
                    "    '\\n'.join(rank_by_relevance(chunks, query)),\n"
                    "    max_tokens=MAX_CONTEXT_TOKENS,\n"
                    ")\n"
                ),
                severity=pattern.severity,
                cost_impact_usd=round(wasted_cost * 0.5, 6),
            )

        if ptype == PatternType.SEQUENTIAL_BOTTLENECK:
            tools = d.get("sequential_tool_names", [])
            savings_ms = d.get("potential_savings_ms", 0.0)
            tools_str = ", ".join(f"'{t}'" for t in tools[:4])
            return Recommendation(
                pattern_type=ptype,
                title=f"Parallelise independent tool calls ({tools_str}…)",
                description=(
                    f"{len(tools)} tool calls ({tools_str}) have no data dependency "
                    f"on each other but ran sequentially. Running them concurrently "
                    f"could save ~{savings_ms:.0f} ms per trace."
                ),
                code_snippet=(
                    "import asyncio\n"
                    "\n"
                    "async def parallel_tools():\n"
                    "    results = await asyncio.gather(\n"
                    + "".join(
                        f"        {t}(),\n" for t in (tools[:3] if tools else ["tool_a", "tool_b"])
                    )
                    + "    )\n"
                    "    return results\n"
                ),
                severity=pattern.severity,
                cost_impact_usd=0.0,  # latency saving, not direct cost saving
            )

        if ptype == PatternType.ERROR_RECOVERY:
            failed_name = d.get("failed_span_name", "unknown")
            overhead_ms = d.get("recovery_overhead_ms", 0.0)
            return Recommendation(
                pattern_type=ptype,
                title=f"Optimise recovery overhead for '{failed_name}' (positive pattern)",
                description=(
                    f"The agent successfully recovered from a '{failed_name}' failure "
                    f"— great resilience! The recovery added ~{overhead_ms:.0f} ms of "
                    f"overhead. Consider caching the successful response or using a "
                    f"faster fallback to reduce this overhead."
                ),
                code_snippet=(
                    "# Use a faster / cheaper model as a fallback\n"
                    "try:\n"
                    "    result = primary_tool(query)\n"
                    "except ToolError:\n"
                    "    result = fallback_tool(query)  # pre-warmed, cached, or cheaper\n"
                ),
                severity=pattern.severity,
                cost_impact_usd=0.0,
            )

        return None
