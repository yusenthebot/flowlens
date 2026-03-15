"""Advanced decorator tests for flowlens/sdk/decorators.py."""
from __future__ import annotations

import contextlib

import pytest

from flowlens import FlowLens, trace_agent, trace_llm, trace_tool
from flowlens.sdk.decorators import trace_llm_stream
from flowlens.sdk.exporters import CallbackExporter
from flowlens.sdk.models import SpanKind, SpanStatus, Trace

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def captured_traces():
    traces: list[Trace] = []

    def capture(trace: Trace):
        traces.append(trace)

    lens = FlowLens(service_name="test-adv")
    lens.set_exporter(CallbackExporter(capture))
    yield traces
    lens.shutdown()


# ---------------------------------------------------------------------------
# @trace_llm_stream with streaming=True (sync generator)
# ---------------------------------------------------------------------------

class TestTraceLLMStream:
    def test_sync_stream_yields_all_chunks(self, captured_traces):
        chunks = [f"tok{i}" for i in range(5)]

        @trace_agent(name="agent")
        def agent():
            @trace_llm_stream(model="gpt-4o", name="streamed")
            def llm_stream():
                yield from chunks

            return list(llm_stream())

        result = agent()
        assert result == chunks

        trace = captured_traces[0]
        llm_spans = [s for s in trace.spans if s.kind == SpanKind.LLM]
        assert len(llm_spans) == 1
        assert llm_spans[0].status == SpanStatus.OK

    def test_sync_stream_sets_streaming_attribute(self, captured_traces):
        @trace_agent(name="agent")
        def agent():
            @trace_llm_stream(model="gpt-4o", name="streamed")
            def llm_stream():
                yield "hello world"

            return list(llm_stream())

        agent()
        trace = captured_traces[0]
        llm_span = next(s for s in trace.spans if s.kind == SpanKind.LLM)
        assert llm_span.attributes.get("gen_ai.streaming") is True

    def test_sync_stream_estimates_tokens_from_text(self, captured_traces):
        """Chunks with a .text attribute trigger the token-estimation fallback path."""

        class TextChunk:
            def __init__(self, t: str):
                self.text = t

        @trace_agent(name="agent")
        def agent():
            @trace_llm_stream(model="gpt-4o", name="streamed")
            def llm_stream():
                # Yield a generic chunk with a .text attribute (fallback path)
                yield TextChunk("A" * 400)  # 400 chars → ~100 tokens

            return list(llm_stream())

        agent()
        trace = captured_traces[0]
        llm_span = next(s for s in trace.spans if s.kind == SpanKind.LLM)
        # Token usage should have been estimated via fallback heuristic
        assert llm_span.token_usage is not None
        assert llm_span.token_usage.output_tokens > 0

    @pytest.mark.asyncio
    async def test_async_stream_yields_all_chunks(self, captured_traces):
        chunks = ["a", "b", "c"]

        @trace_agent(name="agent")
        async def agent():
            @trace_llm_stream(model="claude-sonnet-4", name="async_streamed")
            async def llm_stream():
                for c in chunks:
                    yield c

            collected = []
            async for chunk in llm_stream():
                collected.append(chunk)
            return collected

        result = await agent()
        assert result == chunks

        trace = captured_traces[0]
        llm_spans = [s for s in trace.spans if s.kind == SpanKind.LLM]
        assert len(llm_spans) == 1
        assert llm_spans[0].status == SpanStatus.OK

    def test_sync_stream_records_error(self, captured_traces):
        @trace_agent(name="agent")
        def agent():
            @trace_llm_stream(model="gpt-4o", name="fail_stream")
            def llm_stream():
                yield "partial"
                raise RuntimeError("stream broke")

            return list(llm_stream())

        with pytest.raises(RuntimeError, match="stream broke"):
            agent()

        trace = captured_traces[0]
        llm_spans = [s for s in trace.spans if s.kind == SpanKind.LLM]
        assert len(llm_spans) == 1
        assert llm_spans[0].status == SpanStatus.ERROR


# ---------------------------------------------------------------------------
# @trace_tool with exception handling
# ---------------------------------------------------------------------------

class TestTraceToolExceptions:
    def test_exception_is_re_raised(self, captured_traces):
        @trace_agent(name="agent")
        def agent():
            @trace_tool(name="risky_tool")
            def risky():
                raise ValueError("bad input")

            risky()

        with pytest.raises(ValueError, match="bad input"):
            agent()

    def test_exception_recorded_on_span(self, captured_traces):
        @trace_agent(name="agent")
        def agent():
            @trace_tool(name="risky_tool")
            def risky():
                raise TypeError("type error")

            with contextlib.suppress(TypeError):
                risky()

        agent()
        trace = captured_traces[0]
        tool_spans = [s for s in trace.spans if s.kind == SpanKind.TOOL]
        assert len(tool_spans) == 1
        assert tool_spans[0].status == SpanStatus.ERROR
        assert tool_spans[0].error_message == "type error"
        assert tool_spans[0].error_type == "TypeError"

    @pytest.mark.asyncio
    async def test_async_tool_exception(self, captured_traces):
        @trace_agent(name="agent")
        async def agent():
            @trace_tool(name="async_risky")
            async def async_risky():
                raise OSError("async failed")

            with contextlib.suppress(OSError):
                await async_risky()

        await agent()
        trace = captured_traces[0]
        tool_spans = [s for s in trace.spans if s.kind == SpanKind.TOOL]
        assert len(tool_spans) == 1
        assert tool_spans[0].status == SpanStatus.ERROR
        assert tool_spans[0].error_type == "OSError"


# ---------------------------------------------------------------------------
# Nested decorators: agent → llm → tool
# ---------------------------------------------------------------------------

class TestNestedDecorators:
    @pytest.mark.asyncio
    async def test_nested_agent_llm_tool(self, captured_traces):
        class FakeUsage:
            input_tokens = 100
            output_tokens = 50

        class FakeResp:
            usage = FakeUsage()

        @trace_agent(name="outer_agent")
        async def agent():
            @trace_llm(model="claude-haiku-4", name="inner_llm")
            async def call_llm():
                @trace_tool(name="inner_tool")
                async def use_tool():
                    return "tool_result"

                await use_tool()
                return FakeResp()

            return await call_llm()

        await agent()

        trace = captured_traces[0]
        assert len(trace.spans) == 3

        agent_span = next(s for s in trace.spans if s.kind == SpanKind.AGENT)
        llm_span = next(s for s in trace.spans if s.kind == SpanKind.LLM)
        tool_span = next(s for s in trace.spans if s.kind == SpanKind.TOOL)

        # Parent-child hierarchy
        assert llm_span.parent_span_id == agent_span.span_id
        assert tool_span.parent_span_id == llm_span.span_id

        # All OK
        for span in trace.spans:
            assert span.status == SpanStatus.OK

    def test_sync_nested_agent_llm_tool(self, captured_traces):
        @trace_agent(name="sync_agent")
        def agent():
            @trace_llm(model="gpt-4o-mini", name="sync_llm")
            def call_llm():
                @trace_tool(name="sync_tool")
                def do_tool():
                    return 42

                do_tool()
                return {"usage": {"prompt_tokens": 10, "completion_tokens": 5}}

            return call_llm()

        result = agent()
        assert result == {"usage": {"prompt_tokens": 10, "completion_tokens": 5}}

        trace = captured_traces[0]
        assert len(trace.spans) == 3

        llm_span = next(s for s in trace.spans if s.kind == SpanKind.LLM)
        assert llm_span.token_usage is not None
        assert llm_span.token_usage.input_tokens == 10


# ---------------------------------------------------------------------------
# Async decorators
# ---------------------------------------------------------------------------

class TestAsyncDecorators:
    @pytest.mark.asyncio
    async def test_async_trace_agent(self, captured_traces):
        @trace_agent(name="async_agent")
        async def agent():
            return "async_result"

        result = await agent()
        assert result == "async_result"
        assert len(captured_traces) == 1
        assert captured_traces[0].spans[0].kind == SpanKind.AGENT

    @pytest.mark.asyncio
    async def test_async_trace_llm(self, captured_traces):
        class Resp:
            class usage:
                input_tokens = 50
                output_tokens = 25

        @trace_agent(name="ag")
        async def agent():
            @trace_llm(model="gpt-4o", name="async_llm")
            async def llm():
                return Resp()
            return await llm()

        await agent()
        trace = captured_traces[0]
        llm_span = next(s for s in trace.spans if s.kind == SpanKind.LLM)
        assert llm_span.token_usage.input_tokens == 50

    @pytest.mark.asyncio
    async def test_async_trace_tool_returns_value(self, captured_traces):
        @trace_agent(name="ag")
        async def agent():
            @trace_tool(name="calc")
            async def calc(x: int, y: int) -> int:
                return x + y
            return await calc(3, 4)

        result = await agent()
        assert result == 7

        trace = captured_traces[0]
        tool_span = next(s for s in trace.spans if s.kind == SpanKind.TOOL)
        assert tool_span.attributes.get("tool.input.x") is not None


# ---------------------------------------------------------------------------
# Decorator with custom attributes
# ---------------------------------------------------------------------------

class TestCustomAttributes:
    def test_trace_llm_custom_attributes(self, captured_traces):
        @trace_agent(name="ag")
        def agent():
            @trace_llm(model="gpt-4o", name="llm_custom", temperature=0.7, top_p=0.9)
            def llm():
                return "hello"
            return llm()

        agent()
        trace = captured_traces[0]
        llm_span = next(s for s in trace.spans if s.kind == SpanKind.LLM)
        assert llm_span.attributes.get("temperature") == 0.7
        assert llm_span.attributes.get("top_p") == 0.9

    def test_trace_tool_custom_attributes(self, captured_traces):
        @trace_agent(name="ag")
        def agent():
            @trace_tool(name="search", source="web", max_results=5)
            def search(query: str):
                return []
            return search("flowlens")

        agent()
        trace = captured_traces[0]
        tool_span = next(s for s in trace.spans if s.kind == SpanKind.TOOL)
        assert tool_span.attributes.get("source") == "web"
        assert tool_span.attributes.get("max_results") == 5

    def test_trace_tool_captures_input_params(self, captured_traces):
        @trace_agent(name="ag")
        def agent():
            @trace_tool(name="greet")
            def greet(name: str, greeting: str = "Hello") -> str:
                return f"{greeting}, {name}!"
            return greet("Alice", greeting="Hi")

        result = agent()
        assert result == "Hi, Alice!"

        trace = captured_traces[0]
        tool_span = next(s for s in trace.spans if s.kind == SpanKind.TOOL)
        assert "Alice" in tool_span.attributes.get("tool.input.name", "")
        assert "Hi" in tool_span.attributes.get("tool.input.greeting", "")

    def test_gen_ai_system_detected_for_claude(self, captured_traces):
        @trace_agent(name="ag")
        def agent():
            @trace_llm(model="claude-sonnet-4-20250514", name="claude_call")
            def llm():
                return "ok"
            return llm()

        agent()
        trace = captured_traces[0]
        llm_span = next(s for s in trace.spans if s.kind == SpanKind.LLM)
        assert llm_span.attributes.get("gen_ai.system") == "anthropic"

    def test_gen_ai_system_detected_for_openai(self, captured_traces):
        @trace_agent(name="ag")
        def agent():
            @trace_llm(model="gpt-4o", name="openai_call")
            def llm():
                return "ok"
            return llm()

        agent()
        trace = captured_traces[0]
        llm_span = next(s for s in trace.spans if s.kind == SpanKind.LLM)
        assert llm_span.attributes.get("gen_ai.system") == "openai"
