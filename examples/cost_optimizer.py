#!/usr/bin/env python3
"""
FlowLens Example — Cost Optimiser
====================================
Runs multiple agent traces with different LLM model choices and uses the
FlowLens analysis engine to detect token waste and suggest concrete cost
optimisations.

What it demonstrates:
  - Running traces with claude-sonnet, gpt-4o, and gpt-4o-mini
  - Cost breakdown per model and per span
  - FlowLens pattern detection: cost_spike, context_overflow, retry_storm
  - TraceAdvisor recommendations with estimated monthly savings
  - Side-by-side model cost comparison table

Run with:
    python3 examples/cost_optimizer.py
"""

import asyncio
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flowlens import FlowLens, trace_agent, trace_llm, trace_retrieval
from flowlens.analysis.advisor import TraceAdvisor
from flowlens.analysis.dag_builder import build_causal_dag
from flowlens.analysis.patterns import detect_patterns
from flowlens.sdk.models import Trace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _utils import (
    BOLD,
    BRIGHT_BLUE,
    BRIGHT_CYAN,
    BRIGHT_GREEN,
    BRIGHT_RED,
    BRIGHT_WHITE,
    BRIGHT_YELLOW,
    DIM,
    WHITE,
    c,
    err,
    hbar,
    ok,
    print_table,
    print_trace_tree,
    section,
    subsection,
)


# ── Fake LLM response (Anthropic SDK shape) ───────────────────────────────────
class FakeLLM:
    def __init__(self, text: str, inp: int, out: int):
        self.content = [type("B", (), {"text": text})()]
        self.usage = type("U", (), {"input_tokens": inp, "output_tokens": out})()
        self.stop_reason = "end_turn"


# ─────────────────────────────────────────────────────────────────────────────
# Scenario A — Baseline (claude-sonnet, reasonable token budget)
# ─────────────────────────────────────────────────────────────────────────────


@trace_llm(model="claude-sonnet-4-20250514", name="planner_sonnet")
async def planner_sonnet(prompt: str) -> FakeLLM:
    await asyncio.sleep(random.uniform(0.03, 0.07))
    return FakeLLM(
        "Plan: Step 1 → Step 2 → Step 3", random.randint(400, 700), random.randint(80, 150)
    )


@trace_llm(model="claude-haiku-4-20250514", name="executor_haiku")
async def executor_haiku(plan: str) -> FakeLLM:
    await asyncio.sleep(random.uniform(0.02, 0.05))
    return FakeLLM("Execution complete.", random.randint(200, 400), random.randint(50, 100))


@trace_retrieval(name="kb_search")
async def kb_search(query: str) -> list[dict]:
    await asyncio.sleep(random.uniform(0.01, 0.03))
    return [{"id": f"doc_{i}", "score": random.uniform(0.7, 0.95)} for i in range(3)]


@trace_agent(name="baseline_agent")
async def baseline_agent(task: str) -> dict:
    """Efficient agent: uses haiku for execution, sonnet only for planning."""
    docs = await kb_search(task)
    plan_resp = await planner_sonnet(f"Plan for: {task}")
    exec_resp = await executor_haiku(plan_resp.content[0].text)
    return {"result": exec_resp.content[0].text, "docs": len(docs)}


# ─────────────────────────────────────────────────────────────────────────────
# Scenario B — Expensive: uses claude-opus for everything
# ─────────────────────────────────────────────────────────────────────────────


@trace_llm(model="claude-opus-4-20250514", name="planner_opus")
async def planner_opus(prompt: str) -> FakeLLM:
    await asyncio.sleep(random.uniform(0.05, 0.10))
    return FakeLLM(
        "Opus plan: Step 1 → Step 2 → Step 3", random.randint(600, 1000), random.randint(150, 250)
    )


@trace_llm(model="claude-opus-4-20250514", name="executor_opus")
async def executor_opus(plan: str) -> FakeLLM:
    await asyncio.sleep(random.uniform(0.05, 0.10))
    return FakeLLM("Opus execution complete.", random.randint(500, 900), random.randint(100, 200))


@trace_agent(name="expensive_agent")
async def expensive_agent(task: str) -> dict:
    """Expensive agent: uses claude-opus for both planning AND execution."""
    docs = await kb_search(task)
    plan_resp = await planner_opus(f"Plan for: {task}")
    exec_resp = await executor_opus(plan_resp.content[0].text)
    return {"result": exec_resp.content[0].text, "docs": len(docs)}


# ─────────────────────────────────────────────────────────────────────────────
# Scenario C — Context overflow: massive prompt stuffed into every call
# ─────────────────────────────────────────────────────────────────────────────


@trace_llm(model="claude-sonnet-4-20250514", name="bloated_planner")
async def bloated_planner(prompt: str) -> FakeLLM:
    """Sends the entire knowledge base as context every call — massive waste."""
    await asyncio.sleep(random.uniform(0.05, 0.10))
    # Simulate 150k input tokens — bloated context
    return FakeLLM("Plan with context.", inp=150_000, out=random.randint(100, 200))


@trace_llm(model="claude-sonnet-4-20250514", name="bloated_executor")
async def bloated_executor(plan: str) -> FakeLLM:
    await asyncio.sleep(random.uniform(0.03, 0.07))
    return FakeLLM("Execution done.", inp=80_000, out=random.randint(80, 150))


@trace_agent(name="context_overflow_agent")
async def context_overflow_agent(task: str) -> dict:
    """Bloated agent: stuffs entire knowledge base into every LLM call."""
    plan_resp = await bloated_planner(f"[FULL KB CONTEXT 150k tokens] Plan: {task}")
    exec_resp = await bloated_executor(plan_resp.content[0].text)
    return {"result": exec_resp.content[0].text}


# ─────────────────────────────────────────────────────────────────────────────
# Scenario D — gpt-4o comparison
# ─────────────────────────────────────────────────────────────────────────────


@trace_llm(model="gpt-4o", name="planner_gpt4o")
async def planner_gpt4o(prompt: str) -> FakeLLM:
    await asyncio.sleep(random.uniform(0.04, 0.08))
    return FakeLLM("GPT-4o plan.", random.randint(400, 700), random.randint(80, 150))


@trace_llm(model="gpt-4o-mini", name="executor_gpt4o_mini")
async def executor_gpt4o_mini(plan: str) -> FakeLLM:
    await asyncio.sleep(random.uniform(0.02, 0.04))
    return FakeLLM("Mini execution.", random.randint(200, 400), random.randint(50, 100))


@trace_agent(name="gpt4o_agent")
async def gpt4o_agent(task: str) -> dict:
    """Hybrid OpenAI: gpt-4o for planning, gpt-4o-mini for execution."""
    docs = await kb_search(task)
    plan_resp = await planner_gpt4o(f"Plan for: {task}")
    exec_resp = await executor_gpt4o_mini(plan_resp.content[0].text)
    return {"result": exec_resp.content[0].text, "docs": len(docs)}


# ─────────────────────────────────────────────────────────────────────────────
# Run all scenarios and collect traces
# ─────────────────────────────────────────────────────────────────────────────


async def run_all_scenarios(lens: FlowLens, task: str, traces: list) -> list[dict]:
    """Run each scenario 3 times and return timing + summary data."""
    results = []
    scenarios = [
        ("Baseline (sonnet+haiku)", baseline_agent, BRIGHT_GREEN),
        ("Expensive (opus+opus)", expensive_agent, BRIGHT_RED),
        ("Context overflow (sonnet)", context_overflow_agent, BRIGHT_YELLOW),
        ("GPT-4o (4o+4o-mini)", gpt4o_agent, BRIGHT_BLUE),
    ]

    for label, agent_fn, col in scenarios:
        subsection(label)
        run_costs = []
        run_tokens = []
        run_ms = []

        # Run scenario 3 times
        for run_i in range(3):
            t0 = time.perf_counter()
            try:
                await agent_fn(task)
            except Exception as exc:
                err(f"Run {run_i+1} failed: {exc}")
                continue
            elapsed = (time.perf_counter() - t0) * 1000

            if traces:
                last = traces[-1]
                run_costs.append(last.total_cost_usd)
                run_tokens.append(last.total_tokens)
                run_ms.append(elapsed)

        if run_costs:
            avg_cost = sum(run_costs) / len(run_costs)
            avg_tokens = int(sum(run_tokens) / len(run_tokens))
            avg_ms = sum(run_ms) / len(run_ms)
            ok(
                f"3 runs avg: {c(f'${avg_cost:.5f}', col)} cost | "
                f"{c(str(avg_tokens), col)} tokens | {c(f'{avg_ms:.0f}ms', col)} lat"
            )
            results.append(
                {
                    "label": label,
                    "color": col,
                    "avg_cost": avg_cost,
                    "avg_tokens": avg_tokens,
                    "avg_ms": avg_ms,
                }
            )

    return results


# ─────────────────────────────────────────────────────────────────────────────
# Model comparison table
# ─────────────────────────────────────────────────────────────────────────────


def print_cost_comparison(results: list[dict]) -> None:
    """Pretty-print the side-by-side cost table."""
    section("Model Cost Comparison")

    if not results:
        print(c("  No results to compare.", DIM))
        return

    max_cost = max(r["avg_cost"] for r in results) or 1.0
    best_cost = min(r["avg_cost"] for r in results)

    headers = ["Scenario", "Avg Cost/trace", "Avg Tokens", "Avg Latency", "vs Cheapest"]
    rows = []
    for r in results:
        ratio = r["avg_cost"] / best_cost if best_cost > 0 else 1.0
        ratio_str = (
            c("(baseline)", BRIGHT_GREEN) if ratio < 1.05 else c(f"+{ratio:.1f}x", BRIGHT_RED)
        )
        rows.append(
            [
                r["label"],
                c("${:.5f}".format(r["avg_cost"]), r["color"]),
                c(str(r["avg_tokens"]), BRIGHT_YELLOW),
                c("{:.0f} ms".format(r["avg_ms"]), BRIGHT_CYAN),
                ratio_str,
            ]
        )
    print_table(headers, rows, colors=[BRIGHT_WHITE, None, None, None, None])

    # Bar chart of relative cost
    print()
    print(c("  Relative cost (bar chart):", DIM))
    for r in results:
        bar = hbar(r["avg_cost"], max_cost, width=30, color=r["color"])
        label = r["label"][:28].ljust(28)
        cost_s = c("${:.5f}".format(r["avg_cost"]), r["color"])
        print(f"    {c(label, DIM)}  {bar}  {cost_s}")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# Analysis of the most expensive trace
# ─────────────────────────────────────────────────────────────────────────────


def print_worst_trace_analysis(traces: list[Trace]) -> None:
    """Find the most expensive trace and run full FlowLens analysis on it."""
    if not traces:
        return

    worst = max(traces, key=lambda t: t.total_cost_usd)
    section(f"Worst Trace Analysis — {worst.service_name} (${worst.total_cost_usd:.6f})")

    dag = build_causal_dag(worst)
    patterns = detect_patterns(worst, dag)
    advisor = TraceAdvisor(trace=worst, dag=dag, patterns=patterns, traces_per_month=50_000)
    report = advisor.generate_report()

    print_trace_tree(worst)

    score = report["severity_score"]
    score_col = BRIGHT_GREEN if score < 30 else BRIGHT_YELLOW if score < 60 else BRIGHT_RED
    level = report["severity_level"].upper()
    bar = hbar(score, 100, width=30, color=score_col)
    print(
        f"  Severity  {c(bar, score_col)}  {c(str(score) + '/100', score_col, BOLD)}  {c(level, score_col)}"
    )
    print()

    if patterns:
        section("Detected Waste Patterns")
        sev_icons = {
            "critical": c("●", BRIGHT_RED),
            "warning": c("◆", BRIGHT_YELLOW),
            "info": c("○", BRIGHT_BLUE),
        }
        sev_colors = {"critical": BRIGHT_RED, "warning": BRIGHT_YELLOW, "info": BRIGHT_BLUE}
        for p in patterns:
            icon = sev_icons.get(p.severity, c("○", WHITE))
            col = sev_colors.get(p.severity, WHITE)
            print(
                f"  {icon}  {c(f'[{p.severity.upper()}]', col, BOLD)}  {c(p.pattern_type.value, col)}"
            )
            print(f"      {c(p.description, DIM)}")
            print()

    section("Projected Savings (50k traces/mo)")
    savings = report["estimated_savings"]
    monthly = report["estimated_monthly_savings"]

    metrics = [
        ("Per-trace token savings", "{:,}".format(savings["token_savings"]), BRIGHT_CYAN),
        ("Per-trace cost savings", "${:.5f}".format(savings["cost_savings_usd"]), BRIGHT_GREEN),
        (
            "Per-trace latency savings",
            "{:.0f} ms".format(savings["time_savings_ms"]),
            BRIGHT_YELLOW,
        ),
        (
            "Monthly cost savings",
            "${:.2f}".format(monthly["cost_savings_usd_monthly"]),
            BRIGHT_GREEN,
        ),
        ("Monthly token savings", "{:,}".format(monthly["token_savings_monthly"]), BRIGHT_CYAN),
    ]
    for label, val, col in metrics:
        print(f"  {c(label + ':', DIM):<38}  {c(val, col, BOLD)}")
    print()

    recs = report.get("recommendations_detail", [])
    if recs:
        section("Optimisation Action Plan")
        for i, rec in enumerate(recs[:5], 1):
            sev_col = BRIGHT_RED if rec["severity"] == "critical" else BRIGHT_YELLOW
            badge = c("[{}]".format(rec["severity"].upper()), sev_col, BOLD)
            print(f"  {i}. {badge}  {c(rec['title'], BOLD)}")
            print(f"     {c(rec['description'][:120] + '…', DIM)}")
            if rec.get("code_snippet"):
                for line in rec["code_snippet"].strip().split("\n")[:3]:
                    print(f"       {c('│ ', DIM)}{c(line, BRIGHT_CYAN)}")
            print()


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────


async def main() -> None:
    _traces: list[Trace] = []
    lens = FlowLens(
        service_name="cost-optimizer-demo",
        export_to="console",
        verbose=False,
        on_trace_complete=lambda t: _traces.append(t),
    )

    # Banner
    print(
        c(
            "\n╔══════════════════════════════════════════════════════════════════════╗",
            BRIGHT_CYAN,
            BOLD,
        )
    )
    print(
        c(
            "║         F L O W L E N S   —   Agent Observability Platform           ║",
            BRIGHT_CYAN,
            BOLD,
        )
    )
    print(
        c(
            "║         Example: Cost Optimiser                                      ║",
            BRIGHT_CYAN,
            BOLD,
        )
    )
    print(
        c(
            "║         Compare models, detect waste, estimate savings               ║",
            BRIGHT_CYAN,
            BOLD,
        )
    )
    print(
        c(
            "╚══════════════════════════════════════════════════════════════════════╝",
            BRIGHT_CYAN,
            BOLD,
        )
    )
    print()
    print(c("  Scenarios:", BRIGHT_WHITE, BOLD))
    scenarios_info = [
        (BRIGHT_GREEN, "Baseline", "claude-sonnet (planning) + claude-haiku (execution)"),
        (BRIGHT_RED, "Expensive", "claude-opus for EVERYTHING — 5-10x cost"),
        (BRIGHT_YELLOW, "Context overflow", "150k token prompts sent on every LLM call"),
        (BRIGHT_BLUE, "GPT-4o hybrid", "gpt-4o (planning) + gpt-4o-mini (execution)"),
    ]
    for col, name, desc in scenarios_info:
        print(f"    {c('▸', col)}  {c(name, col, BOLD):<22}  {c(desc, DIM)}")
    print()

    task = "Research and summarise the latest developments in AI agent frameworks"
    section("Running All Scenarios (3 runs each)")
    results = await run_all_scenarios(lens, task, _traces)

    print_cost_comparison(results)

    if _traces:
        print_worst_trace_analysis(_traces)

    # Final headline summary
    section("Summary: Cost Optimisation Opportunities")
    if results and len(results) >= 2:
        cheapest = min(results, key=lambda r: r["avg_cost"])
        expensive = max(results, key=lambda r: r["avg_cost"])
        ratio = expensive["avg_cost"] / cheapest["avg_cost"] if cheapest["avg_cost"] > 0 else 1
        monthly_waste = (expensive["avg_cost"] - cheapest["avg_cost"]) * 50_000
        print(f"  {c('Cheapest scenario:', DIM)}  {c(cheapest['label'], BRIGHT_GREEN, BOLD)}")
        print(f"  {c('Costliest scenario:', DIM)} {c(expensive['label'], BRIGHT_RED, BOLD)}")
        print(
            f"  {c('Cost ratio:', DIM)}          {c(f'{ratio:.1f}x', BRIGHT_RED, BOLD)} more expensive"
        )
        print(
            f"  {c('Monthly waste (50k):', DIM)} {c(f'${monthly_waste:.2f}/mo', BRIGHT_RED, BOLD)}"
        )
        print()
        print(c("  Recommendation:", BRIGHT_WHITE, BOLD))
        print(
            f"    Use {c(cheapest['label'], BRIGHT_GREEN, BOLD)} as your baseline model strategy."
        )
        print("    Reserve claude-opus / gpt-4o for high-stakes generation only.")
        print("    Implement RAG with chunked context instead of full KB injection.")
        print()

    lens.shutdown()
    print(c("  Done! Try: python3 examples/live_dashboard.py", DIM))
    print()


if __name__ == "__main__":
    asyncio.run(main())
