"""Tests for OTLPExporter — conversion logic and export behaviour.

All tests mock the network layer and opentelemetry import so that the suite
can run without opentelemetry packages installed.
"""

from __future__ import annotations

import json
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from flowlens.sdk.exporters import (
    OTLPExporter,
    _dict_to_otel_attrs,
    _pad_hex,
    _to_otel_value,
    create_exporter,
)
from flowlens.sdk.models import Span, SpanKind, SpanStatus, SpanEvent, Trace


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_trace(*spans: Span, service_name: str = "test-svc") -> Trace:
    """Build a minimal Trace containing the given spans."""
    trace = Trace(trace_id="abcdef1234567890abcdef1234567890", service_name=service_name)
    for span in spans:
        span.trace_id = trace.trace_id
    trace.spans = list(spans)
    trace.finish()
    return trace


def _make_span(
    name: str = "test_span",
    kind: SpanKind = SpanKind.CUSTOM,
    status: SpanStatus = SpanStatus.OK,
    span_id: str = "aabbccdd11223344",
    parent_span_id: str | None = None,
) -> Span:
    span = Span(
        name=name,
        kind=kind,
        status=status,
        span_id=span_id,
        parent_span_id=parent_span_id,
    )
    span.start_time = 1_700_000_000.0
    span.end_time = 1_700_000_001.5
    return span


def _make_exporter(available: bool = True, endpoint: str = "http://localhost:4318/v1/traces") -> OTLPExporter:
    """Create an OTLPExporter with mocked availability."""
    exporter = OTLPExporter(endpoint=endpoint)
    exporter._available = available
    return exporter


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

class TestPadHex:
    def test_exact_length(self):
        assert _pad_hex("abcd1234", 8) == "abcd1234"

    def test_pad_shorter(self):
        result = _pad_hex("ff", 8)
        assert len(result) == 8
        assert result.endswith("ff")

    def test_truncate_longer(self):
        result = _pad_hex("aabbccddee112233", 8)
        assert len(result) == 8

    def test_none_returns_zeros(self):
        assert _pad_hex(None, 16) == "0" * 16

    def test_empty_string_returns_zeros(self):
        assert _pad_hex("", 16) == "0" * 16

    def test_strips_dashes(self):
        result = _pad_hex("ab-cd-ef-12", 8)
        assert "-" not in result

    def test_lowercase(self):
        result = _pad_hex("ABCDEF12", 8)
        assert result == result.lower()


class TestToOtelValue:
    def test_bool(self):
        assert _to_otel_value(True) == {"boolValue": True}
        assert _to_otel_value(False) == {"boolValue": False}

    def test_int(self):
        assert _to_otel_value(42) == {"intValue": 42}

    def test_float(self):
        assert _to_otel_value(3.14) == {"doubleValue": 3.14}

    def test_string(self):
        assert _to_otel_value("hello") == {"stringValue": "hello"}

    def test_list(self):
        result = _to_otel_value([1, "two", True])
        assert "arrayValue" in result
        values = result["arrayValue"]["values"]
        assert values[0] == {"intValue": 1}
        assert values[1] == {"stringValue": "two"}
        assert values[2] == {"boolValue": True}

    def test_dict(self):
        result = _to_otel_value({"a": 1, "b": "two"})
        assert "kvlistValue" in result
        kv = {item["key"]: item["value"] for item in result["kvlistValue"]["values"]}
        assert kv["a"] == {"intValue": 1}
        assert kv["b"] == {"stringValue": "two"}

    def test_unknown_type_falls_back_to_string(self):
        result = _to_otel_value(object())
        assert "stringValue" in result


class TestDictToOtelAttrs:
    def test_basic_conversion(self):
        attrs = _dict_to_otel_attrs({"key1": "value", "key2": 99})
        keys = {a["key"] for a in attrs}
        assert "key1" in keys
        assert "key2" in keys

    def test_empty_dict(self):
        assert _dict_to_otel_attrs({}) == []

    def test_nested_list_value(self):
        attrs = _dict_to_otel_attrs({"items": [1, 2, 3]})
        assert len(attrs) == 1
        assert "arrayValue" in attrs[0]["value"]


# ---------------------------------------------------------------------------
# OTLPExporter — availability
# ---------------------------------------------------------------------------

class TestOTLPExporterAvailability:
    def test_unavailable_exporter_does_not_send(self):
        exporter = _make_exporter(available=False)
        with patch.object(exporter, "_send") as mock_send:
            trace = _make_trace(_make_span())
            exporter.export(trace)
            mock_send.assert_not_called()

    def test_available_exporter_calls_send(self):
        exporter = _make_exporter(available=True)
        with patch.object(exporter, "_send") as mock_send:
            trace = _make_trace(_make_span())
            exporter.export(trace)
            mock_send.assert_called_once()

    def test_check_availability_true_when_otel_installed(self):
        fake_otel = MagicMock()
        with patch.dict("sys.modules", {"opentelemetry": fake_otel}):
            assert OTLPExporter._check_availability() is True

    def test_check_availability_false_when_otel_missing(self):
        with patch.dict("sys.modules", {"opentelemetry": None}):
            assert OTLPExporter._check_availability() is False


# ---------------------------------------------------------------------------
# OTLPExporter — payload construction
# ---------------------------------------------------------------------------

class TestOTLPPayloadStructure:
    def setup_method(self):
        self.exporter = _make_exporter(available=True)

    def test_resource_spans_present(self):
        trace = _make_trace(_make_span())
        payload = self.exporter._build_payload(trace)
        assert "resourceSpans" in payload
        assert len(payload["resourceSpans"]) == 1

    def test_service_name_in_resource(self):
        trace = _make_trace(_make_span(), service_name="my-agent")
        payload = self.exporter._build_payload(trace)
        resource_attrs = payload["resourceSpans"][0]["resource"]["attributes"]
        svc_attr = next((a for a in resource_attrs if a["key"] == "service.name"), None)
        assert svc_attr is not None
        assert svc_attr["value"]["stringValue"] == "my-agent"

    def test_fallback_service_name(self):
        """Trace with empty service_name falls back to exporter.service_name."""
        trace = _make_trace(_make_span(), service_name="")
        exporter = OTLPExporter(service_name="fallback-svc")
        exporter._available = True
        payload = exporter._build_payload(trace)
        resource_attrs = payload["resourceSpans"][0]["resource"]["attributes"]
        svc_attr = next(a for a in resource_attrs if a["key"] == "service.name")
        assert svc_attr["value"]["stringValue"] == "fallback-svc"

    def test_sdk_attributes_present(self):
        trace = _make_trace(_make_span())
        payload = self.exporter._build_payload(trace)
        resource_attrs = payload["resourceSpans"][0]["resource"]["attributes"]
        keys = {a["key"] for a in resource_attrs}
        assert "telemetry.sdk.name" in keys
        assert "telemetry.sdk.language" in keys

    def test_scope_name(self):
        trace = _make_trace(_make_span())
        payload = self.exporter._build_payload(trace)
        scope = payload["resourceSpans"][0]["scopeSpans"][0]["scope"]
        assert scope["name"] == "flowlens.tracer"

    def test_span_count_matches(self):
        spans = [_make_span(name=f"s{i}", span_id=f"{'a' * 14}{i:02d}") for i in range(3)]
        trace = _make_trace(*spans)
        payload = self.exporter._build_payload(trace)
        otel_spans = payload["resourceSpans"][0]["scopeSpans"][0]["spans"]
        assert len(otel_spans) == 3


# ---------------------------------------------------------------------------
# OTLPExporter — span conversion
# ---------------------------------------------------------------------------

class TestSpanConversion:
    def setup_method(self):
        self.exporter = _make_exporter(available=True)

    def _convert(self, span: Span, trace: Trace | None = None) -> dict[str, Any]:
        if trace is None:
            trace = _make_trace(span)
        return self.exporter._convert_span(span, trace)

    def test_span_name(self):
        span = _make_span(name="my_llm_call")
        result = self._convert(span)
        assert result["name"] == "my_llm_call"

    def test_trace_id_padded_to_32(self):
        span = _make_span()
        trace = _make_trace(span)
        result = self.exporter._convert_span(span, trace)
        assert len(result["traceId"]) == 32

    def test_span_id_padded_to_16(self):
        span = _make_span(span_id="short")
        result = self._convert(span)
        assert len(result["spanId"]) == 16

    def test_parent_span_id_present(self):
        span = _make_span(parent_span_id="parentparentpa01")
        result = self._convert(span)
        assert "parentSpanId" in result
        assert len(result["parentSpanId"]) == 16

    def test_no_parent_span_id_when_none(self):
        span = _make_span(parent_span_id=None)
        result = self._convert(span)
        assert "parentSpanId" not in result

    def test_timestamps_are_nanoseconds_strings(self):
        span = _make_span()
        span.start_time = 1_700_000_000.0
        span.end_time = 1_700_000_001.0
        result = self._convert(span)
        # Must be string representations of integers (OTel JSON encoding)
        assert result["startTimeUnixNano"] == str(int(1_700_000_000.0 * 1_000_000_000))
        assert result["endTimeUnixNano"] == str(int(1_700_000_001.0 * 1_000_000_000))

    def test_end_time_zero_falls_back_to_start(self):
        span = _make_span()
        span.start_time = 1_700_000_000.0
        span.end_time = 0.0
        result = self._convert(span)
        assert result["endTimeUnixNano"] == result["startTimeUnixNano"]

    # SpanKind mapping
    @pytest.mark.parametrize("fl_kind, expected_otel", [
        (SpanKind.AGENT, OTLPExporter._OTEL_SPAN_KIND_INTERNAL),
        (SpanKind.LLM, OTLPExporter._OTEL_SPAN_KIND_CLIENT),
        (SpanKind.TOOL, OTLPExporter._OTEL_SPAN_KIND_INTERNAL),
        (SpanKind.CHAIN, OTLPExporter._OTEL_SPAN_KIND_INTERNAL),
        (SpanKind.RETRIEVAL, OTLPExporter._OTEL_SPAN_KIND_CLIENT),
        (SpanKind.CUSTOM, OTLPExporter._OTEL_SPAN_KIND_INTERNAL),
    ])
    def test_span_kind_mapping(self, fl_kind: SpanKind, expected_otel: int):
        span = _make_span(kind=fl_kind)
        result = self._convert(span)
        assert result["kind"] == expected_otel

    # SpanStatus mapping
    @pytest.mark.parametrize("fl_status, expected_code", [
        (SpanStatus.UNSET, OTLPExporter._STATUS_CODE_UNSET),
        (SpanStatus.OK, OTLPExporter._STATUS_CODE_OK),
        (SpanStatus.ERROR, OTLPExporter._STATUS_CODE_ERROR),
    ])
    def test_span_status_mapping(self, fl_status: SpanStatus, expected_code: int):
        span = _make_span(status=fl_status)
        result = self._convert(span)
        assert result["status"]["code"] == expected_code

    def test_error_status_includes_message(self):
        span = _make_span(status=SpanStatus.ERROR)
        span.error_message = "something went wrong"
        result = self._convert(span)
        assert result["status"]["code"] == OTLPExporter._STATUS_CODE_ERROR
        assert result["status"]["message"] == "something went wrong"

    def test_ok_status_no_message(self):
        span = _make_span(status=SpanStatus.OK)
        result = self._convert(span)
        assert "message" not in result["status"]


# ---------------------------------------------------------------------------
# OTLPExporter — attribute building
# ---------------------------------------------------------------------------

class TestAttributeBuilding:
    def setup_method(self):
        self.exporter = _make_exporter(available=True)

    def _attr_map(self, span: Span) -> dict[str, Any]:
        """Return OTel attributes as a plain key→value dict for easy assertions."""
        attrs = self.exporter._build_attributes(span)
        result: dict[str, Any] = {}
        for a in attrs:
            val = a["value"]
            # Extract the concrete python value for comparison
            for vtype, vval in val.items():
                result[a["key"]] = vval
                break
        return result

    def test_gen_ai_operation_name_set(self):
        span = _make_span(kind=SpanKind.LLM)
        attrs = self._attr_map(span)
        assert attrs["gen_ai.operation.name"] == "llm"

    def test_span_attributes_preserved(self):
        span = _make_span()
        span.attributes = {"custom.key": "custom_value", "gen_ai.model": "gpt-4o"}
        attrs = self._attr_map(span)
        assert attrs["custom.key"] == "custom_value"
        assert attrs["gen_ai.model"] == "gpt-4o"

    def test_token_usage_mapped_to_gen_ai(self):
        span = _make_span(kind=SpanKind.LLM)
        span.set_token_usage(input_tokens=500, output_tokens=200, model="gpt-4o")
        attrs = self._attr_map(span)
        assert attrs["gen_ai.usage.input_tokens"] == 500
        assert attrs["gen_ai.usage.output_tokens"] == 200
        assert attrs["gen_ai.usage.total_tokens"] == 700

    def test_token_usage_costs_mapped(self):
        span = _make_span(kind=SpanKind.LLM)
        span.set_token_usage(input_tokens=1_000_000, output_tokens=1_000_000, model="gpt-4o")
        attrs = self._attr_map(span)
        # gpt-4o: 2.5 input, 10.0 output per 1M tokens
        assert attrs["gen_ai.usage.input_cost_usd"] == pytest.approx(2.5, rel=1e-3)
        assert attrs["gen_ai.usage.output_cost_usd"] == pytest.approx(10.0, rel=1e-3)

    def test_no_token_usage_keys_absent(self):
        span = _make_span(kind=SpanKind.TOOL)
        attrs = self._attr_map(span)
        assert "gen_ai.usage.input_tokens" not in attrs

    def test_error_message_in_attributes(self):
        span = _make_span(status=SpanStatus.ERROR)
        span.error_message = "boom"
        span.error_type = "RuntimeError"
        attrs = self._attr_map(span)
        assert attrs["exception.message"] == "boom"
        assert attrs["exception.type"] == "RuntimeError"

    def test_no_error_keys_absent(self):
        span = _make_span(status=SpanStatus.OK)
        attrs = self._attr_map(span)
        assert "exception.message" not in attrs
        assert "exception.type" not in attrs


# ---------------------------------------------------------------------------
# OTLPExporter — events
# ---------------------------------------------------------------------------

class TestEventConversion:
    def setup_method(self):
        self.exporter = _make_exporter(available=True)

    def test_events_converted(self):
        span = _make_span()
        span.events = [
            SpanEvent(name="checkpoint:start", timestamp=1_700_000_000.5, attributes={"step": 1}),
            SpanEvent(name="checkpoint:end", timestamp=1_700_000_001.0, attributes={"step": 2}),
        ]
        trace = _make_trace(span)
        result = self.exporter._convert_span(span, trace)
        assert len(result["events"]) == 2
        assert result["events"][0]["name"] == "checkpoint:start"
        assert result["events"][1]["name"] == "checkpoint:end"

    def test_event_timestamp_nanoseconds(self):
        span = _make_span()
        ts = 1_700_000_000.123
        span.events = [SpanEvent(name="ev", timestamp=ts, attributes={})]
        trace = _make_trace(span)
        result = self.exporter._convert_span(span, trace)
        expected_ns = str(int(ts * 1_000_000_000))
        assert result["events"][0]["timeUnixNano"] == expected_ns

    def test_event_attributes_preserved(self):
        span = _make_span()
        span.events = [SpanEvent(name="ev", timestamp=time.time(), attributes={"k": "v", "n": 42})]
        trace = _make_trace(span)
        result = self.exporter._convert_span(span, trace)
        ev_attrs = {a["key"]: a["value"] for a in result["events"][0]["attributes"]}
        assert ev_attrs["k"] == {"stringValue": "v"}
        assert ev_attrs["n"] == {"intValue": 42}

    def test_no_events(self):
        span = _make_span()
        trace = _make_trace(span)
        result = self.exporter._convert_span(span, trace)
        assert result["events"] == []


# ---------------------------------------------------------------------------
# OTLPExporter — HTTP transport
# ---------------------------------------------------------------------------

class TestOTLPHTTPTransport:
    def test_send_posts_json_to_endpoint(self):
        exporter = _make_exporter(available=True, endpoint="http://collector:4318/v1/traces")

        captured_requests: list[Any] = []

        def fake_urlopen(req, timeout=None):
            captured_requests.append(req)
            return MagicMock()

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            trace = _make_trace(_make_span())
            exporter.export(trace)

        assert len(captured_requests) == 1
        req = captured_requests[0]
        assert req.full_url == "http://collector:4318/v1/traces"
        assert req.get_header("Content-type") == "application/json"
        body = json.loads(req.data.decode())
        assert "resourceSpans" in body

    def test_send_includes_custom_headers(self):
        exporter = OTLPExporter(
            endpoint="http://collector:4318/v1/traces",
            headers={"Authorization": "Bearer secret"},
        )
        exporter._available = True

        captured_requests: list[Any] = []

        def fake_urlopen(req, timeout=None):
            captured_requests.append(req)
            return MagicMock()

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            trace = _make_trace(_make_span())
            exporter.export(trace)

        req = captured_requests[0]
        assert req.get_header("Authorization") == "Bearer secret"

    def test_send_failure_does_not_raise(self):
        exporter = _make_exporter(available=True)

        with patch("urllib.request.urlopen", side_effect=ConnectionError("refused")):
            trace = _make_trace(_make_span())
            # Should not propagate the exception
            exporter.export(trace)

    def test_send_uses_configured_timeout(self):
        exporter = OTLPExporter(timeout=42.0)
        exporter._available = True

        timeout_used: list[float] = []

        def fake_urlopen(req, timeout=None):
            timeout_used.append(timeout)
            return MagicMock()

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            exporter.export(_make_trace(_make_span()))

        assert timeout_used[0] == 42.0


# ---------------------------------------------------------------------------
# OTLPExporter — async export
# ---------------------------------------------------------------------------

class TestOTLPAsyncExport:
    @pytest.mark.asyncio
    async def test_export_async_calls_send(self):
        exporter = _make_exporter(available=True)

        with patch.object(exporter, "_send") as mock_send:
            trace = _make_trace(_make_span())
            await exporter.export_async(trace)
            mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_export_async_unavailable_skips(self):
        exporter = _make_exporter(available=False)

        with patch.object(exporter, "_send") as mock_send:
            trace = _make_trace(_make_span())
            await exporter.export_async(trace)
            mock_send.assert_not_called()


# ---------------------------------------------------------------------------
# create_exporter factory
# ---------------------------------------------------------------------------

class TestCreateExporterFactory:
    def test_otlp_creates_otlp_exporter(self):
        exporter = create_exporter(export_to="otlp")
        assert isinstance(exporter, OTLPExporter)

    def test_otlp_uses_custom_endpoint(self):
        exporter = create_exporter(
            export_to="otlp",
            otlp_endpoint="http://my-collector:4318/v1/traces",
        )
        assert isinstance(exporter, OTLPExporter)
        assert exporter.endpoint == "http://my-collector:4318/v1/traces"

    def test_unknown_exporter_raises(self):
        with pytest.raises(ValueError, match="otlp"):
            create_exporter(export_to="unknown")

    def test_console_still_works(self):
        from flowlens.sdk.exporters import ConsoleExporter
        exporter = create_exporter(export_to="console")
        assert isinstance(exporter, ConsoleExporter)

    def test_jsonl_still_works(self, tmp_path):
        from flowlens.sdk.exporters import JSONLExporter
        exporter = create_exporter(export_to="jsonl", output_dir=str(tmp_path))
        assert isinstance(exporter, JSONLExporter)
        exporter.shutdown()

    def test_http_still_works(self):
        from flowlens.sdk.exporters import HTTPExporter
        exporter = create_exporter(export_to="http")
        assert isinstance(exporter, HTTPExporter)


# ---------------------------------------------------------------------------
# Public API export
# ---------------------------------------------------------------------------

class TestPublicAPIExport:
    def test_otlp_exporter_importable_from_flowlens(self):
        from flowlens import OTLPExporter as OE
        assert OE is OTLPExporter

    def test_otlp_exporter_in_all(self):
        import flowlens
        assert "OTLPExporter" in flowlens.__all__


# ---------------------------------------------------------------------------
# Integration: full trace round-trip
# ---------------------------------------------------------------------------

class TestFullTraceRoundTrip:
    """Build a realistic multi-span trace and verify the full OTLP payload."""

    def setup_method(self):
        self.exporter = _make_exporter(available=True)

    def test_agent_llm_tool_trace(self):
        agent_span = Span(
            span_id="agent00000000001",
            name="run_agent",
            kind=SpanKind.AGENT,
            start_time=1_700_000_000.0,
        )
        agent_span.end_time = 1_700_000_005.0
        agent_span.status = SpanStatus.OK

        llm_span = Span(
            span_id="llm000000000001",
            name="call_llm",
            kind=SpanKind.LLM,
            parent_span_id="agent00000000001",
            start_time=1_700_000_001.0,
        )
        llm_span.end_time = 1_700_000_002.0
        llm_span.status = SpanStatus.OK
        llm_span.set_token_usage(input_tokens=1000, output_tokens=400, model="gpt-4o")

        tool_span = Span(
            span_id="tool000000000001",
            name="web_search",
            kind=SpanKind.TOOL,
            parent_span_id="llm000000000001",
            start_time=1_700_000_002.5,
        )
        tool_span.end_time = 1_700_000_003.0
        tool_span.status = SpanStatus.ERROR
        tool_span.error_message = "Connection timeout"
        tool_span.error_type = "TimeoutError"
        tool_span.add_event("retry_attempt", attempt=1)

        trace = Trace(
            trace_id="cafebabe" * 4,
            service_name="my-ai-agent",
        )
        for span in [agent_span, llm_span, tool_span]:
            span.trace_id = trace.trace_id
        trace.spans = [agent_span, llm_span, tool_span]
        trace.finish()

        payload = self.exporter._build_payload(trace)

        resource_spans = payload["resourceSpans"]
        assert len(resource_spans) == 1

        otel_spans = resource_spans[0]["scopeSpans"][0]["spans"]
        assert len(otel_spans) == 3

        by_name = {s["name"]: s for s in otel_spans}

        # Agent span
        assert by_name["run_agent"]["kind"] == OTLPExporter._OTEL_SPAN_KIND_INTERNAL
        assert by_name["run_agent"]["status"]["code"] == OTLPExporter._STATUS_CODE_OK
        assert "parentSpanId" not in by_name["run_agent"]

        # LLM span
        assert by_name["call_llm"]["kind"] == OTLPExporter._OTEL_SPAN_KIND_CLIENT
        assert by_name["call_llm"]["parentSpanId"] is not None
        llm_attr_map = {a["key"]: a["value"] for a in by_name["call_llm"]["attributes"]}
        assert "gen_ai.usage.input_tokens" in llm_attr_map
        assert llm_attr_map["gen_ai.usage.input_tokens"] == {"intValue": 1000}

        # Tool span with error
        assert by_name["web_search"]["status"]["code"] == OTLPExporter._STATUS_CODE_ERROR
        assert by_name["web_search"]["status"]["message"] == "Connection timeout"
        tool_attr_map = {a["key"]: a["value"] for a in by_name["web_search"]["attributes"]}
        assert tool_attr_map["exception.type"] == {"stringValue": "TimeoutError"}
        assert len(by_name["web_search"]["events"]) == 1
        assert by_name["web_search"]["events"][0]["name"] == "retry_attempt"
