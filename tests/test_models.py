"""Tests for SDK data models."""
import time
import pytest
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
        assert span.end_time >= span.start_time
        assert span.duration_ms >= 0

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

    def test_fuzzy_model_matching(self):
        """Test fuzzy substring matching for model names"""
        # Partial match on 'gpt-4o'
        costs = _estimate_cost("gpt-4o-turbo-preview", 1_000_000, 1_000_000)
        assert costs["input_cost_usd"] == 2.5  # gpt-4o pricing
        assert costs["output_cost_usd"] == 10.0

        # Case-insensitive matching
        costs = _estimate_cost("CLAUDE-SONNET-4-20250514", 1_000_000, 1_000_000)
        assert costs["input_cost_usd"] == 3.0
        assert costs["output_cost_usd"] == 15.0

    def test_small_token_values(self):
        """Test cost calculation with small token counts"""
        costs = _estimate_cost("claude-sonnet-4-20250514", 100, 50)
        # (100 / 1_000_000) * 3.0 = 0.0003
        # (50 / 1_000_000) * 15.0 = 0.00075
        assert round(costs["input_cost_usd"], 6) == 0.0003
        assert round(costs["output_cost_usd"], 6) == 0.00075


class TestSpanEdgeCases:
    def test_span_to_dict_all_fields_populated(self):
        """Test to_dict with all optional fields set"""
        span = Span(
            name="full_span",
            kind=SpanKind.LLM,
            parent_span_id="parent_123",
            trace_id="trace_456",
        )
        span.set_token_usage(1000, 500, "claude-sonnet-4-20250514")
        span.add_event("checkpoint_1", step=1, status="started")
        span.add_event("checkpoint_2", step=2, status="ended")
        span.finish(error="Some error occurred")

        d = span.to_dict()

        assert d["span_id"] == span.span_id
        assert d["trace_id"] == "trace_456"
        assert d["parent_span_id"] == "parent_123"
        assert d["name"] == "full_span"
        assert d["kind"] == "llm"
        assert d["status"] == "error"
        assert d["error"]["message"] == "Some error occurred"
        assert d["token_usage"]["input_tokens"] == 1000
        assert d["token_usage"]["output_tokens"] == 500
        assert len(d["events"]) == 2
        assert d["events"][0]["name"] == "checkpoint_1"
        assert d["events"][0]["attributes"]["step"] == 1

    def test_span_duration_before_finish(self):
        """Span duration is 0 before finish() is called"""
        span = Span(name="test")
        assert span.duration_ms == 0.0
        span.finish()
        assert span.duration_ms > 0

    def test_span_with_no_events(self):
        """Span can be created without any events"""
        span = Span(name="minimal")
        span.finish()
        d = span.to_dict()
        assert d["events"] == []


class TestTraceEdgeCases:
    def test_trace_with_zero_spans(self):
        """Trace with no spans"""
        trace = Trace(service_name="empty-service")
        trace.finish()

        assert trace.total_tokens == 0
        assert trace.total_cost_usd == 0.0
        assert not trace.has_errors
        assert trace.error_count == 0
        assert trace.error_rate == 0.0

    def test_trace_error_rate_calculation(self):
        """Error rate is correctly calculated"""
        trace = Trace()

        # 2 OK spans, 1 ERROR span
        s1 = Span(name="ok1", trace_id=trace.trace_id)
        s1.finish(status=SpanStatus.OK)

        s2 = Span(name="error", trace_id=trace.trace_id)
        s2.finish(error="failed")

        s3 = Span(name="ok2", trace_id=trace.trace_id)
        s3.finish(status=SpanStatus.OK)

        trace.spans = [s1, s2, s3]
        trace.finish()

        assert trace.error_count == 1
        assert len(trace.spans) == 3
        assert trace.error_rate == pytest.approx(1/3, rel=1e-5)

    def test_trace_with_multiple_token_usage_spans(self):
        """Sum token usage across multiple LLM spans"""
        trace = Trace(service_name="multi-llm")

        s1 = Span(name="llm1", kind=SpanKind.LLM, trace_id=trace.trace_id)
        s1.set_token_usage(500, 200, "claude-sonnet-4-20250514")
        s1.finish()

        s2 = Span(name="llm2", kind=SpanKind.LLM, trace_id=trace.trace_id)
        s2.set_token_usage(300, 100, "gpt-4o")
        s2.finish()

        s3 = Span(name="tool1", kind=SpanKind.TOOL, trace_id=trace.trace_id)
        s3.finish()  # No token usage

        trace.spans = [s1, s2, s3]
        trace.finish()

        assert trace.total_tokens == 1100  # 500+200+300+100
        assert trace.total_cost_usd > 0

    def test_trace_to_dict_structure(self):
        """Verify trace.to_dict() returns all expected fields"""
        trace = Trace(service_name="test-service")
        s1 = Span(name="root", kind=SpanKind.AGENT, trace_id=trace.trace_id)
        s1.finish()
        trace.spans = [s1]
        trace.finish()

        d = trace.to_dict()

        assert "trace_id" in d
        assert "service_name" in d
        assert d["service_name"] == "test-service"
        assert "root_span_id" in d
        assert "start_time" in d
        assert "end_time" in d
        assert "duration_ms" in d
        assert "total_tokens" in d
        assert "total_cost_usd" in d
        assert "has_errors" in d
        assert "error_count" in d
        assert "span_count" in d
        assert d["span_count"] == 1
        assert "spans" in d
        assert len(d["spans"]) == 1
        assert "metadata" in d
