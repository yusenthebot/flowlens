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

    @trace_tool(name="search")
    async def search(query):
        ...
"""

__version__ = "0.5.0"

from flowlens.sdk.tracer import FlowLens, get_current_trace, get_current_span
from flowlens.sdk.decorators import (
    trace_agent,
    trace_tool,
    trace_llm,
    trace_llm_stream,
    trace_chain,
    trace_retrieval,
    trace_embedding,
)
from flowlens.sdk.context import (
    get_baggage,
    set_baggage,
    get_baggage_item,
    set_baggage_item,
)
from flowlens.sdk.models import SpanEvent, SpanKind
from flowlens.sdk.auto_instrument import auto_instrument
from flowlens.sdk.exporters import (
    OTLPExporter,
    OTLPBatchExporter,
    CSVExporter,
    JSONLStreamExporter,
)
from flowlens.plugins import BasePlugin, PluginRegistry, discover_plugins, load_plugin

__all__ = [
    "FlowLens",
    "trace_agent",
    "trace_tool",
    "trace_llm",
    "trace_llm_stream",
    "trace_chain",
    "trace_retrieval",
    "trace_embedding",
    "get_current_trace",
    "get_current_span",
    "get_baggage",
    "set_baggage",
    "get_baggage_item",
    "set_baggage_item",
    "auto_instrument",
    "SpanEvent",
    "SpanKind",
    "OTLPExporter",
    "OTLPBatchExporter",
    "CSVExporter",
    "JSONLStreamExporter",
    "BasePlugin",
    "PluginRegistry",
    "discover_plugins",
    "load_plugin",
]
