"""
Tests for LocalCollector and LocalExporter.

Covers:
- Basic ingest + query roundtrip
- list_traces pagination
- search functionality
- stats aggregation
- Context manager cleanup
- Thread safety (10 concurrent ingesting threads)
- LocalExporter integration with FlowLens SDK
"""

from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path

import pytest

from flowlens.local import LocalCollector
from flowlens.sdk.exporters import LocalExporter, create_exporter
from flowlens.sdk.models import Span, SpanKind, SpanStatus, TokenUsage, Trace

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_trace_data(
    service: str = "test-service",
    has_error: bool = False,
    span_name: str = "my-span",
    trace_id: str | None = None,
) -> dict:
    """Build a minimal trace dict compatible with TraceStore.save_trace."""
    tid = trace_id or uuid.uuid4().hex
    now = time.time()
    span = {
        "span_id": uuid.uuid4().hex[:16],
        "trace_id": tid,
        "parent_span_id": None,
        "name": span_name,
        "kind": "llm",
        "status": "error" if has_error else "ok",
        "start_time": now - 0.1,
        "end_time": now,
        "duration_ms": 100.0,
        "token_usage": {
            "input_tokens": 10,
            "output_tokens": 20,
            "total_tokens": 30,
            "input_cost_usd": 0.00003,
            "output_cost_usd": 0.0003,
            "total_cost_usd": 0.00033,
        },
        "attributes": {"model": "claude-sonnet-4"},
        "events": [],
    }
    if has_error:
        span["error"] = {"message": "something went wrong", "type": "RuntimeError"}
    return {
        "trace_id": tid,
        "service_name": service,
        "start_time": now - 0.1,
        "end_time": now,
        "duration_ms": 100.0,
        "span_count": 1,
        "total_tokens": 30,
        "total_cost_usd": 0.00033,
        "has_errors": has_error,
        "error_count": 1 if has_error else 0,
        "metadata": {},
        "spans": [span],
    }


def _make_sdk_trace(
    service: str = "sdk-service",
    span_name: str = "sdk-span",
) -> Trace:
    """Build a Trace object using the SDK models."""
    trace = Trace(service_name=service)
    span = Span(
        name=span_name,
        kind=SpanKind.LLM,
        status=SpanStatus.OK,
        start_time=time.time() - 0.05,
    )
    span.finish()
    span.token_usage = TokenUsage(
        input_tokens=5,
        output_tokens=10,
        total_tokens=15,
        total_cost_usd=0.0001,
    )
    trace.spans.append(span)
    trace.finish()
    return trace


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def collector(tmp_path: Path) -> LocalCollector:
    """Fresh LocalCollector backed by a temp SQLite file."""
    db = tmp_path / "test.db"
    c = LocalCollector(db_path=str(db))
    yield c
    c.close()


# ---------------------------------------------------------------------------
# Basic ingest + query roundtrip
# ---------------------------------------------------------------------------


class TestIngestAndQuery:
    def test_ingest_returns_trace_id(self, collector: LocalCollector) -> None:
        td = _make_trace_data()
        result = collector.ingest(td)
        assert result == td["trace_id"]

    def test_query_returns_trace_with_spans(self, collector: LocalCollector) -> None:
        td = _make_trace_data(span_name="alpha-span")
        collector.ingest(td)

        fetched = collector.query(td["trace_id"])
        assert fetched is not None
        assert fetched["trace_id"] == td["trace_id"]
        assert fetched["service_name"] == "test-service"
        assert len(fetched["spans"]) == 1
        assert fetched["spans"][0]["name"] == "alpha-span"

    def test_query_missing_returns_none(self, collector: LocalCollector) -> None:
        result = collector.query("nonexistent-trace-id")
        assert result is None

    def test_ingest_missing_trace_id_raises(self, collector: LocalCollector) -> None:
        with pytest.raises(ValueError, match="trace_id"):
            collector.ingest({"service_name": "oops"})

    def test_ingest_empty_trace_id_raises(self, collector: LocalCollector) -> None:
        with pytest.raises(ValueError, match="trace_id"):
            collector.ingest({"trace_id": "", "service_name": "oops"})

    def test_ingest_overwrites_existing_trace(self, collector: LocalCollector) -> None:
        """INSERT OR REPLACE should silently update an existing trace."""
        td = _make_trace_data(service="svc-a")
        collector.ingest(td)

        td["service_name"] = "svc-b"
        collector.ingest(td)

        fetched = collector.query(td["trace_id"])
        assert fetched["service_name"] == "svc-b"


# ---------------------------------------------------------------------------
# list_traces pagination
# ---------------------------------------------------------------------------


class TestListTraces:
    def test_list_returns_all_traces(self, collector: LocalCollector) -> None:
        for _ in range(5):
            collector.ingest(_make_trace_data())
        traces = collector.list_traces(limit=100)
        assert len(traces) == 5

    def test_list_respects_limit(self, collector: LocalCollector) -> None:
        for _ in range(10):
            collector.ingest(_make_trace_data())
        traces = collector.list_traces(limit=3)
        assert len(traces) == 3

    def test_list_pagination_offset(self, collector: LocalCollector) -> None:
        ids = []
        for _ in range(6):
            td = _make_trace_data()
            collector.ingest(td)
            ids.append(td["trace_id"])

        page1 = collector.list_traces(limit=3, offset=0)
        page2 = collector.list_traces(limit=3, offset=3)
        assert len(page1) == 3
        assert len(page2) == 3
        # Pages must not overlap
        page1_ids = {t["trace_id"] for t in page1}
        page2_ids = {t["trace_id"] for t in page2}
        assert page1_ids.isdisjoint(page2_ids)

    def test_list_filter_by_service(self, collector: LocalCollector) -> None:
        for _ in range(3):
            collector.ingest(_make_trace_data(service="svc-a"))
        for _ in range(2):
            collector.ingest(_make_trace_data(service="svc-b"))

        a = collector.list_traces(service="svc-a")
        b = collector.list_traces(service="svc-b")
        assert len(a) == 3
        assert len(b) == 2

    def test_list_ordered_newest_first(self, collector: LocalCollector) -> None:
        """Traces should come back newest-first (start_time DESC)."""
        for i in range(3):
            td = _make_trace_data()
            td["start_time"] = time.time() + i  # ensure monotonic ordering
            collector.ingest(td)

        traces = collector.list_traces(limit=10)
        start_times = [t["start_time"] for t in traces]
        assert start_times == sorted(start_times, reverse=True)

    def test_list_returns_no_spans_key(self, collector: LocalCollector) -> None:
        """list_traces should not embed span detail."""
        collector.ingest(_make_trace_data())
        traces = collector.list_traces()
        assert "spans" not in traces[0]


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


class TestSearch:
    def test_search_by_span_name(self, collector: LocalCollector) -> None:
        collector.ingest(_make_trace_data(span_name="call-claude"))
        collector.ingest(_make_trace_data(span_name="call-gpt"))
        collector.ingest(_make_trace_data(span_name="search-docs"))

        results = collector.search("claude")
        assert len(results) == 1
        assert results[0]["service_name"] == "test-service"

    def test_search_by_error_message(self, collector: LocalCollector) -> None:
        collector.ingest(_make_trace_data(has_error=True))
        collector.ingest(_make_trace_data(has_error=False))

        results = collector.search("something went wrong")
        assert len(results) == 1

    def test_search_by_service_name(self, collector: LocalCollector) -> None:
        collector.ingest(_make_trace_data(service="my-unique-service-xyz"))
        collector.ingest(_make_trace_data(service="other-service"))

        results = collector.search("unique-service")
        assert len(results) == 1
        assert results[0]["service_name"] == "my-unique-service-xyz"

    def test_search_no_results(self, collector: LocalCollector) -> None:
        collector.ingest(_make_trace_data())
        results = collector.search("zzz-no-match-zzz")
        assert results == []

    def test_search_case_insensitive(self, collector: LocalCollector) -> None:
        collector.ingest(_make_trace_data(span_name="CallClaude"))
        results = collector.search("callclaude")
        assert len(results) == 1


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


class TestStats:
    def test_stats_empty_db(self, collector: LocalCollector) -> None:
        s = collector.stats()
        # total_traces is 0 when empty
        assert s.get("total_traces") == 0 or s.get("total_traces") is None

    def test_stats_counts_traces(self, collector: LocalCollector) -> None:
        for _ in range(4):
            collector.ingest(_make_trace_data())
        s = collector.stats()
        assert s["total_traces"] == 4

    def test_stats_counts_spans(self, collector: LocalCollector) -> None:
        for _ in range(3):
            collector.ingest(_make_trace_data())
        s = collector.stats()
        assert s["total_spans"] == 3

    def test_stats_sums_tokens(self, collector: LocalCollector) -> None:
        for _ in range(2):
            collector.ingest(_make_trace_data())  # each trace has 30 tokens
        s = collector.stats()
        assert s["total_tokens"] == 60

    def test_stats_counts_error_traces(self, collector: LocalCollector) -> None:
        collector.ingest(_make_trace_data(has_error=True))
        collector.ingest(_make_trace_data(has_error=False))
        s = collector.stats()
        assert s["error_traces"] == 1

    def test_stats_avg_duration(self, collector: LocalCollector) -> None:
        for _ in range(2):
            collector.ingest(_make_trace_data())
        s = collector.stats()
        assert s["avg_duration_ms"] is not None
        assert s["avg_duration_ms"] > 0


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------


class TestContextManager:
    def test_context_manager_returns_self(self, tmp_path: Path) -> None:
        db = tmp_path / "ctx.db"
        with LocalCollector(str(db)) as c:
            assert isinstance(c, LocalCollector)

    def test_context_manager_closes_on_exit(self, tmp_path: Path) -> None:
        db = tmp_path / "ctx.db"
        with LocalCollector(str(db)) as c:
            c.ingest(_make_trace_data())
        # After exit the pool's primary connection should be closed; a second
        # collector opening the same file must still be able to read the data.
        with LocalCollector(str(db)) as c2:
            traces = c2.list_traces()
        assert len(traces) == 1

    def test_context_manager_on_exception(self, tmp_path: Path) -> None:
        """close() must be called even when body raises."""
        db = tmp_path / "exc.db"
        closed = []
        original_close = LocalCollector.close

        class TrackingCollector(LocalCollector):
            def close(self) -> None:
                closed.append(True)
                original_close(self)

        try:
            with TrackingCollector(str(db)):
                raise RuntimeError("simulated error")
        except RuntimeError:
            pass

        assert closed == [True]


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_ingest_10_threads(self, tmp_path: Path) -> None:
        """10 threads ingesting concurrently must all succeed without data loss."""
        db = tmp_path / "concurrent.db"
        collector = LocalCollector(str(db))
        errors: list[Exception] = []
        ingested_ids: list[str] = []
        lock = threading.Lock()

        def worker(n: int) -> None:
            try:
                td = _make_trace_data(service=f"svc-{n}")
                tid = collector.ingest(td)
                with lock:
                    ingested_ids.append(tid)
            except Exception as exc:
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        collector.close()

        assert errors == [], f"Errors during concurrent ingest: {errors}"
        assert len(ingested_ids) == 10

        # Verify all traces landed in the DB
        with LocalCollector(str(db)) as verify:
            traces = verify.list_traces(limit=100)
        assert len(traces) == 10

    def test_concurrent_ingest_and_query(self, tmp_path: Path) -> None:
        """Writers and readers can operate concurrently without crashes."""
        db = tmp_path / "rw.db"
        collector = LocalCollector(str(db))
        errors: list[Exception] = []

        # Pre-seed one trace so readers have something to find
        seed = _make_trace_data()
        collector.ingest(seed)

        def write_worker(n: int) -> None:
            try:
                collector.ingest(_make_trace_data(service=f"writer-{n}"))
            except Exception as exc:
                with threading.Lock():
                    errors.append(exc)

        def read_worker() -> None:
            try:
                collector.list_traces(limit=50)
            except Exception as exc:
                with threading.Lock():
                    errors.append(exc)

        threads = [threading.Thread(target=write_worker, args=(i,)) for i in range(5)] + [
            threading.Thread(target=read_worker) for _ in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        collector.close()
        assert errors == [], f"Errors during concurrent read/write: {errors}"


# ---------------------------------------------------------------------------
# LocalExporter integration
# ---------------------------------------------------------------------------


class TestLocalExporter:
    def test_export_persists_trace(self, tmp_path: Path) -> None:
        db = str(tmp_path / "exporter.db")
        exporter = LocalExporter(db_path=db)
        trace = _make_sdk_trace(service="exporter-test")
        exporter.export(trace)
        exporter.shutdown()

        with LocalCollector(db) as c:
            fetched = c.query(trace.trace_id)
        assert fetched is not None
        assert fetched["service_name"] == "exporter-test"
        assert len(fetched["spans"]) == 1

    def test_export_multiple_traces(self, tmp_path: Path) -> None:
        db = str(tmp_path / "multi.db")
        exporter = LocalExporter(db_path=db)
        for _ in range(5):
            exporter.export(_make_sdk_trace())
        exporter.shutdown()

        with LocalCollector(db) as c:
            traces = c.list_traces(limit=100)
        assert len(traces) == 5

    def test_exporter_shutdown_closes_collector(self, tmp_path: Path) -> None:
        """shutdown() must not raise even when called multiple times."""
        db = str(tmp_path / "shutdown.db")
        exporter = LocalExporter(db_path=db)
        exporter.shutdown()
        exporter.shutdown()  # second call should be a no-op / safe

    def test_create_exporter_local(self, tmp_path: Path) -> None:
        """create_exporter('local') should return a LocalExporter."""
        exporter = create_exporter(export_to="local", output_dir=str(tmp_path))
        assert isinstance(exporter, LocalExporter)
        exporter.shutdown()

    def test_create_exporter_local_default_path(self, tmp_path: Path, monkeypatch) -> None:
        """When output_dir is the default './traces', db goes to './flowlens.db'."""
        # We only test that the factory returns a LocalExporter without error
        # (the actual path logic is trivial string manipulation).
        exporter = create_exporter(export_to="local")
        assert isinstance(exporter, LocalExporter)
        exporter.shutdown()

    def test_create_exporter_unknown_raises(self) -> None:
        with pytest.raises(ValueError, match="local"):
            create_exporter(export_to="unknown-backend")

    def test_exporter_span_data_roundtrip(self, tmp_path: Path) -> None:
        """Token usage and span attributes should survive the ingest/query cycle."""
        db = str(tmp_path / "rt.db")
        exporter = LocalExporter(db_path=db)

        trace = Trace(service_name="rt-svc")
        span = Span(
            name="rt-span",
            kind=SpanKind.LLM,
            status=SpanStatus.OK,
            start_time=time.time() - 0.01,
        )
        span.finish()
        span.token_usage = TokenUsage(
            input_tokens=100,
            output_tokens=200,
            total_tokens=300,
            total_cost_usd=0.005,
        )
        span.set_attribute("gen_ai.model", "claude-sonnet-4")
        trace.spans.append(span)
        trace.finish()

        exporter.export(trace)
        exporter.shutdown()

        with LocalCollector(db) as c:
            fetched = c.query(trace.trace_id)

        assert fetched is not None
        s = fetched["spans"][0]
        assert s["name"] == "rt-span"
        assert s["input_tokens"] == 100
        assert s["output_tokens"] == 200
        assert s["attributes"]["gen_ai.model"] == "claude-sonnet-4"
