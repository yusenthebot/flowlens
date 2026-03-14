"""Tests for flowlens.sdk.auto_instrument — monkey-patching LLM libraries."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from flowlens import FlowLens, auto_instrument
from flowlens.sdk import auto_instrument as ai_module
from flowlens.sdk.exporters import CallbackExporter
from flowlens.sdk.models import SpanKind, SpanStatus, Trace

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_patched_registry():
    """Clear the _patched registry between tests to avoid cross-test bleed."""
    original = ai_module._patched.copy()
    ai_module._patched.clear()
    yield
    ai_module._patched.clear()
    ai_module._patched.update(original)


@pytest.fixture
def captured_traces():
    """Set up FlowLens with a CallbackExporter and yield the captured list."""
    traces: list[Trace] = []

    def capture(trace: Trace):
        traces.append(trace)

    lens = FlowLens(service_name="auto-instrument-test")
    lens.set_exporter(CallbackExporter(capture))
    yield traces
    lens.shutdown()


# ---------------------------------------------------------------------------
# auto_instrument() — unknown / idempotency
# ---------------------------------------------------------------------------

class TestAutoInstrumentBasic:
    def test_unknown_library_logs_warning(self):
        import logging
        logger = logging.getLogger("flowlens.sdk.auto_instrument")
        with patch.object(logger, "warning") as mock_warn:
            auto_instrument(["not_a_real_library"])
        mock_warn.assert_called_once()
        assert "not_a_real_library" in str(mock_warn.call_args)

    def test_idempotent_patch(self):
        """Calling auto_instrument twice for the same lib must not double-patch."""
        # Simulate already patched by adding to registry
        ai_module._patched.add("anthropic")
        # Should be a no-op (no AttributeError raised)
        auto_instrument(["anthropic"])
        assert "anthropic" in ai_module._patched

    def test_missing_library_silently_skipped(self):
        """If a library is not installed, auto_instrument must not raise."""
        with patch.dict("sys.modules", {"anthropic": None}):
            # Should not raise ImportError
            auto_instrument(["anthropic"])


# ---------------------------------------------------------------------------
# _build_span_attrs
# ---------------------------------------------------------------------------

class TestBuildSpanAttrs:
    def test_basic_attrs(self):
        from flowlens.sdk.auto_instrument import _build_span_attrs
        attrs = _build_span_attrs("gpt-4.1", "openai", {"model": "gpt-4.1"})
        assert attrs["gen_ai.system"] == "openai"
        assert attrs["gen_ai.request.model"] == "gpt-4.1"

    def test_messages_captured_and_truncated(self):
        from flowlens.sdk.auto_instrument import _build_span_attrs
        long_messages = [{"role": "user", "content": "x" * 1000}]
        attrs = _build_span_attrs("gpt-4.1", "openai", {"messages": long_messages})
        assert "gen_ai.request.messages" in attrs
        assert len(attrs["gen_ai.request.messages"]) <= 503  # 500 + "..."

    def test_temperature_and_max_tokens_captured(self):
        from flowlens.sdk.auto_instrument import _build_span_attrs
        attrs = _build_span_attrs(
            "claude-sonnet-4",
            "anthropic",
            {"temperature": 0.7, "max_tokens": 1024},
        )
        assert attrs["gen_ai.request.temperature"] == 0.7
        assert attrs["gen_ai.request.max_tokens"] == 1024


# ---------------------------------------------------------------------------
# _extract_usage_from_response (used by the wrap helpers)
# ---------------------------------------------------------------------------

class TestExtractUsageFromResponse:
    def _make_span(self):
        from flowlens.sdk.models import Span
        return Span(name="test_span", kind=SpanKind.LLM)

    def test_anthropic_usage(self):
        from flowlens.sdk.auto_instrument import _extract_usage_from_response
        span = self._make_span()
        response = MagicMock()
        response.usage.input_tokens = 100
        response.usage.output_tokens = 50
        _extract_usage_from_response(response, "claude-sonnet-4", span)
        assert span.token_usage is not None
        assert span.token_usage.input_tokens == 100
        assert span.token_usage.output_tokens == 50

    def test_openai_dict_usage(self):
        from flowlens.sdk.auto_instrument import _extract_usage_from_response
        span = self._make_span()
        response = {"usage": {"prompt_tokens": 200, "completion_tokens": 80}}
        _extract_usage_from_response(response, "gpt-4.1", span)
        assert span.token_usage is not None
        assert span.token_usage.input_tokens == 200
        assert span.token_usage.output_tokens == 80

    def test_langchain_response_metadata(self):
        from flowlens.sdk.auto_instrument import _extract_usage_from_response
        span = self._make_span()
        response = MagicMock()
        del response.usage  # ensure no .usage
        response.response_metadata = {
            "token_usage": {"prompt_tokens": 30, "completion_tokens": 10}
        }
        _extract_usage_from_response(response, "gpt-4o", span)
        assert span.token_usage is not None
        assert span.token_usage.input_tokens == 30
        assert span.token_usage.output_tokens == 10

    def test_no_usage_records_nothing(self):
        from flowlens.sdk.auto_instrument import _extract_usage_from_response
        span = self._make_span()
        response = "plain string response"
        _extract_usage_from_response(response, "model", span)
        # No crash; token_usage may or may not be set depending on text length


# ---------------------------------------------------------------------------
# _wrap_sync_llm_call
# ---------------------------------------------------------------------------

class TestWrapSyncLlmCall:
    def test_creates_llm_span(self, captured_traces):
        from flowlens.sdk.auto_instrument import _wrap_sync_llm_call
        from flowlens.sdk.context import TraceContext
        from flowlens.sdk.tracer import FlowLens as FL

        lens = FL.get_instance()
        trace = lens.start_trace()

        response = MagicMock()
        response.usage.input_tokens = 10
        response.usage.output_tokens = 5

        def fake_fn(*args, **kwargs):
            return response

        with TraceContext(trace):
            result = _wrap_sync_llm_call(
                fake_fn,
                args=(),
                kwargs={"model": "gpt-4.1", "messages": []},
                model="gpt-4.1",
                system="openai",
                span_name="test.create",
            )

        lens.end_trace(trace)
        assert result is response
        assert len(captured_traces) == 1
        llm_spans = [s for s in captured_traces[0].spans if s.kind == SpanKind.LLM]
        assert len(llm_spans) == 1
        assert llm_spans[0].name == "test.create"
        assert llm_spans[0].status == SpanStatus.OK

    def test_records_error_on_exception(self, captured_traces):
        from flowlens.sdk.auto_instrument import _wrap_sync_llm_call
        from flowlens.sdk.context import TraceContext
        from flowlens.sdk.tracer import FlowLens as FL

        lens = FL.get_instance()
        trace = lens.start_trace()

        def bad_fn(*args, **kwargs):
            raise ValueError("API error")

        with TraceContext(trace), pytest.raises(ValueError, match="API error"):
            _wrap_sync_llm_call(
                bad_fn, args=(), kwargs={}, model="gpt-4.1",
                system="openai", span_name="bad.create",
            )

        lens.end_trace(trace)
        llm_spans = [s for s in captured_traces[0].spans if s.kind == SpanKind.LLM]
        assert llm_spans[0].status == SpanStatus.ERROR
        assert llm_spans[0].error_type == "ValueError"


# ---------------------------------------------------------------------------
# _wrap_async_llm_call
# ---------------------------------------------------------------------------

class TestWrapAsyncLlmCall:
    @pytest.mark.asyncio
    async def test_creates_llm_span_async(self, captured_traces):
        from flowlens.sdk.auto_instrument import _wrap_async_llm_call
        from flowlens.sdk.context import TraceContext
        from flowlens.sdk.tracer import FlowLens as FL

        lens = FL.get_instance()
        trace = lens.start_trace()

        response = MagicMock()
        response.usage.input_tokens = 20
        response.usage.output_tokens = 8

        async def fake_async_fn(*args, **kwargs):
            return response

        with TraceContext(trace):
            result = await _wrap_async_llm_call(
                fake_async_fn,
                args=(),
                kwargs={"model": "claude-sonnet-4", "messages": []},
                model="claude-sonnet-4",
                system="anthropic",
                span_name="anthropic.messages.create",
            )

        lens.end_trace(trace)
        assert result is response
        llm_spans = [s for s in captured_traces[0].spans if s.kind == SpanKind.LLM]
        assert llm_spans[0].status == SpanStatus.OK
        assert llm_spans[0].token_usage.input_tokens == 20

    @pytest.mark.asyncio
    async def test_records_error_async(self, captured_traces):
        from flowlens.sdk.auto_instrument import _wrap_async_llm_call
        from flowlens.sdk.context import TraceContext
        from flowlens.sdk.tracer import FlowLens as FL

        lens = FL.get_instance()
        trace = lens.start_trace()

        async def bad_async_fn(*args, **kwargs):
            raise RuntimeError("async error")

        with TraceContext(trace), pytest.raises(RuntimeError, match="async error"):
            await _wrap_async_llm_call(
                bad_async_fn, args=(), kwargs={}, model="claude-sonnet-4",
                system="anthropic", span_name="anthropic.messages.create",
            )

        lens.end_trace(trace)
        llm_spans = [s for s in captured_traces[0].spans if s.kind == SpanKind.LLM]
        assert llm_spans[0].status == SpanStatus.ERROR
        assert llm_spans[0].error_type == "RuntimeError"


# ---------------------------------------------------------------------------
# No FlowLens instance — passthrough mode
# ---------------------------------------------------------------------------

class TestAutoInstrumentNoInstance:
    def test_sync_wrap_without_instance_passes_through(self):
        from flowlens.sdk.auto_instrument import _wrap_sync_llm_call

        FlowLens._instance = None

        def fn(*a, **kw):
            return "result"

        result = _wrap_sync_llm_call(fn, (), {}, "model", "openai", "test")
        assert result == "result"

    @pytest.mark.asyncio
    async def test_async_wrap_without_instance_passes_through(self):
        from flowlens.sdk.auto_instrument import _wrap_async_llm_call

        FlowLens._instance = None

        async def fn(*a, **kw):
            return "async_result"

        result = await _wrap_async_llm_call(fn, (), {}, "model", "openai", "test")
        assert result == "async_result"


# ---------------------------------------------------------------------------
# OpenAI patching — legacy ChatCompletion API (sync)
# ---------------------------------------------------------------------------

class TestOpenAILegacyPatch:
    def test_patch_openai_legacy_create_skipped_gracefully(self):
        """If openai.ChatCompletion does not exist, no exception is raised."""
        import sys
        import types
        fake_openai = types.ModuleType("openai")
        # Expose OpenAI / AsyncOpenAI stubs so attribute access doesn't blow up
        fake_openai.OpenAI = type("OpenAI", (), {
            "chat": type("chat", (), {
                "completions": type("completions", (), {"create": lambda *a, **kw: None})()
            })()
        })
        fake_openai.AsyncOpenAI = type("AsyncOpenAI", (), {
            "chat": type("chat", (), {
                "completions": type("completions", (), {"create": lambda *a, **kw: None})()
            })()
        })
        # No ChatCompletion attr  → legacy patch must be silently skipped
        with patch.dict(sys.modules, {"openai": fake_openai}):
            ai_module._patched.discard("openai")
            auto_instrument(["openai"])
        assert "openai" in ai_module._patched

    def test_patch_openai_legacy_create_patched(self):
        """If openai.ChatCompletion.create exists it is wrapped."""
        import sys
        import types
        call_log: list[dict] = []

        def original_create(*args, **kwargs):
            call_log.append({"args": args, "kwargs": kwargs})
            return {"usage": {"prompt_tokens": 5, "completion_tokens": 3}}

        fake_chat_completion = type("ChatCompletion", (), {"create": staticmethod(original_create)})
        fake_openai = types.ModuleType("openai")
        fake_openai.OpenAI = type("OpenAI", (), {
            "chat": type("chat", (), {
                "completions": type("completions", (), {"create": lambda *a, **kw: None})()
            })()
        })
        fake_openai.AsyncOpenAI = type("AsyncOpenAI", (), {
            "chat": type("chat", (), {
                "completions": type("completions", (), {"create": lambda *a, **kw: None})()
            })()
        })
        fake_openai.ChatCompletion = fake_chat_completion

        with patch.dict(sys.modules, {"openai": fake_openai}):
            ai_module._patched.discard("openai")
            auto_instrument(["openai"])

        # The attribute should have been replaced with our wrapper
        assert fake_chat_completion.create is not original_create


# ---------------------------------------------------------------------------
# OpenAI sync streaming
# ---------------------------------------------------------------------------

class TestOpenAISyncStreaming:
    def test_wrap_sync_stream_yields_chunks(self, captured_traces):
        """_wrap_sync_stream_call yields all chunks and creates an LLM span."""
        from flowlens.sdk.auto_instrument import _wrap_sync_stream_call
        from flowlens.sdk.context import TraceContext
        from flowlens.sdk.tracer import FlowLens as FL

        lens = FL.get_instance()
        trace = lens.start_trace()

        # Simulate OpenAI-style streaming chunks
        class FakeUsage:
            prompt_tokens = 10
            completion_tokens = 5

        class FakeDelta:
            content = "hello"

        class FakeChoice:
            delta = FakeDelta()

        class FakeChunk:
            choices = [FakeChoice()]
            usage = None

        last_chunk = MagicMock()
        last_chunk.choices = []
        last_chunk.usage = FakeUsage()

        def fake_stream(*args, **kwargs):
            yield FakeChunk()
            yield last_chunk

        with TraceContext(trace):
            chunks = list(
                _wrap_sync_stream_call(
                    fake_stream,
                    args=(),
                    kwargs={"model": "gpt-4.1", "stream": True},
                    model="gpt-4.1",
                    system="openai",
                    span_name="openai.chat.completions.create",
                )
            )

        lens.end_trace(trace)
        assert len(chunks) == 2
        llm_spans = [s for s in captured_traces[0].spans if s.kind == SpanKind.LLM]
        assert len(llm_spans) == 1
        assert llm_spans[0].status == SpanStatus.OK
        assert llm_spans[0].attributes.get("gen_ai.streaming") is True

    def test_wrap_sync_stream_error_recorded(self, captured_traces):
        """Errors inside streaming generators are captured in the span."""
        from flowlens.sdk.auto_instrument import _wrap_sync_stream_call
        from flowlens.sdk.context import TraceContext
        from flowlens.sdk.tracer import FlowLens as FL

        lens = FL.get_instance()
        trace = lens.start_trace()

        def bad_stream(*args, **kwargs):
            yield MagicMock(choices=[], usage=None)
            raise ConnectionError("stream broken")

        with TraceContext(trace):
            gen = _wrap_sync_stream_call(
                bad_stream, args=(), kwargs={"stream": True},
                model="gpt-4.1", system="openai", span_name="test.stream",
            )
            with pytest.raises(ConnectionError, match="stream broken"):
                list(gen)

        lens.end_trace(trace)
        llm_spans = [s for s in captured_traces[0].spans if s.kind == SpanKind.LLM]
        assert llm_spans[0].status == SpanStatus.ERROR


# ---------------------------------------------------------------------------
# OpenAI async streaming
# ---------------------------------------------------------------------------

class TestOpenAIAsyncStreaming:
    @pytest.mark.asyncio
    async def test_wrap_async_stream_yields_chunks(self, captured_traces):
        from flowlens.sdk.auto_instrument import _wrap_async_stream_call
        from flowlens.sdk.context import TraceContext
        from flowlens.sdk.tracer import FlowLens as FL

        lens = FL.get_instance()
        trace = lens.start_trace()

        class FakeDelta:
            content = "world"

        class FakeChoice:
            delta = FakeDelta()

        class FakeChunk:
            choices = [FakeChoice()]
            usage = None

        async def fake_async_stream(*args, **kwargs):
            yield FakeChunk()
            yield FakeChunk()

        with TraceContext(trace):
            chunks = []
            async for chunk in _wrap_async_stream_call(
                fake_async_stream,
                args=(),
                kwargs={"model": "gpt-4.1", "stream": True},
                model="gpt-4.1",
                system="openai",
                span_name="openai.chat.completions.create",
            ):
                chunks.append(chunk)

        lens.end_trace(trace)
        assert len(chunks) == 2
        llm_spans = [s for s in captured_traces[0].spans if s.kind == SpanKind.LLM]
        assert llm_spans[0].status == SpanStatus.OK
        assert llm_spans[0].attributes.get("gen_ai.streaming") is True
        # Output text should have been accumulated
        assert "gen_ai.response.text" in llm_spans[0].attributes


# ---------------------------------------------------------------------------
# LangChain Chain.__call__ and AgentExecutor._call patching
# ---------------------------------------------------------------------------

class TestLangChainChainPatching:
    def test_patch_langchain_chain_call_graceful_without_langchain(self):
        """If langchain is not installed, no exception is raised."""
        import sys
        with patch.dict(sys.modules, {"langchain": None, "langchain_core": None,
                                       "langchain.chains": None, "langchain.chains.base": None,
                                       "langchain_core.language_models": None,
                                       "langchain_core.language_models.base": None}):
            ai_module._patched.discard("langchain")
            # Should silently skip, not raise
            auto_instrument(["langchain"])

    def test_wrap_sync_chain_call_creates_chain_span(self, captured_traces):
        """_wrap_sync_chain_call creates a CHAIN span with inputs/outputs."""
        from flowlens.sdk.auto_instrument import _wrap_sync_chain_call
        from flowlens.sdk.context import TraceContext
        from flowlens.sdk.tracer import FlowLens as FL

        lens = FL.get_instance()
        trace = lens.start_trace()

        def fake_chain_fn(self, inputs, **kwargs):
            return {"output": "the answer", "input": inputs.get("input", "")}

        class FakeChain:
            chain_type = "StuffDocumentsChain"

        fake_self = FakeChain()
        inputs = {"input": "What is the capital of France?"}

        with TraceContext(trace):
            result = _wrap_sync_chain_call(
                fake_chain_fn,
                args=(fake_self, inputs),
                kwargs={},
                chain_name="StuffDocumentsChain",
                span_name="langchain.chain.StuffDocumentsChain",
            )

        lens.end_trace(trace)
        assert result["output"] == "the answer"
        chain_spans = [s for s in captured_traces[0].spans if s.kind == SpanKind.CHAIN]
        assert len(chain_spans) == 1
        assert chain_spans[0].name == "langchain.chain.StuffDocumentsChain"
        assert chain_spans[0].status == SpanStatus.OK
        assert "chain.inputs" in chain_spans[0].attributes
        assert "chain.outputs" in chain_spans[0].attributes
        assert chain_spans[0].attributes["chain.name"] == "StuffDocumentsChain"

    def test_wrap_sync_chain_call_error_recorded(self, captured_traces):
        """Errors in chain calls are captured in the span."""
        from flowlens.sdk.auto_instrument import _wrap_sync_chain_call
        from flowlens.sdk.context import TraceContext
        from flowlens.sdk.tracer import FlowLens as FL

        lens = FL.get_instance()
        trace = lens.start_trace()

        def failing_chain(self, inputs, **kwargs):
            raise ValueError("chain failed")

        with TraceContext(trace), pytest.raises(ValueError, match="chain failed"):
            _wrap_sync_chain_call(
                failing_chain,
                args=(object(), {"input": "test"}),
                kwargs={},
                chain_name="FailingChain",
                span_name="langchain.chain.FailingChain",
            )

        lens.end_trace(trace)
        chain_spans = [s for s in captured_traces[0].spans if s.kind == SpanKind.CHAIN]
        assert chain_spans[0].status == SpanStatus.ERROR
        assert chain_spans[0].error_type == "ValueError"

    def test_wrap_sync_chain_call_passthrough_without_instance(self):
        """Without a FlowLens instance, chain calls pass through unchanged."""
        from flowlens.sdk.auto_instrument import _wrap_sync_chain_call

        FlowLens._instance = None

        def simple_chain(self, inputs):
            return {"result": "ok"}

        result = _wrap_sync_chain_call(
            simple_chain,
            args=(object(), {"q": "hello"}),
            kwargs={},
            chain_name="SimpleChain",
            span_name="langchain.chain.SimpleChain",
        )
        assert result == {"result": "ok"}


# ---------------------------------------------------------------------------
# SpanKind.EMBEDDING and SpanKind.CHAIN exposed in models
# ---------------------------------------------------------------------------

class TestSpanKindExtensions:
    def test_span_kind_embedding_exists(self):
        from flowlens.sdk.models import SpanKind
        assert SpanKind.EMBEDDING.value == "embedding"

    def test_span_kind_chain_exists(self):
        from flowlens.sdk.models import SpanKind
        assert SpanKind.CHAIN.value == "chain"

    def test_span_kind_embedding_exported_from_top_level(self):
        from flowlens import SpanKind
        assert SpanKind.EMBEDDING.value == "embedding"


# ---------------------------------------------------------------------------
# trace_embedding decorator
# ---------------------------------------------------------------------------

class TestTraceEmbeddingDecorator:
    def test_trace_embedding_sync(self, captured_traces):
        """@trace_embedding creates an EMBEDDING span for sync functions."""
        from flowlens.sdk.context import TraceContext
        from flowlens.sdk.decorators import trace_embedding
        from flowlens.sdk.tracer import FlowLens as FL

        lens = FL.get_instance()
        trace = lens.start_trace()

        # Simulate an OpenAI-style embedding response
        class FakeEmbeddingData:
            embedding = [0.1, 0.2, 0.3, 0.4]

        class FakeUsage:
            total_tokens = 8

        class FakeEmbeddingResponse:
            data = [FakeEmbeddingData()]
            usage = FakeUsage()

        @trace_embedding(model="text-embedding-3-small")
        def embed(texts):
            return FakeEmbeddingResponse()

        with TraceContext(trace):
            result = embed(["hello world"])

        lens.end_trace(trace)
        assert isinstance(result, FakeEmbeddingResponse)
        emb_spans = [s for s in captured_traces[0].spans if s.kind == SpanKind.EMBEDDING]
        assert len(emb_spans) == 1
        span = emb_spans[0]
        assert span.status == SpanStatus.OK
        assert span.attributes["embedding.model"] == "text-embedding-3-small"
        assert span.attributes["embedding.dimension"] == 4
        assert span.attributes["embedding.input_count"] == 1
        assert span.attributes["embedding.token_count"] == 8

    @pytest.mark.asyncio
    async def test_trace_embedding_async(self, captured_traces):
        """@trace_embedding creates an EMBEDDING span for async functions."""
        from flowlens.sdk.context import TraceContext
        from flowlens.sdk.decorators import trace_embedding
        from flowlens.sdk.tracer import FlowLens as FL

        lens = FL.get_instance()
        trace = lens.start_trace()

        class FakeEmbeddingData:
            embedding = [0.5, 0.6, 0.7]

        class FakeUsage:
            total_tokens = 4

        class FakeEmbeddingResponse:
            data = [FakeEmbeddingData(), FakeEmbeddingData()]
            usage = FakeUsage()

        @trace_embedding(model="text-embedding-ada-002")
        async def embed_async(texts):
            return FakeEmbeddingResponse()

        with TraceContext(trace):
            result = await embed_async(["foo", "bar"])

        lens.end_trace(trace)
        emb_spans = [s for s in captured_traces[0].spans if s.kind == SpanKind.EMBEDDING]
        assert len(emb_spans) == 1
        span = emb_spans[0]
        assert span.status == SpanStatus.OK
        assert span.attributes["embedding.model"] == "text-embedding-ada-002"
        assert span.attributes["embedding.input_count"] == 2
        assert span.attributes["embedding.dimension"] == 3
        assert span.attributes["embedding.token_count"] == 4

    def test_trace_embedding_error_captured(self, captured_traces):
        """Errors inside @trace_embedding are captured in the span."""
        from flowlens.sdk.context import TraceContext
        from flowlens.sdk.decorators import trace_embedding
        from flowlens.sdk.tracer import FlowLens as FL

        lens = FL.get_instance()
        trace = lens.start_trace()

        @trace_embedding(model="text-embedding-3-small")
        def embed_fail(texts):
            raise RuntimeError("embedding API down")

        with TraceContext(trace), pytest.raises(RuntimeError, match="embedding API down"):
            embed_fail(["test"])

        lens.end_trace(trace)
        emb_spans = [s for s in captured_traces[0].spans if s.kind == SpanKind.EMBEDDING]
        assert emb_spans[0].status == SpanStatus.ERROR
        assert emb_spans[0].error_type == "RuntimeError"

    def test_trace_embedding_exported_from_top_level(self):
        """trace_embedding is importable from the flowlens package."""
        from flowlens import trace_embedding
        assert callable(trace_embedding)

    def test_trace_embedding_dict_response(self, captured_traces):
        """trace_embedding handles dict-style embedding responses."""
        from flowlens.sdk.context import TraceContext
        from flowlens.sdk.decorators import trace_embedding
        from flowlens.sdk.tracer import FlowLens as FL

        lens = FL.get_instance()
        trace = lens.start_trace()

        @trace_embedding(model="custom-embed")
        def embed_dict(texts):
            return {
                "data": [{"embedding": [0.1, 0.2, 0.3, 0.4, 0.5]}],
                "usage": {"total_tokens": 6},
            }

        with TraceContext(trace):
            embed_dict(["hello"])

        lens.end_trace(trace)
        emb_spans = [s for s in captured_traces[0].spans if s.kind == SpanKind.EMBEDDING]
        span = emb_spans[0]
        assert span.attributes["embedding.dimension"] == 5
        assert span.attributes["embedding.token_count"] == 6
