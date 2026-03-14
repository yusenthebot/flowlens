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

__version__ = "0.1.0"

from flowlens.sdk.tracer import FlowLens
from flowlens.sdk.decorators import trace_agent, trace_tool, trace_llm

__all__ = [
    "FlowLens",
    "trace_agent",
    "trace_tool",
    "trace_llm",
]
