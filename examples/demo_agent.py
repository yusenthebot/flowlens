#!/usr/bin/env python3
"""
FlowLens Demo — Multi-Step Research Agent with RAG Pipeline

A fully realistic simulation of an agentic AI workflow demonstrating all five
FlowLens decorator types in action. The agent performs research using a
retrieval-augmented pipeline, encounters realistic failures, recovers, and
produces a full observability report.

Run with:
    python examples/demo_agent.py

What this demonstrates:
  @trace_agent     — the outer agent orchestration loop
  @trace_llm       — LLM planning and summarisation calls
  @trace_tool      — external tool (search, fetch, validator)
  @trace_chain     — multi-step processing pipeline
  @trace_retrieval — vector similarity search (RAG step)
"""

import asyncio
import random
import sys
import os
import time

# Make runnable from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flowlens import (
    FlowLens,
    trace_agent,
    trace_tool,
    trace_llm,
    trace_chain,
    trace_retrieval,
)
from flowlens.sdk.models import Trace
from flowlens.analysis.dag_builder import build_causal_dag
from flowlens.analysis.patterns import detect_patterns
from flowlens.analysis.advisor import TraceAdvisor

# ===== ANSI colour helpers =====

RESET   = "\033[0m"
BOLD    = "\033[1m"
DIM     = "\033[2m"

BLACK   = "\033[30m"
RED     = "\033[31m"
GREEN   = "\033[32m"
YELLOW  = "\033[33m"
BLUE    = "\033[34m"
MAGENTA = "\033[35m"
CYAN    = "\033[36m"
WHITE   = "\033[37m"

BRIGHT_RED     = "\033[91m"
BRIGHT_GREEN   = "\033[92m"
BRIGHT_YELLOW  = "\033[93m"
BRIGHT_BLUE    = "\033[94m"
BRIGHT_MAGENTA = "\033[95m"
BRIGHT_CYAN    = "\033[96m"
BRIGHT_WHITE   = "\033[97m"

BG_BLUE    = "\033[44m"
BG_MAGENTA = "\033[45m"
BG_CYAN    = "\033[46m"


def _color(text: str, *codes: str) -> str:
    """Wrap text with ANSI codes, reset at end."""
    return "".join(codes) + text + RESET


def _bar(filled: int, total: int = 20, fill_char: str = "█", empty_char: str = "░") -> str:
    """Render a simple progress bar string."""
    n = int(filled / total * total)
    return fill_char * n + empty_char * (total - n)


def _section(title: str, width: int = 72) -> None:
    """Print a coloured section header."""
    pad = width - len(title) - 4
    left = pad // 2
    right = pad - left
    print()
    print(_color("┌" + "─" * (width - 2) + "┐", BRIGHT_CYAN, BOLD))
    print(_color("│" + " " * left + "  " + title + "  " + " " * right + "│", BRIGHT_CYAN, BOLD))
    print(_color("└" + "─" * (width - 2) + "┘", BRIGHT_CYAN, BOLD))


def _subsection(title: str) -> None:
    print()
    print(_color(f"  ▶ {title}", BRIGHT_YELLOW, BOLD))
    print(_color("  " + "─" * 60, DIM))


def _step(icon: str, text: str, detail: str = "") -> None:
    ts = _color(f"[{time.strftime('%H:%M:%S')}]", DIM)
    msg = f"  {ts} {icon}  {text}"
    if detail:
        msg += _color(f"  ({detail})", DIM)
    print(msg)


def _ok(text: str, detail: str = "") -> None:
    _step(_color("✓", BRIGHT_GREEN), _color(text, GREEN), detail)


def _err(text: str, detail: str = "") -> None:
    _step(_color("✗", BRIGHT_RED), _color(text, RED), detail)


def _info(text: str, detail: str = "") -> None:
    _step(_color("→", BRIGHT_BLUE), text, detail)


def _warn(text: str, detail: str = "") -> None:
    _step(_color("⚠", BRIGHT_YELLOW), _color(text, YELLOW), detail)


def _badge(label: str, value: str, color: str = BRIGHT_CYAN) -> str:
    return _color(f" {label}: ", DIM) + _color(value, color, BOLD)


# ===== Fake LLM response =====

class FakeLLMResponse:
    """Mimics the Anthropic SDK response shape so decorators auto-extract tokens."""
    def __init__(self, text: str, input_tokens: int, output_tokens: int):
        self.content = [type("Block", (), {"type": "text", "text": text})()]
        self.usage = type("Usage", (), {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        })()
        self.stop_reason = "end_turn"


# ===== Simulated knowledge base for RAG =====

KNOWLEDGE_BASE = [
    {
        "id": "doc_001",
        "title": "Agentic AI Architectures 2026",
        "content": "Multi-agent systems now leverage tool-use, memory, and self-reflection. "
                   "ReAct, Toolformer, and AutoGPT patterns have converged into unified frameworks.",
        "score": 0.94,
    },
    {
        "id": "doc_002",
        "title": "RAG Pipeline Best Practices",
        "content": "Retrieval-Augmented Generation reduces hallucination by grounding LLM responses "
                   "in retrieved documents. Hybrid search (dense + sparse) outperforms pure vector search.",
        "score": 0.87,
    },
    {
        "id": "doc_003",
        "title": "LLM Cost Optimisation Strategies",
        "content": "Prompt compression, model routing (large for planning, small for execution), "
                   "and semantic caching can reduce costs by 40–70% without quality loss.",
        "score": 0.81,
    },
    {
        "id": "doc_004",
        "title": "Error Resilience in AI Agents",
        "content": "Production agents require exponential backoff, circuit breakers, and fallback "
                   "chains. Cascade failures are the leading cause of agent downtime.",
        "score": 0.79,
    },
    {
        "id": "doc_005",
        "title": "Observability for LLM Systems",
        "content": "OpenTelemetry-based tracing, token accounting, and causal DAG analysis provide "
                   "the visibility needed to debug and optimise agentic workflows at scale.",
        "score": 0.76,
    },
]

# ===== Call counters for simulating failures =====

_call_counts: dict[str, int] = {
    "web_search": 0,
    "fetch_page": 0,
    "validate_content": 0,
}


# ===== Step 1 — LLM: Research Planner =====

@trace_llm(model="claude-sonnet-4-20250514", name="research_planner")
async def llm_plan_research(topic: str) -> FakeLLMResponse:
    """LLM call: plan the research strategy for a given topic."""
    await asyncio.sleep(random.uniform(0.04, 0.09))
    plan_text = (
        f"Research plan for '{topic}':\n"
        "1. Vector search knowledge base for relevant documents\n"
        "2. Web search for latest information\n"
        "3. Fetch and validate top result\n"
        "4. Run synthesis pipeline\n"
        "5. Produce final structured report"
    )
    return FakeLLMResponse(
        text=plan_text,
        input_tokens=random.randint(900, 1400),
        output_tokens=random.randint(180, 320),
    )


# ===== Step 2 — Retrieval: Vector Search (RAG) =====

@trace_retrieval(name="vector_search")
async def vector_search(query: str, top_k: int = 3) -> list[dict]:
    """Simulated dense vector similarity search over the knowledge base."""
    await asyncio.sleep(random.uniform(0.02, 0.06))

    # Simulate score variation
    results = []
    for doc in KNOWLEDGE_BASE[:top_k]:
        jitter = random.uniform(-0.05, 0.05)
        results.append({**doc, "score": round(doc["score"] + jitter, 3)})

    results.sort(key=lambda d: d["score"], reverse=True)
    return results


# ===== Step 3 — Tool: Web Search =====

@trace_tool(name="web_search")
async def web_search(query: str) -> dict:
    """External web search — first call times out to simulate real failure."""
    _call_counts["web_search"] += 1
    await asyncio.sleep(random.uniform(0.03, 0.07))

    if _call_counts["web_search"] == 1:
        raise TimeoutError(
            f"web_search timed out after 30s for query='{query}'"
        )

    return {
        "results": [
            f"[2026] Agentic AI breakthrough: {query} — TechCrunch",
            f"OpenAI, Anthropic race to dominate {query} market — The Verge",
            f"How {query} is reshaping enterprise software — Forbes",
        ],
        "total": 3,
        "latency_ms": 412,
    }


# ===== Step 4 — Tool: Page Fetcher =====

@trace_tool(name="fetch_page")
async def fetch_page(url: str) -> dict:
    """Fetch and parse a web page — fails first time due to upstream search failure."""
    _call_counts["fetch_page"] += 1
    await asyncio.sleep(random.uniform(0.02, 0.05))

    if _call_counts["fetch_page"] == 1:
        raise ValueError(
            f"fetch_page received invalid URL '{url}' — likely from failed upstream search"
        )

    return {
        "url": url,
        "title": "Agentic AI 2026: The State of the Art",
        "content": (
            "Large language models have evolved from passive assistants to active agents "
            "capable of multi-step reasoning, tool use, and self-correction. "
            "Key advances include persistent memory, multi-agent collaboration, and "
            "real-time web grounding. FlowLens-style observability has become essential "
            "for production deployments."
        ),
        "word_count": 847,
        "read_time_s": 3.4,
    }


# ===== Step 5 — Tool: Content Validator =====

@trace_tool(name="validate_content")
async def validate_content(content: str) -> dict:
    """Quality-gate: checks content length, keyword density, and freshness."""
    _call_counts["validate_content"] += 1
    await asyncio.sleep(random.uniform(0.01, 0.03))

    word_count = len(content.split())
    keywords = ["agent", "llm", "ai", "model", "tool", "memory", "reasoning"]
    keyword_hits = sum(1 for kw in keywords if kw.lower() in content.lower())
    quality_score = min(1.0, (word_count / 50) * 0.5 + (keyword_hits / len(keywords)) * 0.5)

    return {
        "valid": quality_score >= 0.5,
        "quality_score": round(quality_score, 3),
        "word_count": word_count,
        "keyword_hits": keyword_hits,
        "issues": [] if quality_score >= 0.5 else ["content too short", "low keyword density"],
    }


# ===== Step 6 — Chain: Synthesis Pipeline =====

@trace_chain(name="synthesis_pipeline")
async def synthesis_pipeline(
    rag_docs: list[dict],
    web_content: str,
    topic: str,
) -> dict:
    """
    Multi-step synthesis chain:
      1. Merge RAG + web content
      2. Validate merged content
      3. LLM synthesis call
    """
    # Merge sources
    rag_text = "\n".join(
        f"[{d['title']}]: {d['content']}" for d in rag_docs
    )
    merged = f"=== Knowledge Base ===\n{rag_text}\n\n=== Web ===\n{web_content}"

    # Validate merged content
    validation = await validate_content(merged)

    if not validation["valid"]:
        raise RuntimeError(
            f"Merged content failed quality gate: {validation['issues']}"
        )

    # LLM synthesis
    synthesis = await llm_synthesise(merged, topic)

    return {
        "synthesis": synthesis.content[0].text,
        "source_count": len(rag_docs) + 1,
        "quality_score": validation["quality_score"],
        "token_used": synthesis.usage.input_tokens + synthesis.usage.output_tokens,
    }


@trace_llm(model="claude-haiku-4-20250514", name="content_synthesiser")
async def llm_synthesise(context: str, topic: str) -> FakeLLMResponse:
    """LLM call: synthesise a structured answer from multiple sources."""
    await asyncio.sleep(random.uniform(0.06, 0.12))
    synthesis_text = (
        f"## {topic}: Research Synthesis\n\n"
        "**Key Findings:**\n"
        "- Agentic AI has matured significantly, with multi-agent collaboration now standard\n"
        "- RAG pipelines with hybrid search achieve 40% better accuracy than naive retrieval\n"
        "- Observability tooling (FlowLens, Langfuse, etc.) is critical for production agents\n"
        "- Cost optimisation via model routing can reduce LLM spend by up to 70%\n\n"
        "**Emerging Trends:**\n"
        "- Persistent agent memory across sessions (MemGPT-style)\n"
        "- Tool-augmented reasoning with automatic fallback chains\n"
        "- Real-time streaming observability dashboards\n\n"
        "**Recommendation:** Instrument all agents with FlowLens before production deployment."
    )
    return FakeLLMResponse(
        text=synthesis_text,
        input_tokens=random.randint(1200, 2400),
        output_tokens=random.randint(280, 480),
    )


# ===== Step 7 — LLM: Final Report Generator =====

@trace_llm(model="claude-sonnet-4-20250514", name="report_generator")
async def llm_generate_report(synthesis: str, topic: str) -> FakeLLMResponse:
    """LLM call: format the synthesis into a final polished report."""
    await asyncio.sleep(random.uniform(0.05, 0.10))
    report_text = (
        f"# Research Report: {topic}\n"
        f"*Generated by FlowLens Research Agent — {time.strftime('%Y-%m-%d %H:%M')}*\n\n"
        + synthesis
        + "\n\n---\n*Report generated with full observability via FlowLens.*"
    )
    return FakeLLMResponse(
        text=report_text,
        input_tokens=random.randint(600, 1100),
        output_tokens=random.randint(350, 600),
    )


# ===== The Main Agent =====

@trace_agent(name="research_agent")
async def run_research_agent(topic: str) -> dict:
    """
    Multi-step RAG Research Agent with realistic failure & recovery.

    Execution flow:
      1.  LLM planning                   (@trace_llm)
      2.  Vector search (RAG retrieval)  (@trace_retrieval)
      3.  Web search (FAIL — timeout)   (@trace_tool)
      4.  Fetch page (FAIL — cascade)   (@trace_tool)
      5.  Web search retry (success)    (@trace_tool)
      6.  Fetch page retry (success)    (@trace_tool)
      7.  Synthesis pipeline chain      (@trace_chain)
           ├─ Content validation        (@trace_tool)
           └─ LLM synthesis             (@trace_llm)
      8.  LLM report generation         (@trace_llm)
    """
    _info(f"Starting research agent for topic: {BOLD}{topic}{RESET}")

    # ── Step 1: LLM Planning ──────────────────────────────────────────────
    _subsection("Step 1: LLM Research Planning")
    t0 = time.perf_counter()
    plan = await llm_plan_research(topic)
    plan_ms = (time.perf_counter() - t0) * 1000
    _ok("Research plan created", f"{plan_ms:.0f}ms · {plan.usage.input_tokens}→{plan.usage.output_tokens} tokens")
    _info("Plan: " + plan.content[0].text.split("\n")[0])

    # ── Step 2: RAG Vector Search ─────────────────────────────────────────
    _subsection("Step 2: RAG Vector Search (knowledge base)")
    t0 = time.perf_counter()
    rag_docs = await vector_search(topic, top_k=3)
    rag_ms = (time.perf_counter() - t0) * 1000
    _ok(f"Retrieved {len(rag_docs)} documents", f"{rag_ms:.0f}ms")
    for doc in rag_docs:
        score_bar = _bar(int(doc["score"] * 20), 20)
        print(f"      {_color(score_bar, BRIGHT_GREEN)}  {doc['score']:.3f}  {_color(doc['title'], DIM)}")

    # ── Step 3: Web Search (will fail first time) ─────────────────────────
    _subsection("Step 3: Web Search + Page Fetch (with recovery)")
    web_content = ""
    search_result = None

    _info("Attempting web search...")
    try:
        search_result = await web_search(topic)
    except TimeoutError as exc:
        _err(f"Web search timed out", str(exc)[:60])
        _warn("Attempting cascade fetch with empty URL (will also fail)...")

        try:
            await fetch_page("")
        except ValueError as exc2:
            _err("Cascade failure: fetch_page", str(exc2)[:60])

        # ── Step 4: Retry web search ──────────────────────────────────────
        _warn("Retrying web search...")
        t0 = time.perf_counter()
        search_result = await web_search(topic)
        retry_ms = (time.perf_counter() - t0) * 1000
        _ok("Web search succeeded on retry", f"{retry_ms:.0f}ms · {search_result['total']} results")

    # ── Step 5: Fetch top result ──────────────────────────────────────────
    top_url = search_result["results"][0] if search_result else "https://example.com"
    _info(f"Fetching: {top_url[:60]}...")
    t0 = time.perf_counter()
    page = await fetch_page(top_url)
    fetch_ms = (time.perf_counter() - t0) * 1000
    _ok(f"Fetched '{page['title']}'", f"{fetch_ms:.0f}ms · {page['word_count']} words")
    web_content = page["content"]

    # ── Step 6: Synthesis Pipeline ────────────────────────────────────────
    _subsection("Step 6: Synthesis Pipeline (chain)")
    _info("Running synthesis: RAG + web → content validation → LLM synthesis")
    t0 = time.perf_counter()
    synthesis_result = await synthesis_pipeline(rag_docs, web_content, topic)
    synth_ms = (time.perf_counter() - t0) * 1000
    _ok(
        f"Synthesis complete ({synthesis_result['source_count']} sources)",
        f"{synth_ms:.0f}ms · quality={synthesis_result['quality_score']:.2f}",
    )

    # ── Step 7: Final Report ──────────────────────────────────────────────
    _subsection("Step 7: Final Report Generation")
    t0 = time.perf_counter()
    report = await llm_generate_report(synthesis_result["synthesis"], topic)
    report_ms = (time.perf_counter() - t0) * 1000
    _ok("Report generated", f"{report_ms:.0f}ms · {report.usage.output_tokens} output tokens")

    return {
        "topic": topic,
        "status": "completed",
        "rag_docs_used": len(rag_docs),
        "synthesis_quality": synthesis_result["quality_score"],
        "report_preview": report.content[0].text[:200] + "...",
        "report_full": report.content[0].text,
    }


# ===== Analysis & Pretty Report =====

def print_causal_dag_markdown(dag, node_map: dict) -> None:
    """Print the causal DAG in Markdown-compatible format."""
    print()
    print(_color("## Causal DAG — Error Propagation Graph", BRIGHT_CYAN, BOLD))
    print()

    if not dag.root_causes:
        print("  *(no errors detected — clean execution)*")
        return

    print("```")
    print("Root causes → cascaded failures:")
    print()

    for rc_id in dag.root_causes:
        rc_node = node_map.get(rc_id)
        if rc_node:
            print(f"  [ROOT CAUSE] {rc_node.name}")
            print(f"  Error: {rc_node.error_message}")

    if dag.edges:
        print()
        print("  Propagation edges:")
        for edge in dag.edges:
            src = node_map.get(edge.source_id)
            tgt = node_map.get(edge.target_id)
            if src and tgt:
                relation = edge.relation.upper()
                print(f"  {src.name}  ──[{relation}]──▶  {tgt.name}")

    print("```")


def print_full_report(trace: Trace) -> None:
    """Print complete FlowLens analysis: DAG, patterns, advisor recommendations."""

    dag = build_causal_dag(trace)
    patterns = detect_patterns(trace, dag)
    advisor = TraceAdvisor(trace=trace, dag=dag, patterns=patterns, traces_per_month=5_000)
    report = advisor.generate_report()
    node_map = {n.span_id: n for n in dag.nodes}

    _section("FLOWLENS ANALYSIS REPORT", width=72)

    # ── Trace Overview ────────────────────────────────────────────────────
    print()
    print(_color("  ## Trace Overview", BRIGHT_WHITE, BOLD))
    print()

    status_color = BRIGHT_RED if trace.has_errors else BRIGHT_GREEN
    status_text = "ERRORS DETECTED" if trace.has_errors else "HEALTHY"
    print(f"  {'Status':<22} {_color(status_text, status_color, BOLD)}")
    print(f"  {'Trace ID':<22} {_color(trace.trace_id[:24] + '...', DIM)}")
    print(f"  {'Service':<22} {trace.service_name}")
    print(f"  {'Spans':<22} {len(trace.spans)}")
    print(f"  {'Duration':<22} {_color(f'{trace.duration_ms:.0f} ms', BRIGHT_CYAN)}")
    print(f"  {'Total Tokens':<22} {_color(f'{trace.total_tokens:,}', BRIGHT_YELLOW)}")
    print(f"  {'Total Cost':<22} {_color(f'${trace.total_cost_usd:.5f}', BRIGHT_YELLOW)}")
    print(f"  {'Error Count':<22} {_color(str(trace.error_count), BRIGHT_RED if trace.error_count else BRIGHT_GREEN)}")
    print(f"  {'Error Rate':<22} {_color(f'{trace.error_rate:.0%}', BRIGHT_RED if trace.error_rate > 0 else BRIGHT_GREEN)}")

    # ── Span Timeline ─────────────────────────────────────────────────────
    print()
    print(_color("  ## Span Timeline", BRIGHT_WHITE, BOLD))
    print()

    kind_icons = {
        "agent":     ("◈", BRIGHT_MAGENTA),
        "llm":       ("◉", BRIGHT_BLUE),
        "tool":      ("◆", BRIGHT_CYAN),
        "chain":     ("◎", BRIGHT_YELLOW),
        "retrieval": ("◐", BRIGHT_GREEN),
        "custom":    ("○", WHITE),
    }

    for span in trace.spans:
        icon, color = kind_icons.get(span.kind.value, ("○", WHITE))
        status_sym = _color("✓", BRIGHT_GREEN) if span.status.value == "ok" else _color("✗", BRIGHT_RED)
        duration = f"{span.duration_ms:.0f}ms"
        tokens_str = f" · {span.token_usage.total_tokens} tok" if span.token_usage else ""
        indent = "    " if span.parent_span_id else "  "
        kind_label = _color(f"[{span.kind.value.upper():<10}]", color)
        name_label = _color(f"{span.name:<30}", BOLD if not span.parent_span_id else "")
        print(f"  {indent}{status_sym}  {kind_label}  {name_label}  {_color(duration, DIM)}{_color(tokens_str, DIM)}")

    # ── Causal DAG ────────────────────────────────────────────────────────
    print()
    print(_color("  ## Causal DAG (Error Analysis)", BRIGHT_WHITE, BOLD))
    print()

    if dag.root_causes:
        print(f"  {'Root Causes':<24} {_color(str(len(dag.root_causes)), BRIGHT_RED)}")
        for rc_id in dag.root_causes:
            rc_node = node_map.get(rc_id)
            if rc_node:
                print(f"    {_color('◉', BRIGHT_RED)}  {_color(rc_node.name, RED, BOLD)}")
                print(f"       {_color(rc_node.error_message or '(unknown error)', DIM)}")
    else:
        print(f"  {'Root Causes':<24} {_color('None', BRIGHT_GREEN)}")

    cascaded = [n for n in dag.nodes if n.error_role.value == "cascaded"]
    if cascaded:
        print()
        print(f"  {'Cascaded Failures':<24} {_color(str(len(cascaded)), BRIGHT_YELLOW)}")
        for node in cascaded:
            print(f"    {_color('↳', YELLOW)}  {_color(node.name, YELLOW)}")
            print(f"       {_color(node.error_message or '(cascade)', DIM)}")

    if dag.edges:
        print()
        print(f"  {'Error Propagation':<24}")
        for edge in dag.edges:
            src = node_map.get(edge.source_id)
            tgt = node_map.get(edge.target_id)
            if src and tgt:
                rel = _color(f"──[{edge.relation}]──▶", DIM)
                print(f"    {_color(src.name, RED)}  {rel}  {_color(tgt.name, YELLOW)}")

    print(f"\n  {'Cascade Depth':<24} {_color(str(dag.cascade_depth), BRIGHT_YELLOW)}")

    # ── Pattern Detection ─────────────────────────────────────────────────
    print()
    print(_color("  ## Detected Patterns", BRIGHT_WHITE, BOLD))
    print()

    if patterns:
        sev_icons = {"critical": ("🔴", BRIGHT_RED), "warning": ("🟡", BRIGHT_YELLOW), "info": ("🔵", BRIGHT_BLUE)}
        for p in patterns:
            icon, color = sev_icons.get(p.severity, ("•", WHITE))
            ptype = _color(f"[{p.pattern_type.value}]", color, BOLD)
            print(f"  {icon}  {ptype}")
            print(f"       {p.description}")
            print()
    else:
        print(f"  {_color('No problematic patterns detected.', BRIGHT_GREEN)}")

    # ── Advisor Recommendations ───────────────────────────────────────────
    print()
    print(_color("  ## Advisor Recommendations", BRIGHT_WHITE, BOLD))
    print()

    severity_score = report["severity_score"]
    severity_level = report["severity_level"]
    score_color = BRIGHT_GREEN if severity_score < 40 else BRIGHT_YELLOW if severity_score < 70 else BRIGHT_RED
    score_bar = _bar(severity_score, 100, "█", "░")

    print(f"  Severity Score  {_color(f'{severity_score}/100', score_color, BOLD)}")
    print(f"  {_color(score_bar[:40], score_color)}  {_color(severity_level.upper(), score_color, BOLD)}")
    print()

    savings = report["estimated_savings"]
    monthly = report["estimated_monthly_savings"]
    print(f"  {'Per-trace savings':}")
    print(f"    Tokens saved   {_color(str(savings['token_savings']), BRIGHT_CYAN)}")
    print(f"    Cost saved     {_color(f\"${savings['cost_savings_usd']:.4f}\", BRIGHT_GREEN)}")
    print(f"    Latency saved  {_color(f\"{savings['time_savings_ms']:.0f}ms\", BRIGHT_YELLOW)}")
    print()
    print(f"  {'Monthly (5,000 traces/mo)':}")
    print(f"    Cost saved     {_color(f\"${monthly['cost_savings_usd_monthly']:.2f}\", BRIGHT_GREEN, BOLD)}")
    print(f"    Tokens saved   {_color(f\"{monthly['token_savings_monthly']:,}\", BRIGHT_CYAN)}")
    print()

    recs = report.get("recommendations_detail", [])
    if recs:
        print(f"  {'Action Items':}")
        for i, rec in enumerate(recs, 1):
            sev_color = BRIGHT_RED if rec["severity"] == "critical" else BRIGHT_YELLOW if rec["severity"] == "warning" else BRIGHT_BLUE
            sev_badge = _color(f"[{rec['severity'].upper()}]", sev_color, BOLD)
            print(f"  {i}. {sev_badge}  {_color(rec['title'], BOLD)}")
            print(f"     {_color(rec['description'][:120] + ('...' if len(rec['description']) > 120 else ''), DIM)}")
            if rec.get("code_snippet"):
                snippet_lines = rec["code_snippet"].strip().split("\n")[:4]
                for line in snippet_lines:
                    print(f"       {_color('│ ', DIM)}{_color(line, CYAN)}")
            print()

    # ── Causal DAG in Markdown ────────────────────────────────────────────
    print_causal_dag_markdown(dag, node_map)

    # ── Final Result Summary ──────────────────────────────────────────────
    print()
    print(_color("═" * 72, BRIGHT_CYAN))
    print(_color("  ANALYSIS COMPLETE", BRIGHT_WHITE, BOLD))
    print(_color("═" * 72, BRIGHT_CYAN))
    print()


# ===== Trace collection =====

_collected_traces: list[Trace] = []


def _capture_trace(trace: Trace) -> None:
    _collected_traces.append(trace)


# ===== Main entry point =====

async def main() -> None:
    # ── Banner ──────────────────────────────────────────────────────────
    print()
    banner_lines = [
        "╔══════════════════════════════════════════════════════════════════════╗",
        "║         F L O W L E N S   —   Agent Observability Platform           ║",
        "║         Multi-Step RAG Research Agent Demo  (all 5 decorators)       ║",
        "╚══════════════════════════════════════════════════════════════════════╝",
    ]
    for line in banner_lines:
        print(_color(line, BRIGHT_CYAN, BOLD))
    print()
    print(_color("  Decorator showcase:", BRIGHT_WHITE))
    print(f"    {_color('@trace_agent', BRIGHT_MAGENTA)}      — orchestration root span")
    print(f"    {_color('@trace_llm', BRIGHT_BLUE)}        — LLM call with token tracking")
    print(f"    {_color('@trace_tool', BRIGHT_CYAN)}       — external tool invocation")
    print(f"    {_color('@trace_chain', BRIGHT_YELLOW)}      — multi-step processing pipeline")
    print(f"    {_color('@trace_retrieval', BRIGHT_GREEN)}   — RAG vector search")
    print()

    # ── FlowLens initialisation ─────────────────────────────────────────
    lens = FlowLens(
        service_name="research-agent-demo",
        export_to="console",
        verbose=False,
        on_trace_complete=_capture_trace,
    )

    # ── Run the agent ───────────────────────────────────────────────────
    topic = "Latest advances in agentic AI 2026"
    _section("AGENT EXECUTION", width=72)

    start = time.perf_counter()
    try:
        result = await run_research_agent(topic)
        elapsed_ms = (time.perf_counter() - start) * 1000

        print()
        _ok(
            f"Agent completed in {elapsed_ms:.0f}ms",
            f"quality={result['synthesis_quality']:.2f}",
        )
    except Exception as exc:
        print()
        _err(f"Agent failed: {exc}")
        raise
    finally:
        lens.shutdown()

    # ── Print full report ───────────────────────────────────────────────
    if _collected_traces:
        print_full_report(_collected_traces[0])

    # ── Show final research output ──────────────────────────────────────
    _section("RESEARCH OUTPUT PREVIEW", width=72)
    print()
    print(_color("  Topic: " + topic, BOLD))
    print()
    for line in result["report_preview"].split("\n"):
        print(f"  {line}")
    print()
    print(_color("  (Full report available via FlowLens dashboard)", DIM))
    print()


if __name__ == "__main__":
    asyncio.run(main())
