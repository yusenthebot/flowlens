"""
FlowLens — Agent Observability Platform
Chrome DevTools for LLM Agents

Usage:
    from flowlens import FlowLens, trace_agent, trace_tool, trace_llm

    lens = FlowLens(service_name="my-agent")

    @trace_agent(name="my_bot")
    async def run(task):
        ...

    @trace_llm(model="claude-sonnet-4-20250514")
    async def think(messages):
        ...

    @trace_llm_stream(model="claude-sonnet-4-20250514")
    async def stream(messages):
        async for chunk in client.messages.stream(...):
            yield chunk

    @trace_tool(name="search")
    async def search(query):
        ...

    # Auto-instrument Anthropic / OpenAI without decorators
    from flowlens import auto_instrument
    auto_instrument(["anthropic", "openai"])
"""

__version__ = "0.1.0"

from flowlens.sdk.tracer import FlowLens, get_current_trace, get_current_span
from flowlens.sdk.decorators import (
    trace_agent,
    trace_tool,
    trace_llm,
    trace_llm_stream,
    trace_chain,
    trace_retrieval,
)
from flowlens.sdk.context import (
    get_baggage,
    set_baggage,
    get_baggage_item,
    set_baggage_item,
)
from flowlens.sdk.auto_instrument import auto_instrument
from flowlens.sdk.models import SpanEvent

__all__ = [
    # Tracer
    "FlowLens",
    "get_current_trace",
    "get_current_span",
    # Decorators
    "trace_agent",
    "trace_tool",
    "trace_llm",
    "trace_llm_stream",
    "trace_chain",
    "trace_retrieval",
    # Auto-instrumentation
    "auto_instrument",
    # Models
    "SpanEvent",
    # Baggage
    "get_baggage",
    "set_baggage",
    "get_baggage_item",
    "set_baggage_item",
]
