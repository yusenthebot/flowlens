"""Edge case tests for flowlens/server/storage.py."""
from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path

import pytest

from flowlens.server.storage import TraceStore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path: Path) -> TraceStore:
    s = TraceStore(db_path=str(tmp_path / "test.db"))
    yield s
    s.close()


def _make_trace(
    service: str = "svc",
    span_name: str = "span",
    n_spans: int = 1,
    has_error: bool = False,
) -> dict:
    trace_id = uuid.uuid4().hex
    spans = []
    for i in range(n_spans):
        spans.append({
            "span_id": uuid.uuid4().hex[:16],
            "trace_id": trace_id,
            "parent_span_id": None,
            "name": span_name if i == 0 else f"{span_name}_{i}",
            "kind": "llm",
            "status": "error" if (has_error and i == 0) else "ok",
            "start_time": time.time(),
            "end_time": time.time() + 0.1 * i,
            "duration_ms": 100.0 * (i + 1),
            "attributes": {},
            "events": [],
            "token_usage": {"input_tokens": 10, "output_tokens": 5, "total_cost_usd": 0.001},
            "error": {"message": "something failed"} if (has_error and i == 0) else None,
        })
    return {
        "trace_id": trace_id,
        "service_name": service,
        "start_time": time.time(),
        "end_time": time.time() + 1.0,
        "duration_ms": 1000.0,
        "span_count": n_spans,
        "total_tokens": 15 * n_spans,
        "total_cost_usd": 0.001 * n_spans,
        "has_errors": has_error,
        "error_count": 1 if has_error else 0,
        "metadata": {"env": "test"},
        "spans": spans,
    }


# ---------------------------------------------------------------------------
# Unicode service names and span names
# ---------------------------------------------------------------------------

class TestUnicode:
    def test_unicode_service_name(self, store: TraceStore):
        t = _make_trace(service="服务-日本語-한국어")
        store.save_trace(t)
        rows = store.list_traces(service_name="服务-日本語-한국어")
        assert len(rows) == 1
        assert rows[0]["service_name"] == "服务-日本語-한국어"

    def test_unicode_span_name(self, store: TraceStore):
        t = _make_trace(service="svc", span_name="ツール呼び出し")
        store.save_trace(t)
        retrieved = store.get_trace(t["trace_id"])
        assert retrieved is not None
        assert any("ツール" in s["name"] for s in retrieved["spans"])

    def test_emoji_in_service_name(self, store: TraceStore):
        t = _make_trace(service="my-agent-🤖")
        store.save_trace(t)
        rows = store.list_traces(service_name="my-agent-🤖")
        assert len(rows) == 1

    def test_unicode_error_message(self, store: TraceStore):
        t = _make_trace(service="svc", has_error=True)
        t["spans"][0]["error"] = {"message": "错误：无效的输入 🔥"}
        store.save_trace(t)
        retrieved = store.get_trace(t["trace_id"])
        error_span = next(s for s in retrieved["spans"] if s.get("error_message"))
        assert "错误" in error_span["error_message"]

    def test_unicode_metadata(self, store: TraceStore):
        t = _make_trace(service="svc")
        t["metadata"] = {"描述": "测试元数据", "user": "用户甲"}
        store.save_trace(t)
        retrieved = store.get_trace(t["trace_id"])
        assert retrieved["metadata"]["描述"] == "测试元数据"


# ---------------------------------------------------------------------------
# Very large traces (100+ spans)
# ---------------------------------------------------------------------------

class TestLargeTraces:
    def test_save_and_retrieve_100_spans(self, store: TraceStore):
        t = _make_trace(service="big-svc", span_name="step", n_spans=100)
        store.save_trace(t)
        retrieved = store.get_trace(t["trace_id"])
        assert retrieved is not None
        assert len(retrieved["spans"]) == 100

    def test_save_and_retrieve_500_spans(self, store: TraceStore):
        t = _make_trace(service="huge-svc", span_name="op", n_spans=500)
        store.save_trace(t)
        retrieved = store.get_trace(t["trace_id"])
        assert retrieved is not None
        assert len(retrieved["spans"]) == 500

    def test_stats_aggregate_large_trace(self, store: TraceStore):
        t = _make_trace(service="stat-svc", n_spans=200)
        store.save_trace(t)
        stats = store.get_stats()
        assert stats["total_traces"] >= 1
        assert stats["total_spans"] is not None

    def test_list_many_traces_with_limit(self, store: TraceStore):
        for i in range(30):
            t = _make_trace(service="multi-svc")
            store.save_trace(t)
        rows = store.list_traces(limit=10)
        assert len(rows) == 10

    def test_batch_delete_large_set(self, store: TraceStore):
        ids = []
        for i in range(50):
            t = _make_trace(service="del-svc")
            store.save_trace(t)
            ids.append(t["trace_id"])
        deleted = store.batch_delete_traces(ids)
        assert deleted == 50
        assert store.list_traces(service_name="del-svc") == []


# ---------------------------------------------------------------------------
# Concurrent writes (use threading)
# ---------------------------------------------------------------------------

class TestConcurrentWrites:
    def test_concurrent_saves_from_multiple_threads(self, tmp_path: Path):
        """Each thread uses its own TraceStore instance (own primary connection),
        all writing to the same WAL-mode SQLite file.  This mirrors real-world
        multi-process / multi-worker deployments where each worker owns a
        connection.
        """
        db = str(tmp_path / "concurrent.db")

        # Initialise the schema once using the main store
        main_store = TraceStore(db_path=db)

        errors: list[Exception] = []
        written_ids: list[str] = []
        lock = threading.Lock()

        def worker():
            try:
                # Each thread gets its own TraceStore / connection
                ts = TraceStore(db_path=db)
                t = _make_trace(service="concurrent-svc")
                ts.save_trace(t)
                ts.close()
                with lock:
                    written_ids.append(t["trace_id"])
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()

        assert not errors, f"Errors during concurrent writes: {errors}"
        assert len(written_ids) == 10

        rows = main_store.list_traces(service_name="concurrent-svc", limit=15)
        assert len(rows) == 10
        main_store.close()

    def test_concurrent_reads_and_writes(self, tmp_path: Path):
        """Writers and readers running simultaneously must not raise."""
        db = str(tmp_path / "rw.db")

        # Initialise schema and seed data
        main_store = TraceStore(db_path=db)
        for _ in range(5):
            main_store.save_trace(_make_trace(service="rw-svc"))

        errors: list[Exception] = []

        def writer():
            try:
                ts = TraceStore(db_path=db)
                for _ in range(3):
                    ts.save_trace(_make_trace(service="rw-svc"))
                ts.close()
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                ts = TraceStore(db_path=db)
                for _ in range(5):
                    ts.list_traces(service_name="rw-svc", limit=5)
                ts.close()
            except Exception as e:
                errors.append(e)

        threads = (
            [threading.Thread(target=writer) for _ in range(3)]
            + [threading.Thread(target=reader) for _ in range(3)]
        )
        for th in threads:
            th.start()
        for th in threads:
            th.join()

        main_store.close()
        assert not errors, f"Errors during concurrent r/w: {errors}"


# ---------------------------------------------------------------------------
# Schema migration (v0 → current)
# ---------------------------------------------------------------------------

class TestSchemaMigration:
    def test_schema_version_is_current(self, store: TraceStore):
        from flowlens.server.storage import SCHEMA_VERSION
        version = store._get_version()
        assert version == SCHEMA_VERSION

    def test_fresh_db_is_migrated_to_latest(self, tmp_path: Path):
        from flowlens.server.storage import SCHEMA_VERSION
        s = TraceStore(db_path=str(tmp_path / "fresh.db"))
        assert s._get_version() == SCHEMA_VERSION
        s.close()

    def test_tables_exist_after_migration(self, store: TraceStore):
        conn = store._conn
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        assert "traces" in tables
        assert "spans" in tables
        assert "schema_version" in tables

    def test_indexes_exist_after_migration(self, store: TraceStore):
        conn = store._conn
        indexes = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()}
        # v2 indexes
        assert "idx_traces_has_errors" in indexes
        assert "idx_traces_created_at" in indexes
        # v3 indexes
        assert "idx_spans_search" in indexes
        assert "idx_traces_service_time" in indexes

    def test_save_and_query_after_migration(self, store: TraceStore):
        t = _make_trace(service="migrated-svc")
        store.save_trace(t)
        result = store.get_trace(t["trace_id"])
        assert result is not None
        assert result["service_name"] == "migrated-svc"


# ---------------------------------------------------------------------------
# Search with special characters
# ---------------------------------------------------------------------------

class TestSearchSpecialChars:
    def test_search_plain_term(self, store: TraceStore):
        t = _make_trace(service="searchable-svc", span_name="do_work")
        store.save_trace(t)
        results = store.search_traces("searchable-svc")
        assert any(r["trace_id"] == t["trace_id"] for r in results)

    def test_search_percent_sign(self, store: TraceStore):
        """A literal % in the query should not break the LIKE query."""
        t = _make_trace(service="pct-svc")
        store.save_trace(t)
        # Should not raise; results may be empty or contain the trace
        results = store.search_traces("%")
        assert isinstance(results, list)

    def test_search_underscore(self, store: TraceStore):
        """A literal _ in the query should not explode LIKE."""
        t = _make_trace(service="under_score_svc")
        store.save_trace(t)
        results = store.search_traces("under_score_svc")
        assert isinstance(results, list)
        # The trace may or may not appear due to LIKE _ behaviour; at minimum no exception

    def test_search_single_quote(self, store: TraceStore):
        """SQL injection attempt via single quote must not raise."""
        t = _make_trace(service="quot-svc")
        store.save_trace(t)
        results = store.search_traces("'; DROP TABLE traces; --")
        assert isinstance(results, list)

    def test_search_backslash(self, store: TraceStore):
        t = _make_trace(service="back\\slash")
        store.save_trace(t)
        results = store.search_traces("back\\slash")
        assert isinstance(results, list)

    def test_search_unicode_term(self, store: TraceStore):
        t = _make_trace(service="unicode-検索")
        store.save_trace(t)
        results = store.search_traces("unicode-検索")
        assert any(r["trace_id"] == t["trace_id"] for r in results)

    def test_search_empty_string_returns_all(self, store: TraceStore):
        for _ in range(3):
            store.save_trace(_make_trace(service="empty-search-svc"))
        results = store.search_traces("")
        assert len(results) >= 3


# ---------------------------------------------------------------------------
# FK constraint resilience: mismatched span trace_ids
# ---------------------------------------------------------------------------

class TestFKConstraintResilience:
    def test_save_trace_with_mismatched_span_trace_id(self, store: TraceStore):
        """Spans with a different trace_id than the parent trace must not
        cause a FOREIGN KEY constraint failure.  The save_trace() method
        should normalise all span trace_ids before inserting."""
        trace_id = uuid.uuid4().hex
        wrong_trace_id = uuid.uuid4().hex  # deliberately different

        trace_data = {
            "trace_id": trace_id,
            "service_name": "external-hook-svc",
            "start_time": time.time(),
            "end_time": time.time() + 1.0,
            "duration_ms": 1000.0,
            "span_count": 2,
            "total_tokens": 30,
            "total_cost_usd": 0.002,
            "has_errors": False,
            "error_count": 0,
            "metadata": {},
            "spans": [
                {
                    "span_id": uuid.uuid4().hex[:16],
                    "trace_id": wrong_trace_id,  # mismatched — simulates external hook
                    "parent_span_id": None,
                    "name": "root",
                    "kind": "llm",
                    "status": "ok",
                    "start_time": time.time(),
                    "end_time": time.time() + 0.5,
                    "duration_ms": 500.0,
                    "attributes": {},
                    "events": [],
                    "token_usage": {"input_tokens": 10, "output_tokens": 5, "total_cost_usd": 0.001},
                    "error": None,
                },
                {
                    "span_id": uuid.uuid4().hex[:16],
                    "trace_id": wrong_trace_id,  # also mismatched
                    "parent_span_id": None,
                    "name": "child",
                    "kind": "tool",
                    "status": "ok",
                    "start_time": time.time(),
                    "end_time": time.time() + 0.2,
                    "duration_ms": 200.0,
                    "attributes": {},
                    "events": [],
                    "token_usage": {"input_tokens": 10, "output_tokens": 5, "total_cost_usd": 0.001},
                    "error": None,
                },
            ],
        }

        # Must not raise IntegrityError / "FOREIGN KEY constraint failed"
        store.save_trace(trace_data)

        retrieved = store.get_trace(trace_id)
        assert retrieved is not None
        assert len(retrieved["spans"]) == 2
        # All stored spans must carry the correct (normalised) trace_id
        for span in retrieved["spans"]:
            assert span["trace_id"] == trace_id


# ---------------------------------------------------------------------------
# FTS5 full-text search
# ---------------------------------------------------------------------------

class TestFTSSearch:
    def test_fts_search_by_span_name(self, store: TraceStore):
        """Searching for a unique span name should return the owning trace."""
        t = _make_trace(service="fts-svc", span_name="embedding_lookup")
        store.save_trace(t)
        results = store.search_traces("embedding_lookup")
        assert any(r["trace_id"] == t["trace_id"] for r in results), (
            "Expected trace not found in FTS results"
        )

    def test_fts_search_by_error_message(self, store: TraceStore):
        """Searching for an error keyword should surface traces with matching error spans."""
        t = _make_trace(service="err-fts-svc", span_name="run_tool", has_error=True)
        # Override error message with a distinctive token
        t["spans"][0]["error"] = {"message": "tokenizer_overflow detected"}
        store.save_trace(t)
        results = store.search_traces("tokenizer_overflow")
        assert any(r["trace_id"] == t["trace_id"] for r in results), (
            "Expected error trace not found via FTS on error_message"
        )

    def test_fts_search_no_results(self, store: TraceStore):
        """Searching for a term that does not exist should return an empty list."""
        t = _make_trace(service="ordinary-svc", span_name="plain_span")
        store.save_trace(t)
        results = store.search_traces("xyzzy_nonexistent_token_42")
        assert results == [], f"Expected no results, got: {results}"

    def test_fts_search_after_delete(self, store: TraceStore):
        """After deleting a trace the FTS index must not return it."""
        t = _make_trace(service="ephemeral-svc", span_name="ephemeral_op")
        store.save_trace(t)

        # Verify it appears before deletion
        before = store.search_traces("ephemeral_op")
        assert any(r["trace_id"] == t["trace_id"] for r in before), (
            "Trace should appear in FTS results before deletion"
        )

        store.delete_trace(t["trace_id"])

        after = store.search_traces("ephemeral_op")
        assert not any(r["trace_id"] == t["trace_id"] for r in after), (
            "Deleted trace should not appear in FTS results"
        )

    def test_fts_fallback_on_invalid_syntax(self, store: TraceStore):
        """An invalid FTS query (e.g. unmatched quote) must not raise — fallback to LIKE."""
        t = _make_trace(service="fallback-svc", span_name="normal_span")
        store.save_trace(t)
        # Unmatched double-quote is invalid FTS5 syntax
        results = store.search_traces('"unmatched')
        # Result must be a list; no exception should propagate
        assert isinstance(results, list)
