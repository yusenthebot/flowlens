"""Tests for FlowLens decorators — trace_agent, trace_llm, trace_tool."""
import pytest

from flowlens import FlowLens, trace_agent, trace_llm, trace_tool
from flowlens.sdk.exporters import CallbackExporter
from flowlens.sdk.models import SpanKind, SpanStatus, Trace


@pytest.fixture
def captured_traces():
    """设置 FlowLens 并捕获 trace"""
    traces: list[Trace] = []

    def capture(trace: Trace):
        traces.append(trace)

    lens = FlowLens(service_name="test")
    lens.set_exporter(CallbackExporter(capture))
    yield traces
    lens.shutdown()


class TestTraceAgent:
    @pytest.mark.asyncio
    async def test_agent_creates_trace(self, captured_traces):
        @trace_agent(name="test_bot")
        async def my_agent():
            return "done"

        result = await my_agent()
        assert result == "done"
        assert len(captured_traces) == 1

        trace = captured_traces[0]
        assert len(trace.spans) == 1
        assert trace.spans[0].name == "test_bot"
        assert trace.spans[0].kind == SpanKind.AGENT
        assert trace.spans[0].status == SpanStatus.OK

    @pytest.mark.asyncio
    async def test_agent_records_error(self, captured_traces):
        @trace_agent(name="bad_bot")
        async def failing_agent():
            raise RuntimeError("crashed")

        with pytest.raises(RuntimeError, match="crashed"):
            await failing_agent()

        assert len(captured_traces) == 1
        trace = captured_traces[0]
        assert trace.has_errors
        assert trace.spans[0].status == SpanStatus.ERROR
        assert trace.spans[0].error_message == "crashed"
        assert trace.spans[0].error_type == "RuntimeError"


class TestTraceLLM:
    @pytest.mark.asyncio
    async def test_llm_records_tokens(self, captured_traces):
        class FakeResponse:
            class usage:
                input_tokens = 500
                output_tokens = 200

        @trace_agent(name="agent")
        async def agent():
            @trace_llm(model="claude-sonnet-4-20250514", name="think")
            async def think():
                return FakeResponse()

            return await think()

        await agent()

        trace = captured_traces[0]
        llm_spans = [s for s in trace.spans if s.kind == SpanKind.LLM]
        assert len(llm_spans) == 1
        assert llm_spans[0].token_usage is not None
        assert llm_spans[0].token_usage.input_tokens == 500
        assert llm_spans[0].token_usage.output_tokens == 200
        assert llm_spans[0].token_usage.total_cost_usd > 0

    @pytest.mark.asyncio
    async def test_llm_parent_child(self, captured_traces):
        @trace_agent(name="agent")
        async def agent():
            @trace_llm(model="test", name="llm_call")
            async def llm():
                return "response"

            return await llm()

        await agent()
        trace = captured_traces[0]
        agent_span = trace.spans[0]
        llm_span = trace.spans[1]
        assert llm_span.parent_span_id == agent_span.span_id


class TestTraceTool:
    @pytest.mark.asyncio
    async def test_tool_records_params(self, captured_traces):
        @trace_agent(name="agent")
        async def agent():
            @trace_tool(name="search")
            async def search(query: str, limit: int = 10):
                return {"results": [query]}

            return await search("hello", limit=5)

        await agent()
        trace = captured_traces[0]
        tool_spans = [s for s in trace.spans if s.kind == SpanKind.TOOL]
        assert len(tool_spans) == 1
        assert "tool.input.query" in tool_spans[0].attributes
        assert tool_spans[0].attributes["tool.input.query"] == "hello"

    @pytest.mark.asyncio
    async def test_tool_error_recorded(self, captured_traces):
        @trace_agent(name="agent")
        async def agent():
            @trace_tool(name="bad_tool")
            async def bad():
                raise ConnectionError("network down")

            try:
                await bad()
            except ConnectionError:
                pass

        await agent()
        trace = captured_traces[0]
        tool_spans = [s for s in trace.spans if s.kind == SpanKind.TOOL]
        assert len(tool_spans) == 1
        assert tool_spans[0].status == SpanStatus.ERROR
        assert "network down" in tool_spans[0].error_message

    @pytest.mark.asyncio
    async def test_nested_spans(self, captured_traces):
        """Agent → LLM → Tool 三层嵌套"""

        @trace_agent(name="agent")
        async def agent():
            @trace_llm(model="test", name="plan")
            async def plan():
                @trace_tool(name="db_query")
                async def query():
                    return {"data": [1, 2, 3]}

                return await query()

            return await plan()

        await agent()
        trace = captured_traces[0]
        assert len(trace.spans) == 3

        agent_span = trace.spans[0]
        llm_span = trace.spans[1]
        tool_span = trace.spans[2]

        assert llm_span.parent_span_id == agent_span.span_id
        assert tool_span.parent_span_id == llm_span.span_id


class TestNoLensGraceful:
    @pytest.mark.asyncio
    async def test_no_lens_instance(self):
        """没有 FlowLens 实例时装饰器应该透明"""
        FlowLens._instance = None

        @trace_agent(name="bot")
        async def my_agent():
            return 42

        result = await my_agent()
        assert result == 42


class TestSyncFunctions:
    def test_trace_agent_sync_function(self, captured_traces):
        """@trace_agent works with sync functions"""
        @trace_agent(name="sync_bot")
        def sync_agent():
            return "sync_result"

        result = sync_agent()
        assert result == "sync_result"
        assert len(captured_traces) == 1
        assert captured_traces[0].spans[0].name == "sync_bot"
        assert captured_traces[0].spans[0].kind == SpanKind.AGENT

    def test_trace_llm_sync_function(self, captured_traces):
        """@trace_llm works with sync functions"""
        class FakeResponse:
            class usage:
                input_tokens = 100
                output_tokens = 50

        @trace_agent(name="agent")
        def agent():
            @trace_llm(model="claude-sonnet-4-20250514", name="sync_llm")
            def call_llm():
                return FakeResponse()

            return call_llm()

        agent()

        trace = captured_traces[0]
        llm_spans = [s for s in trace.spans if s.kind == SpanKind.LLM]
        assert len(llm_spans) == 1
        assert llm_spans[0].token_usage is not None

    def test_trace_tool_sync_function(self, captured_traces):
        """@trace_tool works with sync functions"""
        @trace_agent(name="agent")
        def agent():
            @trace_tool(name="sync_tool")
            def sync_tool(x: int):
                return x * 2

            return sync_tool(5)

        result = agent()
        assert result == 10

        trace = captured_traces[0]
        tool_spans = [s for s in trace.spans if s.kind == SpanKind.TOOL]
        assert len(tool_spans) == 1
        assert "tool.input.x" in tool_spans[0].attributes


class TestDecoratorWithoutFlowLens:
    @pytest.mark.asyncio
    async def test_decorator_without_instance_no_errors(self):
        """Decorators work even if FlowLens._instance is None"""
        FlowLens._instance = None

        @trace_llm(model="test", name="orphan_llm")
        async def orphan_llm():
            return "orphan"

        result = await orphan_llm()
        assert result == "orphan"

    def test_sync_decorator_without_instance(self):
        """Sync decorators work without instance"""
        FlowLens._instance = None

        @trace_tool(name="orphan_tool")
        def orphan_tool():
            return 42

        result = orphan_tool()
        assert result == 42


class TestDecoratorExceptions:
    @pytest.mark.asyncio
    async def test_async_decorator_exception_propagation(self, captured_traces):
        """Exceptions in decorated async functions are re-raised"""
        @trace_agent(name="failing_agent")
        async def failing():
            raise ValueError("test error")

        with pytest.raises(ValueError, match="test error"):
            await failing()

        # Trace should still be recorded with ERROR status
        assert len(captured_traces) == 1
        assert captured_traces[0].spans[0].status == SpanStatus.ERROR
        assert "test error" in captured_traces[0].spans[0].error_message

    def test_sync_decorator_exception_propagation(self, captured_traces):
        """Exceptions in decorated sync functions are re-raised"""
        @trace_agent(name="sync_fail")
        def failing_sync():
            raise RuntimeError("sync error")

        with pytest.raises(RuntimeError, match="sync error"):
            failing_sync()

        assert len(captured_traces) == 1
        assert captured_traces[0].spans[0].status == SpanStatus.ERROR

    @pytest.mark.asyncio
    async def test_llm_decorator_exception_caught(self, captured_traces):
        """LLM decorator records exception and re-raises"""
        @trace_agent(name="agent")
        async def agent():
            @trace_llm(model="test")
            async def bad_llm():
                raise ConnectionError("network issue")

            try:
                await bad_llm()
            except ConnectionError:
                pass

        await agent()

        trace = captured_traces[0]
        llm_span = [s for s in trace.spans if s.kind == SpanKind.LLM][0]
        assert llm_span.status == SpanStatus.ERROR
        assert llm_span.error_type == "ConnectionError"

    @pytest.mark.asyncio
    async def test_tool_decorator_exception_caught(self, captured_traces):
        """Tool decorator records exception and re-raises"""
        @trace_agent(name="agent")
        async def agent():
            @trace_tool(name="bad_tool")
            async def bad():
                raise TimeoutError("took too long")

            try:
                await bad()
            except TimeoutError:
                pass

        await agent()

        trace = captured_traces[0]
        tool_span = [s for s in trace.spans if s.kind == SpanKind.TOOL][0]
        assert tool_span.status == SpanStatus.ERROR
        assert tool_span.error_type == "TimeoutError"


class TestDecoratorMetadata:
    @pytest.mark.asyncio
    async def test_agent_with_metadata(self, captured_traces):
        """@trace_agent accepts metadata parameter"""
        @trace_agent(name="bot", metadata={"env": "test", "version": "1.0"})
        async def bot():
            return "done"

        await bot()

        trace = captured_traces[0]
        assert trace.metadata["env"] == "test"
        assert trace.metadata["version"] == "1.0"

    @pytest.mark.asyncio
    async def test_agent_with_attributes(self, captured_traces):
        """@trace_agent passes **attrs as span attributes"""
        @trace_agent(name="bot", custom_attr="value", flag=True)
        async def bot():
            return "done"

        await bot()

        trace = captured_traces[0]
        agent_span = trace.spans[0]
        assert agent_span.attributes.get("custom_attr") == "value"
        assert agent_span.attributes.get("flag") is True

    @pytest.mark.asyncio
    async def test_llm_with_attributes(self, captured_traces):
        """@trace_llm passes **attrs as span attributes"""
        class FakeResponse:
            class usage:
                input_tokens = 100
                output_tokens = 50

        @trace_agent(name="agent")
        async def agent():
            @trace_llm(model="claude-sonnet-4-20250514", custom="attr")
            async def llm():
                return FakeResponse()

            return await llm()

        await agent()

        trace = captured_traces[0]
        llm_span = [s for s in trace.spans if s.kind == SpanKind.LLM][0]
        assert llm_span.attributes.get("custom") == "attr"
