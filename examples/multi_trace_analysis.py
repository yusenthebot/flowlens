#!/usr/bin/env python3
"""
FlowLens Multi-Trace Correlation Analysis
==========================================
Generates 12 synthetic traces with varying quality (healthy, degraded, and
broken), runs the FlowLens correlator to find systemic issues, and displays a
rich correlation report in both human-readable and JSON formats.

Run with:
    python examples/multi_trace_analysis.py

What this demonstrates:
  - Generating diverse traces programmatically
  - correlate_traces() to find cross-trace systemic issues
  - RecurringFailure detection (errors that appear in many traces)
  - PerformanceTrend detection (latency/token/cost drifts)
  - CommonAntiPattern detection (patterns that recur across traces)
  - Exporting the correlation report as JSON
"""

import asyncio
import json
import random
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flowlens.sdk.models import Trace, Span, SpanKind, SpanStatus
from flowlens.analysis.correlator import correlate_traces, CorrelationReport

# ───────────────────────────────────────────────────────────────────────────
# ANSI helpers
# ───────────────────────────────────────────────────────────────────────────

RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RED    = "\033[91m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
BLUE   = "\033[94m"
CYAN   = "\033[96m"
WHITE  = "\033[97m"
MAGENTA = "\033[95m"


def c(text: str, *codes: str) -> str:
    return "".join(codes) + str(text) + RESET


def banner(title: str) -> None:
    width = 72
    pad = (width - len(title) - 4) // 2
    print()
    print(c("╔" + "═" * (width - 2) + "╗", CYAN, BOLD))
    print(c(f"║{' ' * pad}  {title}  {' ' * pad}║", CYAN, BOLD))
    print(c("╚" + "═" * (width - 2) + "╝", CYAN, BOLD))
    print()


def section(title: str) -> None:
    print()
    print(c(f"  ── {title} " + "─" * (60 - len(title)), CYAN))
    print()


def row(label: str, value: str, value_color: str = WHITE) -> None:
    print(f"  {c(label + ':', DIM):<36}  {c(value, value_color)}")


def hbar(value: float, max_val: float, width: int = 30, color: str = GREEN) -> str:
    filled = int((value / max_val) * width) if max_val > 0 else 0
    bar = "█" * filled + "░" * (width - filled)
    return c(bar, color)


# ───────────────────────────────────────────────────────────────────────────
# Trace factory helpers
# ───────────────────────────────────────────────────────────────────────────

def _make_span(
    name: str,
    kind: SpanKind,
    duration_ms: float,
    status: SpanStatus = SpanStatus.OK,
    error_message: str = "",
    input_tokens: int = 0,
    output_tokens: int = 0,
    model: str = "",
    parent_span_id: str = "",
    trace_id: str = "",
) -> Span:
    """Build a finished Span without needing the full decorator machinery."""
    span = Span(
        name=name,
        kind=kind,
        status=status,
        trace_id=trace_id,
        parent_span_id=parent_span_id or None,
    )
    if error_message:
        span.error_message = error_message
        span.error_type = "SimulatedError"
    span.end_time = span.start_time + (duration_ms / 1000)

    if input_tokens or output_tokens:
        span.set_token_usage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=model,
        )
        span.attributes["gen_ai.usage.input_tokens"] = input_tokens
        span.attributes["gen_ai.usage.output_tokens"] = output_tokens
        span.attributes["gen_ai.request.model"] = model

    return span


def _finish_trace(trace: Trace, extra_ms: float = 0.0) -> Trace:
    """Mark a trace as finished."""
    trace.end_time = trace.start_time + sum(
        s.duration_ms / 1000 for s in trace.spans
    ) + extra_ms / 1000
    return trace


# ───────────────────────────────────────────────────────────────────────────
# Scenario builders — each returns a Trace object
# ───────────────────────────────────────────────────────────────────────────

def _healthy_trace(index: int, label: str = "healthy") -> Trace:
    """A fully healthy agent run — no errors, reasonable latency."""
    trace = Trace(service_name="research-agent", metadata={"scenario": label, "index": index})

    agent_span = _make_span(
        "research_agent", SpanKind.AGENT, duration_ms=300 + index * 10,
        trace_id=trace.trace_id,
    )
    trace.spans.append(agent_span)
    trace.root_span_id = agent_span.span_id

    trace.spans.append(_make_span(
        "research_planner", SpanKind.LLM, duration_ms=80,
        input_tokens=900 + index * 20, output_tokens=220,
        model="claude-sonnet-4-20250514",
        parent_span_id=agent_span.span_id, trace_id=trace.trace_id,
    ))
    trace.spans.append(_make_span(
        "vector_search", SpanKind.RETRIEVAL, duration_ms=40,
        parent_span_id=agent_span.span_id, trace_id=trace.trace_id,
    ))
    trace.spans.append(_make_span(
        "web_search", SpanKind.TOOL, duration_ms=90,
        parent_span_id=agent_span.span_id, trace_id=trace.trace_id,
    ))
    trace.spans.append(_make_span(
        "content_synthesiser", SpanKind.LLM, duration_ms=100,
        input_tokens=1500, output_tokens=350,
        model="claude-haiku-4-20250514",
        parent_span_id=agent_span.span_id, trace_id=trace.trace_id,
    ))

    return _finish_trace(trace)


def _timeout_cascade_trace(index: int) -> Trace:
    """Web search times out → fetch_page gets an invalid URL → cascade failure."""
    trace = Trace(service_name="research-agent", metadata={"scenario": "timeout_cascade", "index": index})

    agent_span = _make_span(
        "research_agent", SpanKind.AGENT, duration_ms=450,
        trace_id=trace.trace_id,
    )
    trace.spans.append(agent_span)
    trace.root_span_id = agent_span.span_id

    trace.spans.append(_make_span(
        "research_planner", SpanKind.LLM, duration_ms=85,
        input_tokens=950, output_tokens=210,
        model="claude-sonnet-4-20250514",
        parent_span_id=agent_span.span_id, trace_id=trace.trace_id,
    ))
    # Root cause: timeout
    trace.spans.append(_make_span(
        "web_search", SpanKind.TOOL, duration_ms=30_000,
        status=SpanStatus.ERROR,
        error_message="web_search timed out after 30s for query='agentic AI 2026'",
        parent_span_id=agent_span.span_id, trace_id=trace.trace_id,
    ))
    # Cascade: fetch_page received empty URL from failed search
    trace.spans.append(_make_span(
        "fetch_page", SpanKind.TOOL, duration_ms=5,
        status=SpanStatus.ERROR,
        error_message="fetch_page received invalid URL '' — likely from failed upstream search",
        parent_span_id=agent_span.span_id, trace_id=trace.trace_id,
    ))

    return _finish_trace(trace)


def _retry_storm_trace(index: int) -> Trace:
    """web_search is called 8 times — a retry storm."""
    trace = Trace(service_name="research-agent", metadata={"scenario": "retry_storm", "index": index})

    agent_span = _make_span(
        "research_agent", SpanKind.AGENT, duration_ms=900,
        trace_id=trace.trace_id,
    )
    trace.spans.append(agent_span)
    trace.root_span_id = agent_span.span_id

    trace.spans.append(_make_span(
        "research_planner", SpanKind.LLM, duration_ms=80,
        input_tokens=900, output_tokens=200,
        model="claude-sonnet-4-20250514",
        parent_span_id=agent_span.span_id, trace_id=trace.trace_id,
    ))
    # 8 calls to the same tool = retry storm
    for i in range(8):
        trace.spans.append(_make_span(
            "web_search", SpanKind.TOOL, duration_ms=30 + i * 5,
            status=SpanStatus.ERROR if i < 7 else SpanStatus.OK,
            error_message="Connection refused" if i < 7 else "",
            parent_span_id=agent_span.span_id, trace_id=trace.trace_id,
        ))

    return _finish_trace(trace)


def _context_overflow_trace(index: int) -> Trace:
    """LLM receives a massive context — approaching the model limit."""
    trace = Trace(service_name="research-agent", metadata={"scenario": "context_overflow", "index": index})

    agent_span = _make_span(
        "research_agent", SpanKind.AGENT, duration_ms=600,
        trace_id=trace.trace_id,
    )
    trace.spans.append(agent_span)
    trace.root_span_id = agent_span.span_id

    # Massive input — 190k tokens for a 200k context model
    trace.spans.append(_make_span(
        "research_planner", SpanKind.LLM, duration_ms=500,
        input_tokens=190_000, output_tokens=180,
        model="claude-sonnet-4-20250514",
        parent_span_id=agent_span.span_id, trace_id=trace.trace_id,
    ))
    trace.spans.append(_make_span(
        "vector_search", SpanKind.RETRIEVAL, duration_ms=45,
        parent_span_id=agent_span.span_id, trace_id=trace.trace_id,
    ))

    return _finish_trace(trace)


def _cost_spike_trace(index: int) -> Trace:
    """One LLM span consumes disproportionate tokens — cost spike."""
    trace = Trace(service_name="research-agent", metadata={"scenario": "cost_spike", "index": index})

    agent_span = _make_span(
        "research_agent", SpanKind.AGENT, duration_ms=700,
        trace_id=trace.trace_id,
    )
    trace.spans.append(agent_span)
    trace.root_span_id = agent_span.span_id

    # Normal call
    trace.spans.append(_make_span(
        "research_planner", SpanKind.LLM, duration_ms=80,
        input_tokens=900, output_tokens=220,
        model="claude-sonnet-4-20250514",
        parent_span_id=agent_span.span_id, trace_id=trace.trace_id,
    ))
    # Massive cost spike call using expensive model
    trace.spans.append(_make_span(
        "content_synthesiser", SpanKind.LLM, duration_ms=600,
        input_tokens=80_000, output_tokens=5_000,
        model="claude-opus-4-20250514",
        parent_span_id=agent_span.span_id, trace_id=trace.trace_id,
    ))

    return _finish_trace(trace)


def _degraded_latency_trace(index: int, multiplier: float = 1.0) -> Trace:
    """A trace with progressively increasing latency — simulates degradation."""
    trace = Trace(service_name="research-agent", metadata={"scenario": "degraded", "index": index})
    base_duration = 300 * multiplier

    agent_span = _make_span(
        "research_agent", SpanKind.AGENT, duration_ms=base_duration,
        trace_id=trace.trace_id,
    )
    trace.spans.append(agent_span)
    trace.root_span_id = agent_span.span_id

    trace.spans.append(_make_span(
        "research_planner", SpanKind.LLM, duration_ms=80 * multiplier,
        input_tokens=int(900 * multiplier), output_tokens=220,
        model="claude-sonnet-4-20250514",
        parent_span_id=agent_span.span_id, trace_id=trace.trace_id,
    ))
    trace.spans.append(_make_span(
        "vector_search", SpanKind.RETRIEVAL, duration_ms=40 * multiplier,
        parent_span_id=agent_span.span_id, trace_id=trace.trace_id,
    ))
    trace.spans.append(_make_span(
        "web_search", SpanKind.TOOL, duration_ms=90 * multiplier,
        parent_span_id=agent_span.span_id, trace_id=trace.trace_id,
    ))

    return _finish_trace(trace)


# ───────────────────────────────────────────────────────────────────────────
# Build the full trace set
# ───────────────────────────────────────────────────────────────────────────

def build_trace_set() -> list[Trace]:
    """
    Generate 12 traces representing a realistic mix:
      - 3 healthy runs
      - 3 timeout-cascade failures (same recurring error)
      - 2 retry storm failures
      - 1 context overflow
      - 1 cost spike
      - 2 degraded latency (progressively slower — trend detection)
    """
    traces: list[Trace] = []

    # Healthy baseline traces
    for i in range(3):
        traces.append(_healthy_trace(i, label="healthy"))

    # Timeout cascade — recurring failure (same error string in 3/12 traces)
    for i in range(3):
        traces.append(_timeout_cascade_trace(i))

    # Retry storm — recurring anti-pattern
    for i in range(2):
        traces.append(_retry_storm_trace(i))

    # Context overflow
    traces.append(_context_overflow_trace(0))

    # Cost spike
    traces.append(_cost_spike_trace(0))

    # Degraded latency trend — multiplier increases 1.0 → 1.5 → 2.5
    # enough consecutive increase to trip the monotonic trend detector
    for mult in [1.0, 1.5, 2.5]:
        traces.append(_degraded_latency_trace(int(mult * 10), multiplier=mult))

    return traces


# ───────────────────────────────────────────────────────────────────────────
# Pretty-print the correlation report
# ───────────────────────────────────────────────────────────────────────────

def print_report(report: CorrelationReport, traces: list[Trace]) -> None:
    """Render the CorrelationReport in a colourful terminal layout."""

    banner("FlowLens Multi-Trace Correlation Report")

    # ── Fleet Overview ────────────────────────────────────────────────────
    section("Fleet Overview")
    total = report.total_traces
    err_pct = report.overall_error_rate * 100

    row("Total traces analysed", str(total), CYAN)
    row("Overall error rate",
        f"{err_pct:.1f}%  [{int(err_pct / 100 * total)}/{total} traces]",
        RED if err_pct > 30 else YELLOW if err_pct > 10 else GREEN)
    row("Avg duration", f"{report.avg_duration_ms:.1f} ms", CYAN)
    row("Avg total tokens", f"{report.avg_total_tokens:,.0f}", YELLOW)
    row("Avg total cost", f"${report.avg_total_cost_usd:.5f}", YELLOW)

    # Scenario distribution
    scenarios: dict[str, int] = {}
    for t in traces:
        s = t.metadata.get("scenario", "unknown")
        scenarios[s] = scenarios.get(s, 0) + 1

    print()
    print(f"  {c('Scenario distribution:', DIM)}")
    max_count = max(scenarios.values()) if scenarios else 1
    for scenario, count in sorted(scenarios.items(), key=lambda x: -x[1]):
        bar = hbar(count, max_count, width=20, color=CYAN)
        color = RED if "timeout" in scenario or "retry" in scenario or "cost" in scenario or "context" in scenario else GREEN if scenario == "healthy" else YELLOW
        print(f"    {c(scenario + ':',DIM):<28}  {bar}  {c(str(count), color)}")

    # ── Recurring Failures ────────────────────────────────────────────────
    section("Recurring Failures")

    if not report.recurring_failures:
        print(c("  No recurring failures detected (error rate too low or varied).", GREEN))
    else:
        for i, rf in enumerate(report.recurring_failures, 1):
            rate_pct = rf.occurrence_rate * 100
            color = RED if rate_pct >= 70 else YELLOW
            print(c(f"  [{i}] {rf.error_message[:80]}", color, BOLD))
            print(f"      Rate    : {c(f'{rate_pct:.0f}%', color)}  ({rf.occurrence_count}/{rf.total_traces} traces)")
            print(f"      Spans   : {c(', '.join(dict.fromkeys(rf.affected_span_names))[:80], DIM)}")
            print(f"      Traces  : {c(', '.join(t[:12] for t in rf.affected_trace_ids[:3]) + '...', DIM)}")
            print()

    # ── Performance Trends ────────────────────────────────────────────────
    section("Performance Trends (Monotonic Degradation)")

    if not report.performance_trends:
        print(c("  No monotonic performance trends detected.", GREEN))
    else:
        for trend in report.performance_trends:
            dir_color = RED if trend.direction == "increasing" else GREEN
            dir_sym = "↑" if trend.direction == "increasing" else "↓"
            print(f"  {c(dir_sym, dir_color, BOLD)}  {c(trend.metric, WHITE, BOLD)}")
            print(f"     Direction : {c(trend.direction.upper(), dir_color)}")
            print(f"     Slope     : {c(f'{trend.slope:+.2f} per trace step', dir_color)}")
            print(f"     Values    : ", end="")

            max_v = max(trend.values) if trend.values else 1
            for v in trend.values:
                bar_len = max(1, int((v / max_v) * 10))
                print(c("▐" * bar_len, dir_color), end="  ")
            print()
            print(f"     ({', '.join(f'{v:.0f}' for v in trend.values)})")
            print()

    # ── Common Anti-Patterns ──────────────────────────────────────────────
    section("Common Anti-Patterns Across Fleet")

    if not report.common_anti_patterns:
        print(c("  No common anti-patterns detected at threshold.", GREEN))
    else:
        for ap in report.common_anti_patterns:
            rate_pct = ap.occurrence_rate * 100
            bar = hbar(rate_pct, 100, width=20, color=RED if rate_pct >= 70 else YELLOW)
            print(f"  {c(ap.pattern_type.value, RED if rate_pct >= 70 else YELLOW, BOLD)}")
            print(f"     Occurrence  :  {bar}  {c(f'{rate_pct:.0f}%', RED if rate_pct >= 70 else YELLOW)}")
            print(f"     Count       :  {ap.occurrence_count}/{ap.total_traces} traces")
            print()

    # ── Summary Text ─────────────────────────────────────────────────────
    section("Executive Summary")
    for line in report.summary().split("\n"):
        print(f"  {line}")

    # ── Actionable Recommendations ────────────────────────────────────────
    section("Systemic Recommendations")

    recs: list[str] = []

    if report.recurring_failures:
        top = report.recurring_failures[0]
        recs.append(
            f"[CRITICAL] Fix the root cause of '{top.affected_span_names[0] if top.affected_span_names else 'unknown'}': "
            f"'{top.error_message[:60]}' — affects {top.occurrence_rate:.0%} of all traces."
        )

    if report.performance_trends:
        for trend in report.performance_trends:
            recs.append(
                f"[WARNING] {trend.metric} is {trend.direction} at +{trend.slope:.1f} per trace. "
                "Investigate for memory leaks, prompt growth, or infrastructure degradation."
            )

    for ap in report.common_anti_patterns:
        if ap.pattern_type.value == "retry_storm":
            recs.append(
                "[WARNING] retry_storm detected in a majority of traces. "
                "Add exponential backoff with jitter and circuit breakers."
            )
        elif ap.pattern_type.value == "context_overflow":
            recs.append(
                "[WARNING] context_overflow is systemic. "
                "Implement RAG with shorter context windows or sliding-window summarisation."
            )
        elif ap.pattern_type.value == "cost_spike":
            recs.append(
                "[WARNING] cost_spike is systemic. "
                "Route large-context calls to a cheaper model tier."
            )

    if not recs:
        recs.append("[INFO] No systemic issues found — fleet health looks good.")

    for rec in recs:
        icon = c("●", RED) if "CRITICAL" in rec else c("◆", YELLOW) if "WARNING" in rec else c("○", BLUE)
        print(f"  {icon}  {rec}")

    print()
    print(c("═" * 72, CYAN))
    print()


# ───────────────────────────────────────────────────────────────────────────
# JSON export
# ───────────────────────────────────────────────────────────────────────────

def export_json(report: CorrelationReport, path: str = "/tmp/flowlens_correlation_report.json") -> str:
    """Serialise the CorrelationReport to a JSON file and return the path."""
    data = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "tool": "FlowLens multi-trace correlator",
        "report": report.to_dict(),
    }
    with open(path, "w") as fh:
        json.dump(data, fh, indent=2)
    return path


# ───────────────────────────────────────────────────────────────────────────
# Main
# ───────────────────────────────────────────────────────────────────────────

def main() -> None:
    banner("FlowLens — Multi-Trace Correlation Analysis")

    # ── Step 1: Generate traces ───────────────────────────────────────────
    section("Generating Synthetic Trace Set")
    traces = build_trace_set()

    print(f"  Generated {c(str(len(traces)), CYAN, BOLD)} traces:")
    scenario_counts: dict[str, int] = {}
    for t in traces:
        s = t.metadata.get("scenario", "?")
        scenario_counts[s] = scenario_counts.get(s, 0) + 1

    for scenario, count in sorted(scenario_counts.items(), key=lambda x: -x[1]):
        color = GREEN if scenario == "healthy" else RED if "timeout" in scenario or "retry" in scenario else YELLOW
        print(f"    {c('▸', color)}  {scenario:<25}  {c(str(count) + ' trace(s)', color)}")

    # ── Step 2: Correlate ─────────────────────────────────────────────────
    section("Running Correlator")
    print(f"  {c('correlate_traces(traces, failure_threshold=0.2, anti_pattern_threshold=0.15)', DIM)}")
    print()

    t0 = time.perf_counter()
    report = correlate_traces(
        traces,
        failure_threshold=0.20,       # report errors in > 20% of traces
        anti_pattern_threshold=0.15,  # report patterns in > 15% of traces
        trend_min_traces=3,           # need at least 3 traces for trend detection
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000

    print(f"  {c('✓', GREEN)} Correlation completed in {elapsed_ms:.1f}ms")
    print(f"    Recurring failures   : {c(str(len(report.recurring_failures)), RED if report.recurring_failures else GREEN)}")
    print(f"    Performance trends   : {c(str(len(report.performance_trends)), YELLOW if report.performance_trends else GREEN)}")
    print(f"    Common anti-patterns : {c(str(len(report.common_anti_patterns)), YELLOW if report.common_anti_patterns else GREEN)}")

    # ── Step 3: Pretty print report ───────────────────────────────────────
    print_report(report, traces)

    # ── Step 4: JSON export ───────────────────────────────────────────────
    section("JSON Export")
    json_path = export_json(report)
    print(f"  {c('✓', GREEN)} Report exported to: {c(json_path, CYAN)}")
    print()

    # Show a snippet of the JSON
    data = report.to_dict()
    print(c("  JSON structure preview:", DIM))
    snippet = json.dumps(
        {k: v for k, v in data.items() if k in ("total_traces", "overall_error_rate", "avg_duration_ms", "avg_total_cost_usd")},
        indent=4,
    )
    for line in snippet.split("\n"):
        print(f"    {c(line, CYAN)}")

    if data.get("recurring_failures"):
        rf_snippet = json.dumps(data["recurring_failures"][0], indent=4)
        print(f"    {c('...', DIM)}")
        print(c("  First recurring_failure:", DIM))
        for line in rf_snippet.split("\n")[:10]:
            print(f"    {c(line, YELLOW)}")
        print(f"    {c('...', DIM)}")

    print()
    print(c("  Done! Load the full JSON in any BI tool, Jupyter notebook, or FlowLens dashboard.", DIM))
    print()


if __name__ == "__main__":
    main()
