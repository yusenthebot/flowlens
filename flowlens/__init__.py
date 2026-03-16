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

__version__ = "1.0.0"

from flowlens.evaluation import (
    ContainsKeywords,
    CostThreshold,
    EvalResult,
    EvaluationRunner,
    Evaluator,
    ExactMatch,
    JsonSchemaValid,
    LatencyThreshold,
    LLMJudge,
)
from flowlens.plugins import BasePlugin, PluginRegistry, discover_plugins, load_plugin
from flowlens.sdk.auto_instrument import auto_instrument
from flowlens.sdk.context import (
    get_baggage,
    get_baggage_item,
    set_baggage,
    set_baggage_item,
)
from flowlens.sdk.decorators import (
    trace_agent,
    trace_chain,
    trace_embedding,
    trace_llm,
    trace_llm_stream,
    trace_retrieval,
    trace_tool,
)
from flowlens.sdk.exporters import (
    CSVExporter,
    JSONLStreamExporter,
    OTLPBatchExporter,
    OTLPExporter,
)
from flowlens.sdk.models import SpanEvent, SpanKind
from flowlens.sdk.tracer import FlowLens, get_current_span, get_current_trace

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
    # Evaluation
    "EvalResult",
    "Evaluator",
    "ExactMatch",
    "ContainsKeywords",
    "JsonSchemaValid",
    "CostThreshold",
    "LatencyThreshold",
    "LLMJudge",
    "EvaluationRunner",
]
