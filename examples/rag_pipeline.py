#!/usr/bin/env python3
"""
FlowLens Example — RAG Pipeline
=================================
Demonstrates a realistic Retrieval-Augmented Generation (RAG) pipeline
instrumented end-to-end with FlowLens decorators.

Pipeline stages:
  1. embed_query     (@trace_embedding) — convert query to dense vector
  2. vector_search   (@trace_retrieval) — ANN search over knowledge base
  3. rerank_results  (@trace_tool)      — cross-encoder reranking
  4. build_prompt    (@trace_chain)     — assemble prompt from top docs
  5. generate_answer (@trace_llm)       — LLM synthesis with token tracking
  6. rag_agent       (@trace_agent)     — orchestrates the full pipeline

Shows: token usage, cost tracking, trace tree, and pattern analysis.

Run with:
    python3 examples/rag_pipeline.py
"""

import asyncio
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── FlowLens imports ────────────────────────────────────────────────────────
from flowlens import (
    FlowLens,
    trace_agent,
    trace_chain,
    trace_embedding,
    trace_llm,
    trace_retrieval,
    trace_tool,
)
from flowlens.analysis.advisor import TraceAdvisor
from flowlens.analysis.dag_builder import build_causal_dag
from flowlens.analysis.patterns import detect_patterns
from flowlens.sdk.models import Trace

# ── Utils (shared helpers from _utils.py) ──────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _utils import (
    BOLD,
    BRIGHT_BLUE,
    BRIGHT_CYAN,
    BRIGHT_GREEN,
    BRIGHT_MAGENTA,
    BRIGHT_RED,
    BRIGHT_WHITE,
    BRIGHT_YELLOW,
    DIM,
    WHITE,
    c,
    hbar,
    info,
    ok,
    print_table,
    print_trace_tree,
    progress,
    section,
    subsection,
)

# ── Simulated knowledge base ─────────────────────────────────────────────────
KNOWLEDGE_BASE = [
    {
        "id": "kb_001", "title": "Agentic AI Architectures 2026",
        "content": (
            "Modern AI agents combine tool use, persistent memory, and self-reflection. "
            "ReAct, Toolformer, and AutoGPT patterns have converged into unified frameworks. "
            "Multi-agent collaboration is now the dominant paradigm for complex tasks."
        ),
        "embedding": [0.82, 0.91, 0.74, 0.66, 0.88],
    },
    {
        "id": "kb_002", "title": "RAG Best Practices",
        "content": (
            "Hybrid search (dense + sparse BM25) outperforms pure vector search by 40%. "
            "Reranking with a cross-encoder adds 15–25% accuracy over bi-encoder retrieval. "
            "Chunking strategy and overlap significantly affect recall quality."
        ),
        "embedding": [0.78, 0.95, 0.61, 0.72, 0.83],
    },
    {
        "id": "kb_003", "title": "LLM Cost Optimisation",
        "content": (
            "Prompt compression, model routing, and semantic caching reduce costs by 40–70%. "
            "Use a small model for retrieval scoring and a large model only for final synthesis. "
            "Token budgeting per pipeline stage prevents runaway costs."
        ),
        "embedding": [0.69, 0.77, 0.93, 0.58, 0.71],
    },
    {
        "id": "kb_004", "title": "Observability for LLM Systems",
        "content": (
            "OpenTelemetry-compatible tracing, token accounting, and causal DAG analysis "
            "are essential for debugging production agents. FlowLens provides all three "
            "with zero-code instrumentation via auto_instrument()."
        ),
        "embedding": [0.55, 0.68, 0.79, 0.94, 0.62],
    },
    {
        "id": "kb_005", "title": "Vector Search Fundamentals",
        "content": (
            "Approximate Nearest Neighbour (ANN) search over dense embeddings enables "
            "semantic similarity retrieval at scale. HNSW and IVF indexes trade recall "
            "for speed. Re-scoring with cross-encoders recovers precision."
        ),
        "embedding": [0.91, 0.63, 0.55, 0.77, 0.89],
    },
]

# ── Fake LLM response (Anthropic SDK shape) ──────────────────────────────────
class FakeLLM:
    def __init__(self, text: str, inp: int, out: int):
        self.content = [type("B", (), {"text": text})()]
        self.usage = type("U", (), {"input_tokens": inp, "output_tokens": out})()
        self.stop_reason = "end_turn"


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline stages
# ─────────────────────────────────────────────────────────────────────────────

@trace_embedding(name="embed_query")
async def embed_query(query: str) -> list[float]:
    """Convert user query to a dense embedding vector (simulated)."""
    await asyncio.sleep(random.uniform(0.01, 0.03))
    # Simulate an embedding — random unit-ish vector
    vec = [random.uniform(0.5, 1.0) for _ in range(5)]
    norm = sum(v ** 2 for v in vec) ** 0.5
    return [round(v / norm, 4) for v in vec]


def _cosine_sim(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na  = sum(x ** 2 for x in a) ** 0.5
    nb  = sum(x ** 2 for x in b) ** 0.5
    return dot / (na * nb) if na * nb > 0 else 0.0


@trace_retrieval(name="vector_search")
async def vector_search(query_vec: list[float], top_k: int = 4) -> list[dict]:
    """ANN search: cosine similarity over the knowledge base."""
    await asyncio.sleep(random.uniform(0.02, 0.05))
    scored = []
    for doc in KNOWLEDGE_BASE:
        score = _cosine_sim(query_vec, doc["embedding"])
        scored.append({**doc, "score": round(score + random.uniform(-0.05, 0.05), 4)})
    scored.sort(key=lambda d: d["score"], reverse=True)
    return scored[:top_k]


@trace_tool(name="cross_encoder_rerank")
async def rerank_results(query: str, docs: list[dict], top_k: int = 3) -> list[dict]:
    """
    Cross-encoder reranking — a heavier but more accurate scoring step.
    Simulates a small neural reranker that rescores each query-doc pair.
    """
    await asyncio.sleep(random.uniform(0.03, 0.07))
    # Simulate reranking — add a small relevance bonus based on keyword overlap
    query_words = set(query.lower().split())
    reranked = []
    for doc in docs:
        content_words = set(doc["content"].lower().split())
        overlap = len(query_words & content_words) / max(len(query_words), 1)
        reranked_score = doc["score"] * 0.6 + overlap * 0.4 + random.uniform(-0.02, 0.02)
        reranked.append({**doc, "rerank_score": round(reranked_score, 4)})
    reranked.sort(key=lambda d: d["rerank_score"], reverse=True)
    return reranked[:top_k]


@trace_chain(name="build_prompt")
async def build_prompt(query: str, docs: list[dict]) -> str:
    """
    Assemble the final prompt from retrieved documents.
    This chain step runs lightweight text processing — no LLM call.
    """
    await asyncio.sleep(random.uniform(0.005, 0.01))
    context_blocks = []
    for i, doc in enumerate(docs, 1):
        block = (
            f"[Source {i}: {doc['title']} | relevance={doc.get('rerank_score', doc['score']):.3f}]\n"
            f"{doc['content']}"
        )
        context_blocks.append(block)

    context = "\n\n".join(context_blocks)
    prompt = (
        f"You are a knowledgeable AI assistant. Answer the following question "
        f"using only the provided context. Be concise and accurate.\n\n"
        f"CONTEXT:\n{context}\n\n"
        f"QUESTION: {query}\n\n"
        f"ANSWER:"
    )
    return prompt


@trace_llm(model="claude-sonnet-4-20250514", name="generate_answer")
async def generate_answer(prompt: str) -> FakeLLM:
    """LLM synthesis — generates the final answer from retrieved context."""
    await asyncio.sleep(random.uniform(0.05, 0.10))
    # Estimate input tokens from prompt length (~4 chars per token)
    inp = len(prompt) // 4 + random.randint(50, 100)
    out = random.randint(120, 280)
    answer = (
        "Based on the retrieved sources, here is a comprehensive answer:\n\n"
        "Modern RAG pipelines achieve best results by combining dense vector retrieval "
        "with cross-encoder reranking, reducing hallucinations by grounding responses "
        "in high-quality retrieved context. Hybrid search (dense + sparse BM25) "
        "outperforms either approach alone by 40%. Using a small model for retrieval "
        "scoring and a powerful model only for synthesis optimises cost without "
        "sacrificing quality. FlowLens instruments every stage automatically, giving "
        "full visibility into token usage, latency, and cost per pipeline step."
    )
    return FakeLLM(answer, inp, out)


@trace_agent(name="rag_agent")
async def rag_agent(query: str) -> dict:
    """
    Full RAG pipeline orchestration.
    Span hierarchy:
      AGENT  rag_agent
        EMBEDDING  embed_query
        RETRIEVAL  vector_search
        TOOL       cross_encoder_rerank
        CHAIN      build_prompt
        LLM        generate_answer
    """
    t0 = time.perf_counter()

    info(f"Query: {c(repr(query), BRIGHT_YELLOW)}")

    # Stage 1: embed query
    subsection("Stage 1 — Embedding")
    query_vec = await embed_query(query)
    ok("Query embedded", f"dim={len(query_vec)}")

    # Stage 2: vector search
    subsection("Stage 2 — Vector Search")
    candidates = await vector_search(query_vec, top_k=4)
    ok(f"Retrieved {len(candidates)} candidates")
    for doc in candidates:
        bar = hbar(doc["score"], 1.0, width=16, color=BRIGHT_GREEN)
        score_str = c(f"{doc['score']:.3f}", BRIGHT_GREEN)
        title_str = c(doc['title'], DIM)
        print(f"    {bar}  {score_str}  {title_str}")

    # Stage 3: rerank
    subsection("Stage 3 — Cross-Encoder Reranking")
    top_docs = await rerank_results(query, candidates, top_k=3)
    ok(f"Reranked to top {len(top_docs)} documents")
    for doc in top_docs:
        bar = hbar(doc["rerank_score"], 1.0, width=16, color=BRIGHT_CYAN)
        rscore_str = c(f"{doc['rerank_score']:.3f}", BRIGHT_CYAN)
        rtitle_str = c(doc['title'], DIM)
        print(f"    {bar}  {rscore_str}  {rtitle_str}")

    # Stage 4: build prompt
    subsection("Stage 4 — Prompt Assembly")
    prompt = await build_prompt(query, top_docs)
    est_tokens = len(prompt) // 4
    ok("Prompt assembled", f"~{est_tokens} tokens · {len(top_docs)} sources")

    # Stage 5: generate
    subsection("Stage 5 — LLM Generation (claude-sonnet-4)")
    response = await generate_answer(prompt)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    ok(
        "Answer generated",
        f"{response.usage.input_tokens} in · {response.usage.output_tokens} out tokens",
    )

    return {
        "query":       query,
        "answer":      response.content[0].text,
        "sources":     [d["title"] for d in top_docs],
        "total_ms":    elapsed_ms,
        "input_tok":   response.usage.input_tokens,
        "output_tok":  response.usage.output_tokens,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Analysis & pretty report
# ─────────────────────────────────────────────────────────────────────────────

def print_analysis(trace: Trace) -> None:
    """Run FlowLens analysis and print results."""
    dag      = build_causal_dag(trace)
    patterns = detect_patterns(trace, dag)
    advisor  = TraceAdvisor(trace=trace, dag=dag, patterns=patterns, traces_per_month=10_000)
    report   = advisor.generate_report()

    section("Trace Tree")
    print_trace_tree(trace)

    section("Token & Cost Breakdown")
    headers = ["Span", "Kind", "Model", "Input tok", "Output tok", "Cost (USD)"]
    rows = []
    for span in trace.spans:
        if span.token_usage and span.token_usage.total_tokens:
            model = span.attributes.get("gen_ai.request.model", "—")
            rows.append([
                span.name,
                span.kind.value.upper(),
                model,
                f"{span.token_usage.input_tokens:,}",
                f"{span.token_usage.output_tokens:,}",
                f"${span.token_usage.total_cost_usd:.6f}",
            ])
    if rows:
        print_table(
            headers, rows,
            colors=[BRIGHT_WHITE, BRIGHT_CYAN, DIM, BRIGHT_YELLOW, BRIGHT_YELLOW, BRIGHT_GREEN],
        )
    else:
        print(c("  No LLM token data (no LLM spans with usage).", DIM))

    # Summary metrics
    section("Trace Summary")
    score = report["severity_score"]
    score_col = BRIGHT_GREEN if score < 30 else BRIGHT_YELLOW if score < 60 else BRIGHT_RED
    progress("Health score (lower = better)", score, 100, f"{score}/100", score_col)
    progress("Total tokens used",    trace.total_tokens, 5000, f"{trace.total_tokens:,} tok", BRIGHT_YELLOW)
    progress("Total cost",           trace.total_cost_usd * 100_000, 50, f"${trace.total_cost_usd:.6f}", BRIGHT_GREEN)
    progress("Pipeline latency",     trace.duration_ms, 500, f"{trace.duration_ms:.0f} ms", BRIGHT_CYAN)
    print()

    # Patterns
    if patterns:
        section("Detected Patterns")
        sev_colors = {"critical": BRIGHT_RED, "warning": BRIGHT_YELLOW, "info": BRIGHT_BLUE}
        for p in patterns:
            col = sev_colors.get(p.severity, WHITE)
            print(f"  {c(f'[{p.severity.upper()}]', col, BOLD)}  {c(p.pattern_type.value, col)}  —  {p.description}")
        print()

    # Advisor savings
    savings = report["estimated_savings"]
    monthly = report["estimated_monthly_savings"]
    section("Advisor — Estimated Savings")
    cost_str    = c("${:.5f}".format(savings['cost_savings_usd']), BRIGHT_GREEN)
    latency_str = c("{:.0f} ms".format(savings['time_savings_ms']), BRIGHT_YELLOW)
    monthly_cost = c("${:.2f}".format(monthly['cost_savings_usd_monthly']), BRIGHT_GREEN, BOLD)
    monthly_tok  = c("{:,}".format(monthly['token_savings_monthly']), BRIGHT_CYAN)
    print(f"  {c('Per-trace savings:', DIM)}")
    print(f"    Token reduction  {c(str(savings['token_savings']), BRIGHT_CYAN)}")
    print(f"    Cost reduction   {cost_str}")
    print(f"    Latency saved    {latency_str}")
    print()
    print(f"  {c('Monthly (10,000 traces/mo):', DIM)}")
    print(f"    Cost saved       {monthly_cost}")
    print(f"    Tokens saved     {monthly_tok}")
    print()

    recs = report.get("recommendations_detail", [])
    if recs:
        section("Top Recommendations")
        for i, rec in enumerate(recs[:3], 1):
            sev_col = BRIGHT_RED if rec["severity"] == "critical" else BRIGHT_YELLOW
            sev_badge = c("[{}]".format(rec["severity"].upper()), sev_col, BOLD)
            print(f"  {i}. {sev_badge}  {c(rec['title'], BOLD)}")
            print(f"     {c(rec['description'][:110] + '…', DIM)}")
            print()


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

async def main() -> None:
    # FlowLens setup
    _traces: list[Trace] = []
    lens = FlowLens(
        service_name="rag-pipeline-demo",
        export_to="console",
        verbose=False,
        on_trace_complete=lambda t: _traces.append(t),
    )

    # Branding
    print(c("\n╔══════════════════════════════════════════════════════════════════════╗", BRIGHT_CYAN, BOLD))
    print(c("║         F L O W L E N S   —   Agent Observability Platform           ║", BRIGHT_CYAN, BOLD))
    print(c("║         Example: RAG Pipeline  (embed → search → rerank → LLM)       ║", BRIGHT_CYAN, BOLD))
    print(c("╚══════════════════════════════════════════════════════════════════════╝", BRIGHT_CYAN, BOLD))
    print()
    print(f"  Decorators: {c('@trace_agent',BRIGHT_MAGENTA)}  {c('@trace_embedding',BRIGHT_WHITE)}  "
          f"{c('@trace_retrieval',BRIGHT_GREEN)}  {c('@trace_tool',BRIGHT_CYAN)}  "
          f"{c('@trace_chain',BRIGHT_YELLOW)}  {c('@trace_llm',BRIGHT_BLUE)}")
    print()

    # Run the RAG pipeline
    query = "How do I optimise a RAG pipeline for production cost and accuracy?"
    section("Agent Execution")
    start = time.perf_counter()
    result = await rag_agent(query)
    total_ms = (time.perf_counter() - start) * 1000
    print()
    ok(f"Pipeline complete in {total_ms:.0f} ms")

    # Show answer
    section("Generated Answer")
    print(f"  {c('Query:', BRIGHT_WHITE, BOLD)} {query}")
    print()
    for line in result["answer"].split("\n"):
        print(f"  {c(line, WHITE)}")
    print()
    print(f"  {c('Sources used:', DIM)}")
    for src in result["sources"]:
        print(f"    {c('▸', BRIGHT_GREEN)}  {c(src, DIM)}")
    print()

    # Analysis
    if _traces:
        print_analysis(_traces[0])

    lens.shutdown()
    print(c("  Done! Try: python3 examples/multi_agent.py", DIM))
    print()


if __name__ == "__main__":
    asyncio.run(main())
