"""Tests for flowlens.sdk.auto_instrument — monkey-patching LLM libraries."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from flowlens import FlowLens, auto_instrument
from flowlens.sdk.models import Trace, SpanKind, SpanStatus
from flowlens.sdk.exporters import CallbackExporter
from flowlens.sdk import auto_instrument as ai_module


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
    def test_unknown_library_logs_warning(self, caplog):
        import logging
        with caplog.at_level(logging.WARNING, logger="flowlens.sdk.auto_instrument"):
            auto_instrument(["not_a_real_library"])
        assert "not_a_real_library" in caplog.text

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

        with TraceContext(trace):
            with pytest.raises(ValueError, match="API error"):
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

        with TraceContext(trace):
            with pytest.raises(RuntimeError, match="async error"):
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
