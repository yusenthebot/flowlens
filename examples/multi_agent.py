#!/usr/bin/env python3
"""
FlowLens Example — Multi-Agent Collaboration
==============================================
Demonstrates a four-agent pipeline where specialized agents collaborate
to research, write, and review a document. Shows parent-child span
relationships, realistic error handling (reviewer rejects → writer retries),
and full DAG analysis.

Agent pipeline:
  planner_agent   — decomposes task into subtasks  (@trace_agent)
    ├── research_agent — gathers information         (@trace_agent)
    │       ├── vector_search                        (@trace_retrieval)
    │       └── summarise_sources                   (@trace_llm)
    ├── writer_agent   — drafts the document         (@trace_agent)
    │       ├── draft_outline                        (@trace_llm)
    │       └── expand_sections                     (@trace_llm)
    ├── reviewer_agent — quality-gates the draft     (@trace_agent)
    │       ├── check_quality                        (@trace_tool)
    │       └── llm_review                          (@trace_llm)
    └── (retry) writer_agent re-writes on rejection

Shows: nested traces, error propagation, DAG analysis, pattern detection.

Run with:
    python3 examples/multi_agent.py
"""

import asyncio
import random
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flowlens import (
    FlowLens, trace_agent, trace_llm, trace_tool, trace_retrieval,
)
from flowlens.sdk.models import Trace
from flowlens.analysis.dag_builder import build_causal_dag
from flowlens.analysis.patterns import detect_patterns
from flowlens.analysis.advisor import TraceAdvisor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _utils import (
    c, banner, section, subsection, ok, err, info, warn, note,
    print_trace_tree, print_table, hbar,
    RESET, BOLD, DIM,
    BRIGHT_RED, BRIGHT_GREEN, BRIGHT_YELLOW, BRIGHT_BLUE,
    BRIGHT_MAGENTA, BRIGHT_CYAN, BRIGHT_WHITE, WHITE, GREEN, RED, YELLOW,
)

# ── Shared knowledge base (reused across agents) ─────────────────────────────
KNOWLEDGE_BASE = [
    {"id": "1", "title": "Multi-Agent Coordination Patterns",
     "content": "Orchestrator-subagent architectures use a planner to decompose tasks. "
                "Blackboard and message-passing are the two dominant coordination models."},
    {"id": "2", "title": "LLM Reliability Techniques",
     "content": "Chain-of-thought, self-consistency, and critique-revision loops improve "
                "output quality. Constitutional AI adds automated review steps."},
    {"id": "3", "title": "Document Generation Best Practices",
     "content": "Structured outlines reduce hallucination. Iterative refinement with "
                "human-in-the-loop review improves accuracy by 35%."},
    {"id": "4", "title": "Error Recovery in Agentic Systems",
     "content": "Retry with exponential backoff, fallback chains, and reviewer-gated "
                "outputs reduce cascade failures. Circuit breakers prevent retry storms."},
]

# ── Fake LLM response ────────────────────────────────────────────────────────
class FakeLLM:
    def __init__(self, text: str, inp: int, out: int):
        self.content = [type("B", (), {"text": text})()]
        self.usage = type("U", (), {"input_tokens": inp, "output_tokens": out})()
        self.stop_reason = "end_turn"

# ── Counters for simulating reject/retry ─────────────────────────────────────
_writer_attempt = 0
_reviewer_call = 0


# ─────────────────────────────────────────────────────────────────────────────
# Sub-agent helper functions (tools / llm calls used by the sub-agents)
# ─────────────────────────────────────────────────────────────────────────────

@trace_retrieval(name="vector_search")
async def vector_search(query: str) -> list[dict]:
    """Knowledge base retrieval — simulates ANN search."""
    await asyncio.sleep(random.uniform(0.02, 0.05))
    scored = []
    for doc in KNOWLEDGE_BASE:
        words = set(query.lower().split())
        hits  = sum(1 for w in words if w in doc["content"].lower())
        scored.append({**doc, "score": round(0.5 + hits * 0.1 + random.uniform(0, 0.15), 3)})
    scored.sort(key=lambda d: d["score"], reverse=True)
    return scored[:3]


@trace_llm(model="claude-haiku-4-20250514", name="summarise_sources")
async def summarise_sources(docs: list[dict], topic: str) -> FakeLLM:
    """Compact LLM call: summarise retrieved sources into bullet points."""
    await asyncio.sleep(random.uniform(0.03, 0.06))
    bullets = "\n".join(f"- {d['content'][:80]}…" for d in docs)
    return FakeLLM(
        f"Research summary for '{topic}':\n{bullets}",
        inp=random.randint(300, 600), out=random.randint(80, 150),
    )


@trace_llm(model="claude-sonnet-4-20250514", name="draft_outline")
async def draft_outline(topic: str, research: str) -> FakeLLM:
    """Generate a structured outline for the document."""
    await asyncio.sleep(random.uniform(0.04, 0.08))
    return FakeLLM(
        f"## Outline: {topic}\n"
        "1. Introduction\n2. Background\n3. Key Findings\n"
        "4. Implementation Guide\n5. Conclusion",
        inp=random.randint(400, 700), out=random.randint(100, 200),
    )


@trace_llm(model="claude-sonnet-4-20250514", name="expand_sections")
async def expand_sections(outline: str, research: str) -> FakeLLM:
    """Expand each outline section into full prose."""
    await asyncio.sleep(random.uniform(0.06, 0.12))
    return FakeLLM(
        "# Full Document Draft\n\n"
        "## Introduction\nThis document covers the state of the art in multi-agent AI.\n\n"
        "## Key Findings\nOrchestrator patterns and critique-revision loops are essential.\n\n"
        "## Conclusion\nProduction agents require observability tooling like FlowLens.",
        inp=random.randint(600, 1000), out=random.randint(250, 500),
    )


@trace_tool(name="quality_gate")
async def quality_gate(draft: str) -> dict:
    """
    Automated quality check: word count, keyword density, structure score.
    First call intentionally returns low quality to trigger a retry.
    """
    global _reviewer_call
    _reviewer_call += 1
    await asyncio.sleep(random.uniform(0.02, 0.04))

    word_count = len(draft.split())
    keywords = ["introduction", "findings", "conclusion", "agent", "llm", "observability"]
    keyword_hits = sum(1 for kw in keywords if kw.lower() in draft.lower())

    # First review: simulate a stricter threshold causing rejection
    if _reviewer_call == 1:
        return {
            "passed": False,
            "score": 0.42,
            "word_count": word_count,
            "keyword_hits": keyword_hits,
            "issues": [
                "Insufficient depth in Section 2 (Background)",
                "Missing citations for key claims",
                "Conclusion is too brief",
            ],
        }
    # Second review: draft was revised, now passes
    return {
        "passed": True,
        "score": 0.87,
        "word_count": word_count + 120,
        "keyword_hits": keyword_hits + 2,
        "issues": [],
    }


@trace_llm(model="claude-haiku-4-20250514", name="llm_review")
async def llm_review(draft: str, quality: dict) -> FakeLLM:
    """LLM-based review: generate structured feedback on the draft."""
    await asyncio.sleep(random.uniform(0.03, 0.07))
    if not quality["passed"]:
        issues_text = "; ".join(quality["issues"])
        return FakeLLM(
            f"REJECTED — Quality score {quality['score']:.2f}. Issues: {issues_text}. "
            "Please revise and resubmit.",
            inp=random.randint(300, 500), out=random.randint(60, 120),
        )
    return FakeLLM(
        f"APPROVED — Quality score {quality['score']:.2f}. "
        "Document meets all quality standards. Ready for publication.",
        inp=random.randint(300, 500), out=random.randint(60, 100),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Sub-agents
# ─────────────────────────────────────────────────────────────────────────────

@trace_agent(name="research_agent")
async def research_agent(topic: str) -> dict:
    """Retrieve and summarise knowledge base content for a given topic."""
    info(f"Research agent: gathering sources for {c(repr(topic), BRIGHT_YELLOW)}")
    docs = await vector_search(topic)
    ok(f"Retrieved {len(docs)} documents")
    for d in docs:
        bar = hbar(d["score"], 1.0, width=12, color=BRIGHT_GREEN)
        print(f"    {bar}  {c(d['score'], BRIGHT_GREEN)}  {c(d['title'], DIM)}")

    summary = await summarise_sources(docs, topic)
    ok("Sources summarised", f"{summary.usage.input_tokens} in / {summary.usage.output_tokens} out tok")
    return {"summary": summary.content[0].text, "doc_count": len(docs)}


@trace_agent(name="writer_agent")
async def writer_agent(topic: str, research: str, attempt: int) -> dict:
    """Draft a document given a topic and research summary."""
    global _writer_attempt
    _writer_attempt += 1
    label = "initial draft" if attempt == 1 else f"revision #{attempt}"
    info(f"Writer agent: creating {c(label, BRIGHT_YELLOW)} for {c(repr(topic), BRIGHT_YELLOW)}")

    outline_resp = await draft_outline(topic, research)
    ok("Outline drafted", f"{outline_resp.usage.output_tokens} out tok")

    draft_resp = await expand_sections(outline_resp.content[0].text, research)
    ok("Sections expanded", f"{draft_resp.usage.output_tokens} out tok")

    return {
        "draft": draft_resp.content[0].text,
        "attempt": attempt,
        "total_tokens": (
            outline_resp.usage.input_tokens + outline_resp.usage.output_tokens +
            draft_resp.usage.input_tokens + draft_resp.usage.output_tokens
        ),
    }


@trace_agent(name="reviewer_agent")
async def reviewer_agent(draft: str, attempt: int) -> dict:
    """Quality-gate the draft. Returns approved=True or raises for retry."""
    info(f"Reviewer agent: checking draft (attempt {attempt})")
    quality = await quality_gate(draft)
    review  = await llm_review(draft, quality)

    verdict = review.content[0].text
    if not quality["passed"]:
        warn(f"Draft REJECTED (score={quality['score']:.2f})")
        for issue in quality["issues"]:
            note(issue)
    else:
        ok(f"Draft APPROVED (score={quality['score']:.2f})")

    return {
        "passed":  quality["passed"],
        "score":   quality["score"],
        "verdict": verdict,
        "issues":  quality["issues"],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Planner (root orchestrator)
# ─────────────────────────────────────────────────────────────────────────────

@trace_agent(name="planner_agent")
async def planner_agent(task: str) -> dict:
    """
    Root orchestrator. Decomposes the task and coordinates sub-agents.
    Handles one rejection cycle: writer → reviewer (reject) → writer (retry) → reviewer (approve).
    """
    info(f"Planner: decomposing task: {c(repr(task), BRIGHT_YELLOW)}")

    # Phase 1: Research
    subsection("Phase 1 — Research")
    research_result = await research_agent(task)

    # Phase 2: Write (first attempt)
    subsection("Phase 2 — Writing (Attempt 1)")
    write_result = await writer_agent(task, research_result["summary"], attempt=1)

    # Phase 3: Review (first — will reject)
    subsection("Phase 3 — Review (Attempt 1)")
    review1 = await reviewer_agent(write_result["draft"], attempt=1)

    if not review1["passed"]:
        err("Reviewer rejected draft", f"score={review1['score']:.2f}")
        note("Planner: triggering revision cycle…")
        print()

        # Phase 4: Revise
        subsection("Phase 4 — Writing (Revision)")
        write_result = await writer_agent(task, research_result["summary"], attempt=2)

        # Phase 5: Re-review (will approve)
        subsection("Phase 5 — Review (Attempt 2)")
        review2 = await reviewer_agent(write_result["draft"], attempt=2)
        final_review = review2
    else:
        final_review = review1

    ok(f"Planner: task complete  approved={final_review['passed']}")
    return {
        "task":           task,
        "approved":       final_review["passed"],
        "review_score":   final_review["score"],
        "writer_attempts": write_result["attempt"],
        "research_docs":  research_result["doc_count"],
        "final_draft":    write_result["draft"],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Analysis & pretty report
# ─────────────────────────────────────────────────────────────────────────────

def print_dag_section(trace: Trace) -> None:
    """Print the causal DAG in human-readable form."""
    dag = build_causal_dag(trace)
    node_map = {n.span_id: n for n in dag.nodes}

    section("Causal DAG — Error Propagation")
    if not dag.root_causes:
        print(c("  No errors detected — all agents completed successfully.", BRIGHT_GREEN))
        return

    print(f"  Root causes    : {c(str(len(dag.root_causes)), BRIGHT_RED)}")
    for rc_id in dag.root_causes:
        rc = node_map.get(rc_id)
        if rc:
            print(f"    {c('●', BRIGHT_RED)} {c(rc.name, RED, BOLD)}")
            print(f"      {c(rc.error_message or '(unknown)', DIM)}")

    cascaded = [n for n in dag.nodes if n.error_role.value == "cascaded"]
    if cascaded:
        print()
        print(f"  Cascaded       : {c(str(len(cascaded)), BRIGHT_YELLOW)}")
        for node in cascaded:
            print(f"    {c('↳', YELLOW)} {c(node.name, YELLOW)}")

    if dag.edges:
        print()
        print(f"  Propagation:")
        for edge in dag.edges:
            src = node_map.get(edge.source_id)
            tgt = node_map.get(edge.target_id)
            if src and tgt:
                arrow = c(f"──[{edge.relation}]──▶", DIM)
                print(f"    {c(src.name, RED)}  {arrow}  {c(tgt.name, YELLOW)}")

    print(f"\n  Cascade depth  : {c(str(dag.cascade_depth), BRIGHT_YELLOW)}")


def print_pattern_section(trace: Trace) -> None:
    """Detect and print patterns from the trace."""
    dag      = build_causal_dag(trace)
    patterns = detect_patterns(trace, dag)
    advisor  = TraceAdvisor(trace=trace, dag=dag, patterns=patterns, traces_per_month=2000)
    report   = advisor.generate_report()

    section("Detected Patterns")
    if patterns:
        sev_icons  = {"critical": c("●", BRIGHT_RED), "warning": c("◆", BRIGHT_YELLOW), "info": c("○", BRIGHT_BLUE)}
        sev_colors = {"critical": BRIGHT_RED, "warning": BRIGHT_YELLOW, "info": BRIGHT_BLUE}
        for p in patterns:
            icon = sev_icons.get(p.severity, c("○", WHITE))
            col  = sev_colors.get(p.severity, WHITE)
            print(f"  {icon}  {c(f'[{p.severity.upper()}]', col, BOLD)}  {c(p.pattern_type.value, col)}")
            print(f"      {c(p.description, DIM)}")
            print()
    else:
        print(c("  No problematic patterns detected.", BRIGHT_GREEN))
        print()

    section("Savings Estimate (2,000 traces/mo)")
    savings = report["estimated_savings"]
    monthly = report["estimated_monthly_savings"]
    cost_s  = "${:.5f}".format(savings["cost_savings_usd"])
    cost_m  = "${:.2f}".format(monthly["cost_savings_usd_monthly"])
    tok_m   = "{:,}".format(monthly["token_savings_monthly"])
    print(f"  Per-trace token savings  : {c(str(savings['token_savings']), BRIGHT_CYAN)}")
    print(f"  Per-trace cost savings   : {c(cost_s, BRIGHT_GREEN)}")
    print(f"  Monthly cost savings     : {c(cost_m, BRIGHT_GREEN, BOLD)}")
    print(f"  Monthly token savings    : {c(tok_m, BRIGHT_CYAN)}")
    print()

    recs = report.get("recommendations_detail", [])
    if recs:
        section("Top Action Items")
        for i, rec in enumerate(recs[:4], 1):
            sev_col = BRIGHT_RED if rec["severity"] == "critical" else BRIGHT_YELLOW
            badge   = c("[{}]".format(rec["severity"].upper()), sev_col, BOLD)
            print(f"  {i}. {badge}  {c(rec['title'], BOLD)}")
            print(f"     {c(rec['description'][:115] + '…', DIM)}")
            print()


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

async def main() -> None:
    _traces: list[Trace] = []
    lens = FlowLens(
        service_name="multi-agent-demo",
        export_to="console",
        verbose=False,
        on_trace_complete=lambda t: _traces.append(t),
    )

    # Banner
    print(c("\n╔══════════════════════════════════════════════════════════════════════╗", BRIGHT_CYAN, BOLD))
    print(c("║         F L O W L E N S   —   Agent Observability Platform           ║", BRIGHT_CYAN, BOLD))
    print(c("║         Example: Multi-Agent Collaboration (plan → research →        ║", BRIGHT_CYAN, BOLD))
    print(c("║                  write → review → retry → approve)                   ║", BRIGHT_CYAN, BOLD))
    print(c("╚══════════════════════════════════════════════════════════════════════╝", BRIGHT_CYAN, BOLD))
    print()

    # Agent legend
    agents = [
        ("planner_agent",   BRIGHT_MAGENTA, "root orchestrator — decomposes task & coordinates"),
        ("research_agent",  BRIGHT_GREEN,   "retrieves & summarises knowledge base"),
        ("writer_agent",    BRIGHT_BLUE,    "drafts document (with retry on rejection)"),
        ("reviewer_agent",  BRIGHT_YELLOW,  "quality-gates output — first attempt rejects"),
    ]
    print(c("  Agent pipeline:", BRIGHT_WHITE, BOLD))
    for name, col, desc in agents:
        print(f"    {c('◈', col)}  {c(name, col, BOLD):<36}  {c(desc, DIM)}")
    print()

    # Run
    task = "Write a technical guide on multi-agent AI system design"
    section("Orchestration Execution")
    start = time.perf_counter()
    result = await planner_agent(task)
    elapsed_ms = (time.perf_counter() - start) * 1000

    print()
    ok(f"All agents complete in {elapsed_ms:.0f} ms", f"approved={result['approved']}")

    # Execution summary table
    section("Execution Summary")
    print_table(
        ["Metric", "Value"],
        [
            ["Task",              task[:55] + "…" if len(task) > 55 else task],
            ["Writer attempts",   str(result["writer_attempts"])],
            ["Research docs",     str(result["research_docs"])],
            ["Review score",      f"{result['review_score']:.2f}"],
            ["Status",            c("APPROVED", BRIGHT_GREEN) if result["approved"] else c("REJECTED", BRIGHT_RED)],
            ["Total latency",     f"{elapsed_ms:.0f} ms"],
        ],
        colors=[DIM, BRIGHT_WHITE],
    )

    # Final document preview
    section("Final Document Preview")
    for line in result["final_draft"].split("\n")[:8]:
        prefix = c("  │  ", DIM)
        print(f"{prefix}{c(line, BRIGHT_WHITE) if line.startswith('#') else c(line, WHITE)}")
    print(c("  │  …(truncated)", DIM))
    print()

    # Analysis
    if _traces:
        trace = _traces[0]
        section("Span Tree")
        print_trace_tree(trace)
        print_dag_section(trace)
        print_pattern_section(trace)

    lens.shutdown()
    print(c("  Done! Try: python3 examples/cost_optimizer.py", DIM))
    print()


if __name__ == "__main__":
    asyncio.run(main())
