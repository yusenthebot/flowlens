"""Tests for SDK data models."""
import time
from flowlens.sdk.models import (
    Span, SpanKind, SpanStatus, SpanEvent, TokenUsage, Trace, _estimate_cost,
)


class TestSpan:
    def test_create_default(self):
        span = Span(name="test")
        assert span.name == "test"
        assert span.kind == SpanKind.CUSTOM
        assert span.status == SpanStatus.UNSET
        assert span.span_id  # auto-generated
        assert span.start_time > 0

    def test_finish_ok(self):
        span = Span(name="test")
        span.finish(status=SpanStatus.OK)
        assert span.status == SpanStatus.OK
        assert span.end_time > span.start_time
        assert span.duration_ms > 0

    def test_finish_error(self):
        span = Span(name="test")
        span.finish(error="something broke")
        assert span.status == SpanStatus.ERROR
        assert span.error_message == "something broke"

    def test_add_event(self):
        span = Span(name="test")
        span.add_event("checkpoint:start", step=1)
        assert len(span.events) == 1
        assert span.events[0].name == "checkpoint:start"
        assert span.events[0].attributes["step"] == 1

    def test_set_token_usage(self):
        span = Span(name="test")
        span.set_token_usage(input_tokens=1000, output_tokens=500, model="claude-sonnet-4-20250514")
        assert span.token_usage is not None
        assert span.token_usage.input_tokens == 1000
        assert span.token_usage.output_tokens == 500
        assert span.token_usage.total_tokens == 1500
        assert span.token_usage.total_cost_usd > 0

    def test_to_dict(self):
        span = Span(name="test", kind=SpanKind.LLM)
        span.finish()
        d = span.to_dict()
        assert d["name"] == "test"
        assert d["kind"] == "llm"
        assert d["status"] == "ok"
        assert "span_id" in d
        assert "duration_ms" in d

    def test_to_dict_with_error(self):
        span = Span(name="fail")
        span.finish(error="boom")
        d = span.to_dict()
        assert d["error"]["message"] == "boom"

    def test_to_dict_with_tokens(self):
        span = Span(name="llm")
        span.set_token_usage(100, 50, "gpt-4o")
        span.finish()
        d = span.to_dict()
        assert d["token_usage"]["total_tokens"] == 150


class TestTrace:
    def test_create_trace(self):
        trace = Trace(service_name="test-svc")
        assert trace.trace_id
        assert trace.service_name == "test-svc"
        assert trace.total_tokens == 0
        assert not trace.has_errors

    def test_trace_with_spans(self):
        trace = Trace()
        s1 = Span(name="a", trace_id=trace.trace_id)
        s1.set_token_usage(100, 50, "")
        s1.finish()
        s2 = Span(name="b", trace_id=trace.trace_id)
        s2.finish(error="fail")
        trace.spans = [s1, s2]
        trace.finish()

        assert trace.total_tokens == 150
        assert trace.has_errors
        assert trace.error_count == 1
        assert trace.duration_ms > 0

    def test_to_dict(self):
        trace = Trace(service_name="svc")
        span = Span(name="root", trace_id=trace.trace_id)
        span.finish()
        trace.spans = [span]
        trace.finish()
        d = trace.to_dict()
        assert d["service_name"] == "svc"
        assert d["span_count"] == 1
        assert len(d["spans"]) == 1


class TestCostEstimation:
    def test_claude_sonnet_pricing(self):
        costs = _estimate_cost("claude-sonnet-4-20250514", 1_000_000, 1_000_000)
        assert costs["input_cost_usd"] == 3.0
        assert costs["output_cost_usd"] == 15.0

    def test_gpt4o_pricing(self):
        costs = _estimate_cost("gpt-4o", 1_000_000, 1_000_000)
        assert costs["input_cost_usd"] == 2.5
        assert costs["output_cost_usd"] == 10.0

    def test_unknown_model_uses_default(self):
        costs = _estimate_cost("unknown-model-v99", 1_000_000, 1_000_000)
        assert costs["input_cost_usd"] == 3.0  # default
        assert costs["output_cost_usd"] == 15.0  # default

    def test_zero_tokens(self):
        costs = _estimate_cost("", 0, 0)
        assert costs["total_cost_usd"] == 0.0
