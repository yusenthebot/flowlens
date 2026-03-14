#!/usr/bin/env python3
"""
FlowLens Quickstart — From Zero to Full Agent Observability in 5 Minutes
=========================================================================
This file is designed to be read top-to-bottom like a tutorial.
Every line is annotated, and example output is shown in comments.

Run with:
    python examples/quickstart.py

What you will see:
  - Example 1: The absolute minimum — one decorator, one agent
  - Example 2: Adding LLM tracking with token + cost accounting
  - Example 3: All five decorator types in a single workflow
  - Example 4: Error handling — how FlowLens records failures
  - Example 5: Accessing the trace object for custom analysis
"""

import asyncio
import random
import sys
import os

# Make the script runnable from the project root directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ─────────────────────────────────────────────────────────────────────────────
# ANSI colour codes — just for making the output readable.
# You do not need these in your own code.
# ─────────────────────────────────────────────────────────────────────────────
CYAN  = "\033[96m"
GREEN = "\033[92m"
BOLD  = "\033[1m"
DIM   = "\033[2m"
RESET = "\033[0m"


def heading(title: str) -> None:
    """Print a section heading."""
    print(f"\n{CYAN}{BOLD}{'─' * 60}{RESET}")
    print(f"{CYAN}{BOLD}  {title}{RESET}")
    print(f"{CYAN}{BOLD}{'─' * 60}{RESET}\n")


def note(text: str) -> None:
    print(f"  {DIM}# {text}{RESET}")


# ─────────────────────────────────────────────────────────────────────────────
# EXAMPLE 1 — The Simplest Possible Example
# ─────────────────────────────────────────────────────────────────────────────
#
# Two things are needed:
#   1. A FlowLens instance  (sets the global tracer singleton)
#   2. A @trace_agent decorator on your agent's entry-point function
#
# That is everything. FlowLens automatically:
#   - Creates a trace when the function is called
#   - Creates a root span (kind = AGENT)
#   - Records start time, end time, and duration
#   - Captures any unhandled exception (without swallowing it)
#   - Exports the trace when the function returns

from flowlens import FlowLens, trace_agent, trace_tool, trace_llm, trace_chain, trace_retrieval
from flowlens.sdk.models import Trace


# Step 1: Create a FlowLens instance.
# This registers itself as the global singleton so all decorators can find it.
#
# export_to="console" prints a compact summary to stdout after each trace.
# Other options: "jsonl" (write to file), "http" (send to FlowLens server),
#               "otlp" (send to Jaeger / Grafana Tempo / etc.)
#
lens = FlowLens(
    service_name="quickstart-demo",  # appears in trace metadata
    export_to="console",              # print traces to stdout
    verbose=False,                    # set True for detailed span-by-span output
)


# Step 2: Decorate the agent entry-point with @trace_agent.
# The `name` argument becomes the root span name in the trace.
@trace_agent(name="hello_agent")
async def hello_agent(message: str) -> str:
    """The simplest possible agent — just return a greeting."""
    # Simulate a tiny bit of work
    await asyncio.sleep(0.05)
    return f"Hello, {message}!"


async def example_1() -> None:
    heading("Example 1 — Minimum viable tracing")
    note("One FlowLens instance + one @trace_agent decorator = full trace")
    note("")

    result = await hello_agent("FlowLens")

    print(f"  Agent returned: {GREEN}{result}{RESET}")
    print()
    note("The [FlowLens] line above is the exported trace summary.")
    note("Fields: trace_id, duration_ms, span count, token count, cost.")


# ─────────────────────────────────────────────────────────────────────────────
# EXAMPLE 2 — Adding LLM Call Tracking
# ─────────────────────────────────────────────────────────────────────────────
#
# @trace_llm wraps any function that calls an LLM.
# It automatically:
#   - Creates a span (kind = LLM)
#   - Records the model name
#   - Extracts token usage from the response object
#     (supports Anthropic, OpenAI, Google, Bedrock, LiteLLM response shapes)
#   - Calculates cost based on the model's pricing table
#
# The function must return an object that looks like an LLM response.
# For real code: just decorate the function that calls anthropic.messages.create()
# or openai.chat.completions.create().  FlowLens handles the rest.

class _MockLLMResponse:
    """Pretend this is the object returned by anthropic.messages.create()."""
    def __init__(self, text: str, input_tokens: int, output_tokens: int):
        self.content = [type("Block", (), {"text": text})()]
        # Anthropic SDK shape — FlowLens reads .usage.input_tokens / .output_tokens
        self.usage = type("Usage", (), {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        })()
        self.stop_reason = "end_turn"


@trace_llm(
    model="claude-sonnet-4-20250514",  # model name is used for cost calculation
    name="planner_llm",                 # span name (defaults to function name)
)
async def call_llm(prompt: str) -> _MockLLMResponse:
    """A mocked LLM call — in real code this calls the Anthropic/OpenAI SDK."""
    await asyncio.sleep(0.03)
    return _MockLLMResponse(
        text=f"Planned response for: {prompt}",
        input_tokens=random.randint(400, 800),   # mocked token counts
        output_tokens=random.randint(100, 250),
    )


@trace_agent(name="llm_tracking_agent")
async def llm_tracking_agent(task: str) -> str:
    """Agent that calls an LLM and returns its response."""
    # call_llm() is decorated with @trace_llm, so this call creates an LLM span
    response = await call_llm(task)
    # Access the text from the mocked response
    return response.content[0].text


async def example_2() -> None:
    heading("Example 2 — LLM call tracking with token + cost accounting")
    note("@trace_llm extracts token usage from the response object")
    note("and computes cost from a built-in pricing table (2026 models)")
    note("")

    result = await llm_tracking_agent("Summarise the latest AI research")

    print(f"  Agent result: {GREEN}{result[:60]}...{RESET}")
    print()
    note("Notice 'tokens' and 'cost' fields in the trace output above.")
    note("FlowLens supports: Anthropic, OpenAI, Google, Bedrock, LiteLLM response shapes.")


# ─────────────────────────────────────────────────────────────────────────────
# EXAMPLE 3 — All Five Decorator Types
# ─────────────────────────────────────────────────────────────────────────────
#
# FlowLens has five span kinds, each with its own decorator:
#
#   @trace_agent      — the outermost agent loop (creates the trace)
#   @trace_llm        — LLM calls (token + cost tracking)
#   @trace_tool       — external tool calls (search, APIs, databases)
#   @trace_chain      — multi-step pipelines (groups sub-spans)
#   @trace_retrieval  — RAG / vector search (records result count)
#
# You can nest them freely.  FlowLens automatically builds the parent-child
# tree from Python's async context variables.

@trace_retrieval(name="vector_search")  # kind = RETRIEVAL
async def vector_search(query: str) -> list[dict]:
    """Simulated vector similarity search — returns top-k documents."""
    await asyncio.sleep(0.02)
    return [
        {"id": "doc_1", "text": f"Document about {query}", "score": 0.93},
        {"id": "doc_2", "text": f"More context on {query}", "score": 0.87},
    ]


@trace_tool(name="web_search")  # kind = TOOL
async def web_search(query: str) -> list[str]:
    """Simulated web search — returns a list of result snippets."""
    await asyncio.sleep(0.03)
    return [
        f"Result 1: Recent news on {query}",
        f"Result 2: Expert opinion on {query}",
    ]


@trace_chain(name="rag_pipeline")  # kind = CHAIN — groups the sub-steps
async def rag_pipeline(query: str) -> dict:
    """
    A Retrieval-Augmented Generation pipeline.
    The @trace_chain decorator groups the sub-steps as child spans.
    """
    # Both of these calls create child spans under the "rag_pipeline" chain span
    docs = await vector_search(query)
    web = await web_search(query)

    context = "\n".join(d["text"] for d in docs) + "\n" + "\n".join(web)

    # The LLM synthesises using the retrieved context
    llm_response = await call_llm(f"Answer using context: {context[:100]}")

    return {
        "answer": llm_response.content[0].text,
        "sources": len(docs) + len(web),
    }


@trace_agent(name="full_pipeline_agent")  # kind = AGENT — trace root
async def full_pipeline_agent(question: str) -> dict:
    """Agent that demonstrates all five decorator types in one workflow."""
    # This call creates a CHAIN span which contains RETRIEVAL, TOOL, and LLM spans
    result = await rag_pipeline(question)
    return result


async def example_3() -> None:
    heading("Example 3 — All five decorator types in one workflow")
    note("Span tree:")
    note("  AGENT  full_pipeline_agent")
    note("    CHAIN  rag_pipeline")
    note("      RETRIEVAL  vector_search")
    note("      TOOL       web_search")
    note("      LLM        planner_llm")
    note("")

    result = await full_pipeline_agent("What is the state of agentic AI in 2026?")

    print(f"  Answer: {GREEN}{result['answer'][:80]}...{RESET}")
    print(f"  Sources used: {result['sources']}")
    print()
    note("Each nested decorator creates a child span under its parent.")
    note("FlowLens builds the parent-child tree automatically via contextvars.")


# ─────────────────────────────────────────────────────────────────────────────
# EXAMPLE 4 — Error Handling
# ─────────────────────────────────────────────────────────────────────────────
#
# FlowLens decorators never swallow exceptions.
# When a decorated function raises, FlowLens:
#   - Sets the span status to ERROR
#   - Records error_message and error_type
#   - Continues to propagate the exception to the caller
#
# The trace will contain both the error spans and any spans that succeeded
# before the error — giving you full visibility into failure cascades.

@trace_tool(name="flaky_tool")
async def flaky_tool(input: str) -> str:
    """A tool that fails on every other call."""
    await asyncio.sleep(0.01)
    raise ConnectionError(f"flaky_tool: connection refused (input='{input}')")


@trace_agent(name="error_demo_agent")
async def error_demo_agent(task: str) -> str:
    """Agent that calls a tool that always fails — shows error recording."""
    # Call the LLM first (succeeds)
    plan = await call_llm(task)
    plan_text = plan.content[0].text

    # Call the flaky tool — this raises and the span is marked ERROR
    # The exception propagates up to the agent span, which is also marked ERROR
    try:
        result = await flaky_tool(plan_text)
        return result
    except ConnectionError as exc:
        # In a real agent you might retry or fall back here.
        # FlowLens has already recorded the error span even though we caught it.
        return f"Recovered from error: {exc}"


async def example_4() -> None:
    heading("Example 4 — Error recording and recovery")
    note("FlowLens records errors without swallowing exceptions.")
    note("Even caught errors are visible in the trace.")
    note("")

    result = await error_demo_agent("Find the latest research paper")

    print(f"  Agent result: {GREEN}{result[:80]}{RESET}")
    print()
    note("Notice 'errors: 1' in the trace output above.")
    note("The LLM span is marked OK; the tool span is marked ERROR.")
    note("Causal DAG analysis can identify cascade failure chains.")


# ─────────────────────────────────────────────────────────────────────────────
# EXAMPLE 5 — Accessing the Trace Object
# ─────────────────────────────────────────────────────────────────────────────
#
# Sometimes you want to programmatically inspect the trace after it completes —
# for testing, custom dashboards, or running the FlowLens analysis engine.
#
# Use the `on_trace_complete` callback in FlowLens() to receive each Trace.
# The Trace object has properties: total_tokens, total_cost_usd, error_count,
# duration_ms, spans, etc.
#
# For deeper analysis, pass the Trace to:
#   build_causal_dag(trace)  → CausalDAG (root causes, cascade edges)
#   detect_patterns(trace, dag)  → list[DetectedPattern]
#   TraceAdvisor(trace, dag, patterns)  → recommendations, severity score

_captured_traces: list[Trace] = []


def _on_trace(trace: Trace) -> None:
    """Callback that fires when each trace completes."""
    _captured_traces.append(trace)


async def example_5() -> None:
    heading("Example 5 — Accessing the Trace object for custom analysis")
    note("Pass on_trace_complete= to receive each Trace when it finishes.")
    note("")

    # Create a second FlowLens instance (replaces the global singleton)
    # with a callback to capture traces
    lens2 = FlowLens(
        service_name="quickstart-demo",
        export_to="console",
        verbose=False,
        on_trace_complete=_on_trace,   # ← callback receives each Trace
    )

    # Run the agent — the callback fires when it finishes
    await full_pipeline_agent("Demonstrate trace callback")

    lens2.shutdown()

    if _captured_traces:
        t = _captured_traces[-1]
        print()
        print(f"  {DIM}Trace object properties:{RESET}")
        print(f"    trace_id      : {t.trace_id[:24]}...")
        print(f"    span_count    : {len(t.spans)}")
        print(f"    total_tokens  : {t.total_tokens}")
        print(f"    total_cost    : ${t.total_cost_usd:.5f}")
        print(f"    duration_ms   : {t.duration_ms:.1f} ms")
        print(f"    error_count   : {t.error_count}")
        print(f"    has_errors    : {t.has_errors}")
        print()
        note("You can pass this Trace to the analysis engine:")
        note("  from flowlens.analysis.dag_builder import build_causal_dag")
        note("  from flowlens.analysis.patterns import detect_patterns")
        note("  from flowlens.analysis.advisor import TraceAdvisor")
        print()
        note("See examples/demo_agent.py for a complete analysis walkthrough.")


# ─────────────────────────────────────────────────────────────────────────────
# Run all examples
# ─────────────────────────────────────────────────────────────────────────────

async def main() -> None:
    print(f"\n{CYAN}{BOLD}{'═' * 60}")
    print("  FlowLens Quickstart Tutorial")
    print(f"{'═' * 60}{RESET}")
    print()
    print(f"  {DIM}Five progressive examples from zero to full observability.{RESET}")

    await example_1()   # minimal: @trace_agent only
    await example_2()   # adds @trace_llm with token tracking
    await example_3()   # all five decorator types
    await example_4()   # error recording
    await example_5()   # accessing the Trace object

    # Clean up all tracer resources
    lens.shutdown()

    print(f"\n{GREEN}{BOLD}  All examples complete!{RESET}")
    print()
    print(f"  {DIM}Next steps:")
    print(f"    python examples/demo_agent.py         — full RAG research agent")
    print(f"    python examples/auto_instrument_example.py  — zero-code tracing")
    print(f"    python examples/multi_trace_analysis.py     — fleet-wide analysis")
    print(f"    python examples/server_demo.py              — API server walkthrough")
    print(f"  {RESET}")


if __name__ == "__main__":
    asyncio.run(main())
