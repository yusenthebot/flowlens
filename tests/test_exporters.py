"""
Tests for OTLPBatchExporter, CSVExporter, and JSONLStreamExporter.

All network I/O is mocked so the suite runs without external services.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import sys
import threading
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from flowlens.sdk.exporters import (
    _CSV_DEFAULT_COLUMNS,
    CSVExporter,
    HTTPExporter,
    JSONLExporter,
    JSONLStreamExporter,
    OTLPBatchExporter,
)
from flowlens.sdk.models import Span, SpanKind, SpanStatus, Trace

# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------


def _make_trace(
    *spans: Span,
    service_name: str = "test-svc",
    trace_id: str = "abcdef1234567890abcdef1234567890",
) -> Trace:
    trace = Trace(trace_id=trace_id, service_name=service_name)
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


# ---------------------------------------------------------------------------
# OTLPBatchExporter — batch accumulation
# ---------------------------------------------------------------------------


class TestOTLPBatchExporterAccumulation:
    """Verify that traces accumulate and flush correctly."""

    def _make_exporter(self, batch_size: int = 3, **kwargs) -> OTLPBatchExporter:
        exp = OTLPBatchExporter(
            endpoint="http://localhost:4318/v1/traces",
            batch_size=batch_size,
            flush_interval_seconds=60,  # disable periodic flush during tests
            **kwargs,
        )
        return exp

    def test_traces_buffered_until_batch_size(self):
        """Traces should accumulate without sending until batch_size is hit."""
        exp = self._make_exporter(batch_size=3)
        sent_batches: list[list[Trace]] = []

        original_send = exp._send_batch

        def capturing_send(traces):
            sent_batches.append(list(traces))

        exp._send_batch = capturing_send

        trace1 = _make_trace(_make_span(name="s1", span_id="aa" * 8))
        trace2 = _make_trace(_make_span(name="s2", span_id="bb" * 8))

        exp.export(trace1)
        exp.export(trace2)
        assert len(sent_batches) == 0, "Should not flush before batch_size"

        trace3 = _make_trace(_make_span(name="s3", span_id="cc" * 8))
        exp.export(trace3)
        assert len(sent_batches) == 1
        assert len(sent_batches[0]) == 3

        exp._flush_thread = MagicMock()  # suppress join warning
        exp._shutdown_event.set()

    def test_flush_clears_buffer(self):
        exp = self._make_exporter(batch_size=10)
        sent: list[int] = []

        def capturing_send(traces):
            sent.append(len(traces))

        exp._send_batch = capturing_send

        for i in range(4):
            exp.export(_make_trace(_make_span(name=f"s{i}", span_id=f"{'a' * 14}{i:02x}")))

        exp.flush()
        assert sent == [4]

        # After flush buffer should be empty
        exp.flush()
        assert sent == [4], "Second flush with empty buffer should be a no-op"

        exp._shutdown_event.set()

    def test_shutdown_flushes_remaining(self):
        exp = self._make_exporter(batch_size=10)
        sent: list[int] = []

        def capturing_send(traces):
            sent.append(len(traces))

        exp._send_batch = capturing_send

        exp.export(_make_trace(_make_span()))
        exp.shutdown()

        assert sent == [1], "shutdown() must flush buffered traces"

    def test_batch_reset_after_flush(self):
        exp = self._make_exporter(batch_size=2)
        sent: list[int] = []

        def capturing_send(traces):
            sent.append(len(traces))

        exp._send_batch = capturing_send

        # Fill first batch
        exp.export(_make_trace(_make_span(span_id="aa" * 8)))
        exp.export(_make_trace(_make_span(span_id="bb" * 8)))
        assert sent == [2]

        # Fill second batch
        exp.export(_make_trace(_make_span(span_id="cc" * 8)))
        exp.export(_make_trace(_make_span(span_id="dd" * 8)))
        assert sent == [2, 2]

        exp._shutdown_event.set()

    def test_empty_batch_no_send(self):
        exp = self._make_exporter(batch_size=5)
        sent: list[int] = []

        def capturing_send(traces):
            sent.append(len(traces))

        exp._send_batch = capturing_send
        exp.flush()
        assert sent == []

        exp._shutdown_event.set()


# ---------------------------------------------------------------------------
# OTLPBatchExporter — HTTP transport and compression
# ---------------------------------------------------------------------------


class TestOTLPBatchExporterTransport:
    def _make_exp(self, **kwargs) -> OTLPBatchExporter:
        return OTLPBatchExporter(
            endpoint="http://localhost:4318/v1/traces",
            batch_size=1,
            flush_interval_seconds=60,
            **kwargs,
        )

    def test_sends_json_post(self):
        exp = self._make_exp(gzip=False)
        captured: list[Any] = []

        def fake_urlopen(req, timeout=None):
            captured.append(req)
            return MagicMock()

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            exp.export(_make_trace(_make_span()))

        assert len(captured) == 1
        req = captured[0]
        assert req.full_url == "http://localhost:4318/v1/traces"
        assert req.get_header("Content-type") == "application/json"
        body = json.loads(req.data.decode())
        assert "resourceSpans" in body

    def test_gzip_compression(self):
        exp = self._make_exp(gzip=True)
        captured: list[Any] = []

        def fake_urlopen(req, timeout=None):
            captured.append(req)
            return MagicMock()

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            exp.export(_make_trace(_make_span()))

        req = captured[0]
        assert req.get_header("Content-encoding") == "gzip"

        # Verify decompressible
        decompressed = gzip.decompress(req.data)
        body = json.loads(decompressed.decode())
        assert "resourceSpans" in body

    def test_no_gzip_by_default(self):
        exp = self._make_exp(gzip=False)
        captured: list[Any] = []

        def fake_urlopen(req, timeout=None):
            captured.append(req)
            return MagicMock()

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            exp.export(_make_trace(_make_span()))

        req = captured[0]
        assert req.get_header("Content-encoding") is None

    def test_custom_headers_forwarded(self):
        exp = OTLPBatchExporter(
            endpoint="http://localhost:4318/v1/traces",
            headers={"Authorization": "Bearer token123"},
            batch_size=1,
            flush_interval_seconds=60,
        )
        captured: list[Any] = []

        def fake_urlopen(req, timeout=None):
            captured.append(req)
            return MagicMock()

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            exp.export(_make_trace(_make_span()))

        assert captured[0].get_header("Authorization") == "Bearer token123"


# ---------------------------------------------------------------------------
# OTLPBatchExporter — retry logic
# ---------------------------------------------------------------------------


class TestOTLPBatchExporterRetry:
    def test_retries_on_failure(self):
        exp = OTLPBatchExporter(
            endpoint="http://localhost:4318/v1/traces",
            batch_size=1,
            flush_interval_seconds=60,
            max_retries=3,
        )

        call_count = [0]

        def flaky_urlopen(req, timeout=None):
            call_count[0] += 1
            if call_count[0] < 3:
                raise ConnectionError("transient error")
            return MagicMock()

        with patch("urllib.request.urlopen", side_effect=flaky_urlopen):
            with patch("time.sleep"):  # skip actual sleep
                exp.export(_make_trace(_make_span()))

        assert call_count[0] == 3, "Should have attempted 3 times"

    def test_all_retries_exhausted_does_not_raise(self):
        exp = OTLPBatchExporter(
            endpoint="http://localhost:4318/v1/traces",
            batch_size=1,
            flush_interval_seconds=60,
            max_retries=2,
        )

        with patch("urllib.request.urlopen", side_effect=ConnectionError("always fails")):
            with patch("time.sleep"):
                # Should log errors but not propagate the exception
                exp.export(_make_trace(_make_span()))

    def test_exponential_backoff_timing(self):
        exp = OTLPBatchExporter(
            endpoint="http://localhost:4318/v1/traces",
            batch_size=1,
            flush_interval_seconds=60,
            max_retries=3,
        )

        sleep_calls: list[float] = []

        with patch("urllib.request.urlopen", side_effect=ConnectionError("fail")):
            with patch("time.sleep", side_effect=lambda t: sleep_calls.append(t)):
                exp.export(_make_trace(_make_span()))

        # Backoff: 0.5s, 1.0s, 2.0s (2^attempt * 0.5)
        assert len(sleep_calls) == 3
        assert sleep_calls[0] == pytest.approx(0.5)
        assert sleep_calls[1] == pytest.approx(1.0)
        assert sleep_calls[2] == pytest.approx(2.0)

    def test_succeeds_on_first_try_no_sleep(self):
        exp = OTLPBatchExporter(
            endpoint="http://localhost:4318/v1/traces",
            batch_size=1,
            flush_interval_seconds=60,
            max_retries=3,
        )

        sleep_calls: list[float] = []

        with patch("urllib.request.urlopen", return_value=MagicMock()):
            with patch("time.sleep", side_effect=lambda t: sleep_calls.append(t)):
                exp.export(_make_trace(_make_span()))

        assert sleep_calls == [], "No sleep when first attempt succeeds"


# ---------------------------------------------------------------------------
# OTLPBatchExporter — payload structure
# ---------------------------------------------------------------------------


class TestOTLPBatchExporterPayload:
    def test_payload_has_resource_spans(self):
        exp = OTLPBatchExporter(endpoint="http://localhost:4318/v1/traces")
        trace = _make_trace(_make_span())
        payload = exp._build_payload([trace])
        assert "resourceSpans" in payload
        assert len(payload["resourceSpans"]) == 1

    def test_multiple_traces_multiple_resource_spans(self):
        exp = OTLPBatchExporter(endpoint="http://localhost:4318/v1/traces")
        traces = [_make_trace(_make_span(name=f"s{i}", span_id=f"{'a'*14}{i:02x}")) for i in range(3)]
        payload = exp._build_payload(traces)
        assert len(payload["resourceSpans"]) == 3

    def test_service_name_in_resource(self):
        exp = OTLPBatchExporter(endpoint="http://localhost:4318/v1/traces", service_name="my-svc")
        trace = _make_trace(_make_span(), service_name="")
        payload = exp._build_payload([trace])
        resource_attrs = payload["resourceSpans"][0]["resource"]["attributes"]
        svc_attr = next(a for a in resource_attrs if a["key"] == "service.name")
        assert svc_attr["value"]["stringValue"] == "my-svc"

    def test_span_count_in_payload(self):
        exp = OTLPBatchExporter(endpoint="http://localhost:4318/v1/traces")
        spans = [_make_span(name=f"s{i}", span_id=f"{'b'*14}{i:02x}") for i in range(4)]
        trace = _make_trace(*spans)
        payload = exp._build_payload([trace])
        otel_spans = payload["resourceSpans"][0]["scopeSpans"][0]["spans"]
        assert len(otel_spans) == 4


# ---------------------------------------------------------------------------
# OTLPBatchExporter — public API
# ---------------------------------------------------------------------------


class TestOTLPBatchExporterPublicAPI:
    def test_importable_from_flowlens(self):
        from flowlens import OTLPBatchExporter as OBE
        assert OBE is OTLPBatchExporter

    def test_in_all(self):
        import flowlens
        assert "OTLPBatchExporter" in flowlens.__all__

    def test_default_parameters(self):
        exp = OTLPBatchExporter()
        assert exp.batch_size == 10
        assert exp.flush_interval_seconds == 5.0
        assert exp.use_gzip is False
        assert exp.max_retries == 3
        exp.shutdown()

    def test_has_flush_method(self):
        exp = OTLPBatchExporter()
        assert callable(exp.flush)
        exp.shutdown()

    def test_has_shutdown_method(self):
        exp = OTLPBatchExporter()
        assert callable(exp.shutdown)
        exp.shutdown()

    def test_background_thread_started(self):
        exp = OTLPBatchExporter()
        assert exp._flush_thread.is_alive()
        exp.shutdown()

    def test_background_thread_stops_after_shutdown(self):
        exp = OTLPBatchExporter(flush_interval_seconds=0.05)
        exp.shutdown()
        exp._flush_thread.join(timeout=2.0)
        assert not exp._flush_thread.is_alive()


# ---------------------------------------------------------------------------
# CSVExporter — output format
# ---------------------------------------------------------------------------


class TestCSVExporterOutputFormat:
    def test_header_row_present(self):
        exp = CSVExporter(write_header=True)
        exp.export(_make_trace(_make_span()))
        lines = exp.get_csv_string().splitlines()
        assert lines[0].split(",") == _CSV_DEFAULT_COLUMNS

    def test_one_row_per_span(self):
        spans = [_make_span(name=f"s{i}", span_id=f"{'a'*14}{i:02x}") for i in range(5)]
        exp = CSVExporter(write_header=True)
        exp.export(_make_trace(*spans))
        lines = [l for l in exp.get_csv_string().splitlines() if l]
        # 1 header + 5 data rows
        assert len(lines) == 6

    def test_span_name_in_output(self):
        span = _make_span(name="my_special_span")
        exp = CSVExporter(write_header=False)
        exp.export(_make_trace(span))
        content = exp.get_csv_string()
        assert "my_special_span" in content

    def test_trace_id_in_output(self):
        span = _make_span()
        trace = _make_trace(span, trace_id="deadbeef" * 4)
        exp = CSVExporter(write_header=False)
        exp.export(trace)
        content = exp.get_csv_string()
        assert "deadbeef" in content

    def test_status_value_in_output(self):
        span = _make_span(status=SpanStatus.ERROR)
        exp = CSVExporter(write_header=False)
        exp.export(_make_trace(span))
        content = exp.get_csv_string()
        assert "error" in content

    def test_error_message_in_output(self):
        span = _make_span(status=SpanStatus.ERROR)
        span.error_message = "something broke"
        exp = CSVExporter(write_header=False)
        exp.export(_make_trace(span))
        content = exp.get_csv_string()
        assert "something broke" in content

    def test_token_usage_in_output(self):
        span = _make_span(kind=SpanKind.LLM)
        span.set_token_usage(input_tokens=100, output_tokens=50, model="gpt-4o")
        exp = CSVExporter(write_header=False)
        exp.export(_make_trace(span))
        content = exp.get_csv_string()
        assert "150" in content  # total_tokens

    def test_no_header_when_write_header_false(self):
        exp = CSVExporter(write_header=False)
        exp.export(_make_trace(_make_span()))
        lines = [l for l in exp.get_csv_string().splitlines() if l]
        assert len(lines) == 1  # just the data row

    def test_custom_columns(self):
        columns = ["trace_id", "name", "status"]
        exp = CSVExporter(columns=columns, write_header=True)
        exp.export(_make_trace(_make_span(name="custom_test")))
        reader = csv.DictReader(io.StringIO(exp.get_csv_string()))
        rows = list(reader)
        assert len(rows) == 1
        assert set(rows[0].keys()) == set(columns)
        assert rows[0]["name"] == "custom_test"

    def test_parseable_csv(self):
        spans = [_make_span(name=f"span_{i}", span_id=f"{'c'*14}{i:02x}") for i in range(3)]
        exp = CSVExporter(write_header=True)
        exp.export(_make_trace(*spans))
        reader = csv.DictReader(io.StringIO(exp.get_csv_string()))
        rows = list(reader)
        assert len(rows) == 3
        names = {r["name"] for r in rows}
        assert names == {"span_0", "span_1", "span_2"}

    def test_multiple_traces_appended(self):
        exp = CSVExporter(write_header=True)
        exp.export(_make_trace(_make_span(name="t1", span_id="aa" * 8)))
        exp.export(_make_trace(_make_span(name="t2", span_id="bb" * 8)))
        reader = csv.DictReader(io.StringIO(exp.get_csv_string()))
        rows = list(reader)
        assert len(rows) == 2
        names = {r["name"] for r in rows}
        assert names == {"t1", "t2"}


# ---------------------------------------------------------------------------
# CSVExporter — file output
# ---------------------------------------------------------------------------


class TestCSVExporterFileOutput:
    def test_writes_to_file(self, tmp_path):
        p = tmp_path / "out.csv"
        exp = CSVExporter(file_path=str(p), write_header=True)
        exp.export(_make_trace(_make_span(name="file_span")))
        exp.shutdown()

        content = p.read_text()
        assert "file_span" in content

    def test_file_has_header(self, tmp_path):
        p = tmp_path / "out.csv"
        exp = CSVExporter(file_path=str(p), write_header=True)
        exp.export(_make_trace(_make_span()))
        exp.shutdown()

        lines = p.read_text().splitlines()
        assert lines[0].split(",") == _CSV_DEFAULT_COLUMNS

    def test_file_and_string_consistent(self, tmp_path):
        p = tmp_path / "out.csv"
        exp = CSVExporter(file_path=str(p), write_header=True)
        exp.export(_make_trace(_make_span(name="sync_test")))
        exp.shutdown()

        # Normalise line endings before comparing (csv module may use \r\n on some platforms)
        file_content = p.read_text().replace("\r\n", "\n")
        mem_content = exp.get_csv_string().replace("\r\n", "\n")
        assert file_content == mem_content

    def test_creates_parent_directories(self, tmp_path):
        p = tmp_path / "a" / "b" / "c" / "out.csv"
        exp = CSVExporter(file_path=str(p), write_header=False)
        exp.export(_make_trace(_make_span()))
        exp.shutdown()
        assert p.exists()


# ---------------------------------------------------------------------------
# CSVExporter — public API
# ---------------------------------------------------------------------------


class TestCSVExporterPublicAPI:
    def test_importable_from_flowlens(self):
        from flowlens import CSVExporter as CE
        assert CE is CSVExporter

    def test_in_all(self):
        import flowlens
        assert "CSVExporter" in flowlens.__all__


# ---------------------------------------------------------------------------
# JSONLStreamExporter — output format
# ---------------------------------------------------------------------------


class TestJSONLStreamExporterFormat:
    def test_each_export_writes_one_line(self):
        buf = io.StringIO()
        exp = JSONLStreamExporter()
        exp._out = buf

        exp.export(_make_trace(_make_span(name="l1", span_id="aa" * 8)))
        exp.export(_make_trace(_make_span(name="l2", span_id="bb" * 8)))

        lines = [l for l in buf.getvalue().splitlines() if l]
        assert len(lines) == 2

    def test_output_is_valid_json(self):
        buf = io.StringIO()
        exp = JSONLStreamExporter()
        exp._out = buf

        exp.export(_make_trace(_make_span()))

        line = buf.getvalue().strip()
        parsed = json.loads(line)
        assert "trace_id" in parsed
        assert "spans" in parsed

    def test_trace_id_present(self):
        buf = io.StringIO()
        exp = JSONLStreamExporter()
        exp._out = buf

        trace = _make_trace(_make_span(), trace_id="cafebabe" * 4)
        exp.export(trace)

        parsed = json.loads(buf.getvalue().strip())
        assert "cafebabe" in parsed["trace_id"]

    def test_spans_serialised(self):
        buf = io.StringIO()
        exp = JSONLStreamExporter()
        exp._out = buf

        span = _make_span(name="serialised_span")
        exp.export(_make_trace(span))

        parsed = json.loads(buf.getvalue().strip())
        names = [s["name"] for s in parsed["spans"]]
        assert "serialised_span" in names

    def test_lines_end_with_newline(self):
        buf = io.StringIO()
        exp = JSONLStreamExporter()
        exp._out = buf

        exp.export(_make_trace(_make_span()))
        assert buf.getvalue().endswith("\n")

    def test_no_trailing_blank_lines(self):
        buf = io.StringIO()
        exp = JSONLStreamExporter()
        exp._out = buf

        exp.export(_make_trace(_make_span(span_id="aa" * 8)))
        exp.export(_make_trace(_make_span(span_id="bb" * 8)))

        content = buf.getvalue()
        # Each line should be well-formed JSON
        for line in content.splitlines():
            json.loads(line)


# ---------------------------------------------------------------------------
# JSONLStreamExporter — file output
# ---------------------------------------------------------------------------


class TestJSONLStreamExporterFileOutput:
    def test_writes_to_file(self, tmp_path):
        p = tmp_path / "traces.jsonl"
        exp = JSONLStreamExporter(file_path=str(p))
        exp.export(_make_trace(_make_span(name="file_trace")))
        exp.shutdown()

        content = p.read_text()
        parsed = json.loads(content.strip())
        assert parsed["spans"][0]["name"] == "file_trace"

    def test_appends_to_existing_file(self, tmp_path):
        p = tmp_path / "traces.jsonl"

        exp1 = JSONLStreamExporter(file_path=str(p))
        exp1.export(_make_trace(_make_span(name="trace1", span_id="aa" * 8)))
        exp1.shutdown()

        exp2 = JSONLStreamExporter(file_path=str(p))
        exp2.export(_make_trace(_make_span(name="trace2", span_id="bb" * 8)))
        exp2.shutdown()

        lines = [l for l in p.read_text().splitlines() if l]
        assert len(lines) == 2

    def test_creates_parent_directories(self, tmp_path):
        p = tmp_path / "a" / "b" / "traces.jsonl"
        exp = JSONLStreamExporter(file_path=str(p))
        exp.export(_make_trace(_make_span()))
        exp.shutdown()
        assert p.exists()

    def test_dash_means_stdout(self, capsys):
        exp = JSONLStreamExporter(file_path="-")
        assert exp._out is sys.stdout

    def test_none_means_stdout(self):
        exp = JSONLStreamExporter(file_path=None)
        assert exp._out is sys.stdout


# ---------------------------------------------------------------------------
# JSONLStreamExporter — stdout output
# ---------------------------------------------------------------------------


class TestJSONLStreamExporterStdout:
    def test_stdout_output(self, capsys):
        exp = JSONLStreamExporter(file_path=None)
        exp.export(_make_trace(_make_span(name="stdout_trace")))
        captured = capsys.readouterr()
        parsed = json.loads(captured.out.strip())
        assert parsed["spans"][0]["name"] == "stdout_trace"


# ---------------------------------------------------------------------------
# JSONLStreamExporter — public API
# ---------------------------------------------------------------------------


class TestJSONLStreamExporterPublicAPI:
    def test_importable_from_flowlens(self):
        from flowlens import JSONLStreamExporter as JLE
        assert JLE is JSONLStreamExporter

    def test_in_all(self):
        import flowlens
        assert "JSONLStreamExporter" in flowlens.__all__


# ---------------------------------------------------------------------------
# Existing OTLPExporter still works (smoke test — do not remove)
# ---------------------------------------------------------------------------


class TestOTLPExporterNotBroken:
    """Guard: ensure original OTLPExporter is intact after adding new classes."""

    def test_import(self):
        from flowlens.sdk.exporters import OTLPExporter
        assert OTLPExporter is not None

    def test_export_with_mock(self):
        from flowlens.sdk.exporters import OTLPExporter
        exp = OTLPExporter(endpoint="http://localhost:4318/v1/traces")
        exp._available = True
        with patch.object(exp, "_send") as mock_send:
            trace = _make_trace(_make_span())
            exp.export(trace)
            mock_send.assert_called_once()


# ---------------------------------------------------------------------------
# Thread-safety — JSONLExporter
# ---------------------------------------------------------------------------


class TestJSONLExporterThreadSafety:
    """Verify that concurrent writes do not corrupt JSONL output."""

    def test_jsonl_exporter_thread_safety(self, tmp_path):
        """10 threads each writing 50 traces must produce 500 valid, complete lines."""
        output_dir = tmp_path / "jsonl_thread_test"
        exp = JSONLExporter(output_dir=str(output_dir))

        num_threads = 10
        traces_per_thread = 50
        errors: list[Exception] = []

        def worker(thread_idx: int) -> None:
            for i in range(traces_per_thread):
                span_id = f"{thread_idx:02x}{i:02x}" + "aa" * 6
                trace = _make_trace(
                    _make_span(name=f"t{thread_idx}_s{i}", span_id=span_id),
                    trace_id=f"{thread_idx:02x}{i:02x}" + "ab" * 14,
                )
                try:
                    exp.export(trace)
                except Exception as exc:
                    errors.append(exc)

        threads = [threading.Thread(target=worker, args=(idx,)) for idx in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        exp.shutdown()

        assert errors == [], f"Threads raised exceptions: {errors}"

        file_path = output_dir / "traces.jsonl"
        raw_lines = [line for line in file_path.read_text(encoding="utf-8").splitlines() if line.strip()]

        assert len(raw_lines) == num_threads * traces_per_thread, (
            f"Expected {num_threads * traces_per_thread} lines, got {len(raw_lines)}"
        )

        # Every line must be valid JSON with a trace_id field — no interleaving
        for line in raw_lines:
            parsed = json.loads(line)
            assert "trace_id" in parsed


# ---------------------------------------------------------------------------
# Thread-safety — CSVExporter
# ---------------------------------------------------------------------------


class TestCSVExporterThreadSafety:
    """Verify that concurrent writes do not corrupt CSV output."""

    def test_csv_exporter_thread_safety(self):
        """10 threads each writing 50 traces must produce exactly 500 data rows."""
        exp = CSVExporter(write_header=True)

        num_threads = 10
        traces_per_thread = 50
        errors: list[Exception] = []

        def worker(thread_idx: int) -> None:
            for i in range(traces_per_thread):
                span_id = f"{thread_idx:02x}{i:02x}" + "cc" * 6
                trace = _make_trace(
                    _make_span(name=f"t{thread_idx}_s{i}", span_id=span_id),
                    trace_id=f"{thread_idx:02x}{i:02x}" + "cd" * 14,
                )
                try:
                    exp.export(trace)
                except Exception as exc:
                    errors.append(exc)

        threads = [threading.Thread(target=worker, args=(idx,)) for idx in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Threads raised exceptions: {errors}"

        reader = csv.DictReader(io.StringIO(exp.get_csv_string()))
        rows = list(reader)

        assert len(rows) == num_threads * traces_per_thread, (
            f"Expected {num_threads * traces_per_thread} data rows, got {len(rows)}"
        )

        # Every row must have parseable columns — no interleaving corruption
        for row in rows:
            assert "trace_id" in row
            assert "name" in row


# ---------------------------------------------------------------------------
# HTTPExporter — configurable timeout
# ---------------------------------------------------------------------------


class TestHTTPExporterCustomTimeout:
    """Verify that the timeout parameter is forwarded to urllib.request.urlopen."""

    def test_default_timeout_is_five(self):
        exp = HTTPExporter()
        assert exp.timeout == 5.0

    def test_custom_timeout_stored(self):
        exp = HTTPExporter(timeout=12.5)
        assert exp.timeout == 12.5

    def test_custom_timeout_forwarded_to_urlopen(self):
        """urlopen must receive the configured timeout, not a hardcoded value."""
        captured_timeouts: list[Any] = []

        def fake_urlopen(req, timeout=None):
            captured_timeouts.append(timeout)
            return MagicMock()

        exp = HTTPExporter(
            endpoint="http://localhost:8585/v1/traces/ingest",
            timeout=42.0,
        )

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            exp.export(_make_trace(_make_span()))

        assert len(captured_timeouts) == 1
        assert captured_timeouts[0] == pytest.approx(42.0)

    def test_default_timeout_forwarded_to_urlopen(self):
        captured_timeouts: list[Any] = []

        def fake_urlopen(req, timeout=None):
            captured_timeouts.append(timeout)
            return MagicMock()

        exp = HTTPExporter(endpoint="http://localhost:8585/v1/traces/ingest")

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            exp.export(_make_trace(_make_span()))

        assert captured_timeouts[0] == pytest.approx(5.0)
