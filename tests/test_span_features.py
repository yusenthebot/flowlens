"""Tests for new Span methods: set_attribute, add_link, add_event (updated),
and updated MODEL_PRICING / _MODEL_CONTEXT_WINDOWS in models.py."""

from __future__ import annotations

import pytest

from flowlens import SpanEvent as PublicSpanEvent  # verify __init__ export
from flowlens.sdk.models import (
    _MODEL_CONTEXT_WINDOWS,
    _MODEL_PRICING,
    Span,
    SpanEvent,
    _estimate_cost,
)

# ---------------------------------------------------------------------------
# SpanEvent public export
# ---------------------------------------------------------------------------


class TestSpanEventPublicExport:
    def test_span_event_importable_from_flowlens(self):
        """SpanEvent must be importable from the top-level flowlens package."""
        assert PublicSpanEvent is SpanEvent

    def test_span_event_fields(self):
        ev = SpanEvent(name="my_event", attributes={"k": "v"})
        assert ev.name == "my_event"
        assert ev.attributes["k"] == "v"
        assert ev.timestamp > 0

    def test_span_event_default_timestamp(self):
        import time

        before = time.time()
        ev = SpanEvent(name="ev")
        after = time.time()
        assert before <= ev.timestamp <= after


# ---------------------------------------------------------------------------
# Span.set_attribute
# ---------------------------------------------------------------------------


class TestSetAttribute:
    def test_set_single_attribute(self):
        span = Span(name="test")
        span.set_attribute("custom.key", "custom_value")
        assert span.attributes["custom.key"] == "custom_value"

    def test_set_attribute_overrides_existing(self):
        span = Span(name="test", attributes={"key": "old"})
        span.set_attribute("key", "new")
        assert span.attributes["key"] == "new"

    def test_set_attribute_various_types(self):
        span = Span(name="test")
        span.set_attribute("int_attr", 42)
        span.set_attribute("float_attr", 3.14)
        span.set_attribute("bool_attr", True)
        span.set_attribute("list_attr", [1, 2, 3])
        assert span.attributes["int_attr"] == 42
        assert span.attributes["float_attr"] == pytest.approx(3.14)
        assert span.attributes["bool_attr"] is True
        assert span.attributes["list_attr"] == [1, 2, 3]

    def test_set_attribute_reflected_in_to_dict(self):
        span = Span(name="test")
        span.set_attribute("gen_ai.model", "gpt-4.1")
        span.finish()
        d = span.to_dict()
        assert d["attributes"]["gen_ai.model"] == "gpt-4.1"


# ---------------------------------------------------------------------------
# Span.add_event (updated signature)
# ---------------------------------------------------------------------------


class TestAddEvent:
    def test_add_event_with_kwargs(self):
        span = Span(name="test")
        span.add_event("checkpoint:start", step=1, status="running")
        assert len(span.events) == 1
        assert span.events[0].name == "checkpoint:start"
        assert span.events[0].attributes["step"] == 1
        assert span.events[0].attributes["status"] == "running"

    def test_add_event_with_attributes_dict(self):
        span = Span(name="test")
        span.add_event("my_event", attributes={"a": 1, "b": 2})
        assert span.events[0].attributes["a"] == 1
        assert span.events[0].attributes["b"] == 2

    def test_add_event_dict_and_kwargs_merged(self):
        span = Span(name="test")
        span.add_event("ev", attributes={"from_dict": True}, from_kwarg=True)
        attrs = span.events[0].attributes
        assert attrs["from_dict"] is True
        assert attrs["from_kwarg"] is True

    def test_add_event_kwargs_take_precedence_over_dict(self):
        """When a key appears in both attributes dict and kwargs, kwargs win."""
        span = Span(name="test")
        span.add_event("ev", attributes={"key": "dict_value"}, key="kwarg_value")
        assert span.events[0].attributes["key"] == "kwarg_value"

    def test_add_event_no_attributes(self):
        span = Span(name="test")
        span.add_event("bare_event")
        assert span.events[0].name == "bare_event"
        assert span.events[0].attributes == {}

    def test_multiple_events_ordered(self):
        span = Span(name="test")
        span.add_event("first")
        span.add_event("second")
        span.add_event("third")
        names = [e.name for e in span.events]
        assert names == ["first", "second", "third"]

    def test_events_in_to_dict(self):
        span = Span(name="test")
        span.add_event("ev", x=99)
        span.finish()
        d = span.to_dict()
        assert len(d["events"]) == 1
        assert d["events"][0]["name"] == "ev"
        assert d["events"][0]["attributes"]["x"] == 99


# ---------------------------------------------------------------------------
# Span.add_link
# ---------------------------------------------------------------------------


class TestAddLink:
    def test_add_link_creates_event(self):
        span = Span(name="consumer")
        span.add_link(trace_id="trace_abc", span_id="span_xyz")
        assert len(span.events) == 1
        ev = span.events[0]
        assert ev.name == "span_link"
        assert ev.attributes["link.trace_id"] == "trace_abc"
        assert ev.attributes["link.span_id"] == "span_xyz"

    def test_add_link_with_attributes(self):
        span = Span(name="consumer")
        span.add_link("trace_abc", "span_xyz", attributes={"reason": "causality"})
        ev = span.events[0]
        assert ev.attributes["reason"] == "causality"
        assert ev.attributes["link.trace_id"] == "trace_abc"

    def test_add_multiple_links(self):
        span = Span(name="fan_in")
        span.add_link("trace_1", "span_1")
        span.add_link("trace_2", "span_2")
        link_events = [e for e in span.events if e.name == "span_link"]
        assert len(link_events) == 2
        assert link_events[0].attributes["link.trace_id"] == "trace_1"
        assert link_events[1].attributes["link.trace_id"] == "trace_2"

    def test_link_serialized_in_to_dict(self):
        span = Span(name="test")
        span.add_link("t1", "s1")
        span.finish()
        d = span.to_dict()
        link_events = [e for e in d["events"] if e["name"] == "span_link"]
        assert len(link_events) == 1
        assert link_events[0]["attributes"]["link.trace_id"] == "t1"
        assert link_events[0]["attributes"]["link.span_id"] == "s1"

    def test_links_mixed_with_regular_events(self):
        span = Span(name="test")
        span.add_event("before_link")
        span.add_link("tx", "sx")
        span.add_event("after_link")
        assert len(span.events) == 3
        assert span.events[0].name == "before_link"
        assert span.events[1].name == "span_link"
        assert span.events[2].name == "after_link"


# ---------------------------------------------------------------------------
# MODEL_PRICING — 2026 model coverage
# ---------------------------------------------------------------------------


class TestModelPricing2026:
    def _check_model(self, model_key: str):
        assert model_key in _MODEL_PRICING, f"{model_key!r} missing from _MODEL_PRICING"
        in_price, out_price = _MODEL_PRICING[model_key]
        assert in_price > 0
        assert out_price > 0

    def test_claude_4_opus(self):
        self._check_model("claude-opus-4-20250514")

    def test_claude_4_sonnet(self):
        self._check_model("claude-sonnet-4-20250514")

    def test_claude_4_haiku(self):
        self._check_model("claude-haiku-4-20250514")

    def test_gpt_41(self):
        self._check_model("gpt-4.1")

    def test_gpt_41_mini(self):
        self._check_model("gpt-4.1-mini")

    def test_gemini_25_pro(self):
        self._check_model("gemini-2.5-pro")

    def test_gemini_25_flash(self):
        self._check_model("gemini-2.5-flash")

    def test_deepseek_v3(self):
        self._check_model("deepseek-v3")

    def test_deepseek_r1(self):
        self._check_model("deepseek-r1")

    def test_claude_4_opus_pricing_values(self):
        """Verify specific pricing numbers for Claude 4 Opus."""
        in_p, out_p = _MODEL_PRICING["claude-opus-4-20250514"]
        assert in_p == 15.0
        assert out_p == 75.0

    def test_claude_4_sonnet_pricing_values(self):
        in_p, out_p = _MODEL_PRICING["claude-sonnet-4-20250514"]
        assert in_p == 3.0
        assert out_p == 15.0

    def test_gpt_41_pricing_values(self):
        in_p, out_p = _MODEL_PRICING["gpt-4.1"]
        assert in_p == 2.0
        assert out_p == 8.0

    def test_deepseek_v3_pricing_values(self):
        in_p, out_p = _MODEL_PRICING["deepseek-v3"]
        assert in_p == pytest.approx(0.27)
        assert out_p == pytest.approx(1.1)

    def test_all_models_have_positive_prices(self):
        for model, (in_p, out_p) in _MODEL_PRICING.items():
            assert in_p >= 0, f"{model} has negative input price"
            assert out_p >= 0, f"{model} has negative output price"
            assert out_p >= in_p, f"{model}: output should be >= input (common pattern)"


# ---------------------------------------------------------------------------
# _MODEL_CONTEXT_WINDOWS — sanity
# ---------------------------------------------------------------------------


class TestContextWindows:
    def test_claude_4_large_context(self):
        assert _MODEL_CONTEXT_WINDOWS.get("claude-sonnet-4-20250514", 0) >= 200_000

    def test_gemini_25_pro_large_context(self):
        assert _MODEL_CONTEXT_WINDOWS.get("gemini-2.5-pro", 0) >= 1_000_000

    def test_gpt_41_large_context(self):
        assert _MODEL_CONTEXT_WINDOWS.get("gpt-4.1", 0) >= 128_000


# ---------------------------------------------------------------------------
# _estimate_cost — extended coverage
# ---------------------------------------------------------------------------


class TestEstimateCostExtended:
    def test_claude_4_opus_short_alias(self):
        """Short alias 'claude-opus-4' should resolve to the same pricing."""
        costs_full = _estimate_cost("claude-opus-4-20250514", 1_000_000, 1_000_000)
        costs_short = _estimate_cost("claude-opus-4", 1_000_000, 1_000_000)
        assert costs_full == costs_short

    def test_deepseek_r1_pricing(self):
        costs = _estimate_cost("deepseek-r1", 1_000_000, 1_000_000)
        assert costs["input_cost_usd"] == pytest.approx(0.55)
        assert costs["output_cost_usd"] == pytest.approx(2.19)

    def test_gemini_25_pro_pricing(self):
        costs = _estimate_cost("gemini-2.5-pro", 1_000_000, 1_000_000)
        assert costs["input_cost_usd"] == pytest.approx(1.25)
        assert costs["output_cost_usd"] == pytest.approx(10.0)

    def test_total_equals_sum(self):
        costs = _estimate_cost("gpt-4.1", 500_000, 200_000)
        assert costs["total_cost_usd"] == pytest.approx(
            costs["input_cost_usd"] + costs["output_cost_usd"], rel=1e-6
        )
