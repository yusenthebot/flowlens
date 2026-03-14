#!/usr/bin/env python3
"""
FlowLens Quickstart — Zero to Traced Agent in Seconds
=======================================================
The absolute minimum example: create a trace, add spans, finish, print summary.

Run with:
    python3 examples/quickstart.py
"""

import asyncio
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flowlens import FlowLens, trace_agent, trace_llm, trace_retrieval, trace_tool
from flowlens.sdk.models import Trace

# ── Shared ANSI helpers ────────────────────────────────────────────────────
RESET = "\033[0m"; BOLD = "\033[1m"; DIM = "\033[2m"
CYAN = "\033[96m"; GREEN = "\033[92m"; YELLOW = "\033[93m"; RED = "\033[91m"
MAGENTA = "\033[95m"; BLUE = "\033[94m"; WHITE = "\033[97m"

def c(text, *codes): return "".join(codes) + str(text) + RESET
def banner(t): print(c(f"\n{'═'*64}\n  {t}\n{'═'*64}", CYAN, BOLD))
def ok(t, d=""): print(f"  {c('✓',GREEN)}  {t}" + (c(f"  ({d})",DIM) if d else ""))
def info(t): print(f"  {c('→',BLUE)}  {t}")

# ── Fake LLM response (mimics Anthropic SDK shape) ─────────────────────────
class _LLM:
    def __init__(self, txt, inp, out):
        self.content = [type("B",(),{"text":txt})()]
        self.usage = type("U",(),{"input_tokens":inp,"output_tokens":out})()

# ── Step 1: Create a FlowLens instance ────────────────────────────────────
# One instance sets the global singleton — all decorators below find it.
_traces: list[Trace] = []
lens = FlowLens(
    service_name="quickstart",
    export_to="console",
    verbose=False,
    on_trace_complete=lambda t: _traces.append(t),
)

# ── Step 2: Decorate your functions ───────────────────────────────────────
@trace_retrieval(name="vector_search")
async def search(query: str) -> list[dict]:
    await asyncio.sleep(0.02)
    return [{"id": "doc_1", "text": f"Result for {query}", "score": 0.94}]

@trace_tool(name="web_fetch")
async def fetch(url: str) -> str:
    await asyncio.sleep(0.03)
    return f"<html>Content from {url}</html>"

@trace_llm(model="claude-sonnet-4-20250514", name="llm_call")
async def think(prompt: str) -> _LLM:
    await asyncio.sleep(0.04)
    return _LLM(f"Answer: {prompt[:40]}…", random.randint(300,700), random.randint(80,200))

@trace_agent(name="quickstart_agent")   # ← creates the trace root span
async def my_agent(question: str) -> str:
    docs   = await search(question)      # RETRIEVAL span
    page   = await fetch("https://example.com")  # TOOL span
    resp   = await think(question)       # LLM span (token + cost auto-tracked)
    return resp.content[0].text

# ── Step 3: Run and inspect ───────────────────────────────────────────────
async def main() -> None:
    print(c("\n╔══════════════════════════════════════════════════════════════╗", CYAN, BOLD))
    print(c("║        FlowLens — Agent Observability Platform               ║", CYAN, BOLD))
    print(c("║        Quickstart: zero to traced agent in seconds           ║", CYAN, BOLD))
    print(c("╚══════════════════════════════════════════════════════════════╝", CYAN, BOLD))

    info("Running agent with @trace_agent + @trace_llm + @trace_tool + @trace_retrieval …")
    result = await my_agent("What is agentic AI?")
    ok(f"Agent returned: {c(result, GREEN)}")

    # Pretty-print trace summary
    if _traces:
        t = _traces[0]
        banner("Trace Summary")
        rows = [
            ("trace_id",     c(t.trace_id[:28] + "…", DIM)),
            ("service",      t.service_name),
            ("spans",        c(str(len(t.spans)), CYAN)),
            ("duration",     c(f"{t.duration_ms:.0f} ms", CYAN)),
            ("total_tokens", c(f"{t.total_tokens:,}", YELLOW)),
            ("total_cost",   c(f"${t.total_cost_usd:.6f}", YELLOW)),
            ("errors",       c(str(t.error_count), RED if t.error_count else GREEN)),
        ]
        for label, val in rows:
            print(f"  {c(label + ':',DIM):<36}  {val}")

        # Span tree
        banner("Span Tree")
        kind_icons = {"agent":"◈","llm":"◉","tool":"◆","chain":"◎","retrieval":"◐"}
        kind_colors = {"agent":MAGENTA,"llm":BLUE,"tool":CYAN,"chain":YELLOW,"retrieval":GREEN}
        for span in t.spans:
            kv = span.kind.value
            icon = kind_icons.get(kv,"○")
            col  = kind_colors.get(kv, WHITE)
            indent = "    " if span.parent_span_id else "  "
            status = c("✓", GREEN) if span.status.value == "ok" else c("✗", RED)
            tok = f" · {span.token_usage.total_tokens} tok" if span.token_usage else ""
            print(f"  {indent}{status}  {c(f'[{kv.upper():<9}]', col)}  "
                  f"{c(span.name, BOLD if not span.parent_span_id else '')}  "
                  f"{c(f'{span.duration_ms:.0f}ms', DIM)}{c(tok, DIM)}")

    print(c("\n  Done! Next: python3 examples/rag_pipeline.py", DIM))
    lens.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
