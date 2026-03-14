"""Tests for @trace_llm_stream — streaming LLM decorator."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from flowlens import FlowLens, trace_agent, trace_llm_stream
from flowlens.sdk.models import Trace, SpanKind, SpanStatus
from flowlens.sdk.exporters import CallbackExporter
from flowlens.sdk.decorators import _estimate_tokens_from_text


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def captured_traces():
    traces: list[Trace] = []

    def capture(trace: Trace):
        traces.append(trace)

    lens = FlowLens(service_name="stream-test")
    lens.set_exporter(CallbackExporter(capture))
    yield traces
    lens.shutdown()


# ---------------------------------------------------------------------------
# Helpers — fake streaming chunks
# ---------------------------------------------------------------------------

def _anthropic_chunks(input_toks: int = 100, output_toks: int = 50):
    """Yield fake Anthropic stream chunks in canonical order."""
    # message_start
    start = MagicMock()
    start.type = "message_start"
    start.message.usage.input_tokens = input_toks
    yield start

    # content_block_delta
    delta1 = MagicMock()
    delta1.type = "content_block_delta"
    delta1.delta.text = "Hello "
    yield delta1

    delta2 = MagicMock()
    delta2.type = "content_block_delta"
    delta2.delta.text = "world"
    yield delta2

    # message_delta (output usage)
    md = MagicMock()
    md.type = "message_delta"
    md.usage.output_tokens = output_toks
    yield md


def _openai_chunks(prompt_toks: int = 80, completion_toks: int = 30):
    """Yield fake OpenAI streaming chunks."""
    # Normal content chunks
    for word in ["Hi ", "there"]:
        chunk = MagicMock()
        chunk.type = None
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta.content = word
        chunk.usage = None
        yield chunk

    # Final chunk with usage (requires stream_options={"include_usage": True})
    final = MagicMock()
    final.type = None
    final.choices = [MagicMock()]
    final.choices[0].delta.content = ""
    final.usage = MagicMock()
    final.usage.prompt_tokens = prompt_toks
    final.usage.completion_tokens = completion_toks
    yield final


# ---------------------------------------------------------------------------
# Async generator tests
# ---------------------------------------------------------------------------

class TestTraceLlmStreamAsync:
    @pytest.mark.asyncio
    async def test_anthropic_stream_tokens(self, captured_traces):
        @trace_agent(name="agent")
        async def agent():
            @trace_llm_stream(model="claude-sonnet-4", name="stream_call")
            async def stream():
                for chunk in _anthropic_chunks(input_toks=100, output_toks=50):
                    yield chunk

            chunks = []
            async for c in stream():
                chunks.append(c)
            return chunks

        chunks = await agent()
        assert len(chunks) == 4  # start + 2 deltas + message_delta

        trace = captured_traces[0]
        llm_spans = [s for s in trace.spans if s.kind == SpanKind.LLM]
        assert len(llm_spans) == 1
        span = llm_spans[0]
        assert span.status == SpanStatus.OK
        assert span.token_usage is not None
        assert span.token_usage.input_tokens == 100
        assert span.token_usage.output_tokens == 50
        assert span.token_usage.total_tokens == 150
        assert span.attributes["gen_ai.streaming"] is True

    @pytest.mark.asyncio
    async def test_openai_stream_tokens(self, captured_traces):
        @trace_agent(name="agent")
        async def agent():
            @trace_llm_stream(model="gpt-4.1", name="oai_stream")
            async def stream():
                for chunk in _openai_chunks(prompt_toks=80, completion_toks=30):
                    yield chunk

            all_chunks = []
            async for c in stream():
                all_chunks.append(c)
            return all_chunks

        await agent()
        trace = captured_traces[0]
        llm_spans = [s for s in trace.spans if s.kind == SpanKind.LLM]
        span = llm_spans[0]
        assert span.token_usage is not None
        assert span.token_usage.input_tokens == 80
        assert span.token_usage.output_tokens == 30

    @pytest.mark.asyncio
    async def test_stream_records_output_text(self, captured_traces):
        @trace_agent(name="agent")
        async def agent():
            @trace_llm_stream(model="claude-sonnet-4")
            async def stream():
                for chunk in _anthropic_chunks():
                    yield chunk

            async for _ in stream():
                pass

        await agent()
        trace = captured_traces[0]
        llm_spans = [s for s in trace.spans if s.kind == SpanKind.LLM]
        assert "gen_ai.response.text" in llm_spans[0].attributes
        assert "Hello" in llm_spans[0].attributes["gen_ai.response.text"]

    @pytest.mark.asyncio
    async def test_stream_error_recorded(self, captured_traces):
        @trace_agent(name="agent")
        async def agent():
            @trace_llm_stream(model="claude-sonnet-4", name="bad_stream")
            async def bad_stream():
                yield MagicMock(type="content_block_delta", delta=MagicMock(text="oops"))
                raise ConnectionError("stream interrupted")

            try:
                async for _ in bad_stream():
                    pass
            except ConnectionError:
                pass

        await agent()
        trace = captured_traces[0]
        llm_spans = [s for s in trace.spans if s.kind == SpanKind.LLM]
        assert llm_spans[0].status == SpanStatus.ERROR
        assert llm_spans[0].error_type == "ConnectionError"

    @pytest.mark.asyncio
    async def test_stream_passthrough_without_instance(self):
        """Without a FlowLens instance, the decorator is transparent."""
        FlowLens._instance = None

        @trace_llm_stream(model="claude-sonnet-4")
        async def stream():
            yield "chunk1"
            yield "chunk2"

        collected = []
        async for c in stream():
            collected.append(c)

        assert collected == ["chunk1", "chunk2"]

    @pytest.mark.asyncio
    async def test_stream_parent_child_relationship(self, captured_traces):
        @trace_agent(name="agent")
        async def agent():
            @trace_llm_stream(model="claude-sonnet-4", name="stream")
            async def stream():
                for c in _anthropic_chunks():
                    yield c

            async for _ in stream():
                pass

        await agent()
        trace = captured_traces[0]
        agent_span = trace.spans[0]
        llm_span = [s for s in trace.spans if s.kind == SpanKind.LLM][0]
        assert llm_span.parent_span_id == agent_span.span_id

    @pytest.mark.asyncio
    async def test_stream_fallback_token_estimation(self, captured_traces):
        """When no usage chunks are present, tokens are estimated from text."""
        @trace_agent(name="agent")
        async def agent():
            @trace_llm_stream(model="gpt-4o")
            async def stream():
                # Yield generic text chunks with no usage info
                for word in ["Hello", " world", " this is a test"]:
                    chunk = MagicMock(spec=[])
                    chunk.text = word
                    yield chunk

            async for _ in stream():
                pass

        await agent()
        trace = captured_traces[0]
        llm_spans = [s for s in trace.spans if s.kind == SpanKind.LLM]
        span = llm_spans[0]
        # Estimated tokens from "Hello world this is a test" (26 chars → ~6 tokens)
        assert span.token_usage is not None
        assert span.token_usage.output_tokens > 0


# ---------------------------------------------------------------------------
# Sync generator tests
# ---------------------------------------------------------------------------

class TestTraceLlmStreamSync:
    def test_sync_stream_anthropic_tokens(self, captured_traces):
        @trace_agent(name="agent")
        def agent():
            @trace_llm_stream(model="claude-sonnet-4", name="sync_stream")
            def stream():
                yield from _anthropic_chunks(input_toks=60, output_toks=20)

            return list(stream())

        chunks = agent()
        assert len(chunks) == 4

        trace = captured_traces[0]
        llm_spans = [s for s in trace.spans if s.kind == SpanKind.LLM]
        span = llm_spans[0]
        assert span.status == SpanStatus.OK
        assert span.token_usage.input_tokens == 60
        assert span.token_usage.output_tokens == 20

    def test_sync_stream_passthrough_without_instance(self):
        FlowLens._instance = None

        @trace_llm_stream(model="gpt-4.1")
        def stream():
            yield "a"
            yield "b"

        assert list(stream()) == ["a", "b"]

    def test_sync_stream_error_recorded(self, captured_traces):
        @trace_agent(name="agent")
        def agent():
            @trace_llm_stream(model="gpt-4.1", name="bad_sync")
            def bad():
                yield MagicMock(type="content_block_delta", delta=MagicMock(text="x"))
                raise TimeoutError("timeout")

            try:
                list(bad())
            except TimeoutError:
                pass

        agent()
        trace = captured_traces[0]
        llm_spans = [s for s in trace.spans if s.kind == SpanKind.LLM]
        assert llm_spans[0].status == SpanStatus.ERROR
        assert llm_spans[0].error_type == "TimeoutError"


# ---------------------------------------------------------------------------
# _estimate_tokens_from_text
# ---------------------------------------------------------------------------

class TestEstimateTokensFromText:
    def test_empty_string(self):
        assert _estimate_tokens_from_text("") == 0

    def test_short_string(self):
        # "Hello" = 5 chars → max(1, 5//4) = 1
        assert _estimate_tokens_from_text("Hello") == 1

    def test_longer_string(self):
        text = "a" * 400  # 400 chars → 100 tokens
        assert _estimate_tokens_from_text(text) == 100

    def test_minimum_one_token(self):
        assert _estimate_tokens_from_text("x") == 1

    def test_unicode_text(self):
        text = "你好世界" * 10  # 40 chars
        assert _estimate_tokens_from_text(text) == 10
