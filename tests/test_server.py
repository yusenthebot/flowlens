"""Tests for FlowLens API Server and Storage."""
import json
import time
import pytest
from flowlens.server.storage import TraceStore
from flowlens.server.app import create_app, _ALLOWED_IMPORT_DIRS


# ===========================================================================
# Shared fixture helpers
# ===========================================================================

def _make_trace_data(trace_id="t1", has_errors=False, service_name="test-svc", start_time=1000.0):
    """Build a minimal but fully valid trace dict for testing."""
    return {
        "trace_id": trace_id,
        "service_name": service_name,
        "start_time": start_time,
        "end_time": start_time + 1.0,
        "duration_ms": 1000.0,
        "span_count": 2,
        "total_tokens": 500,
        "total_cost_usd": 0.005,
        "has_errors": has_errors,
        "error_count": 1 if has_errors else 0,
        "metadata": {"env": "test"},
        "spans": [
            {
                "span_id": f"{trace_id}_s1",
                "trace_id": trace_id,
                "parent_span_id": None,
                "name": "agent",
                "kind": "agent",
                "status": "ok",
                "start_time": start_time,
                "end_time": start_time + 1.0,
                "duration_ms": 1000.0,
                "attributes": {"test": True},
                "events": [],
                "token_usage": {
                    "input_tokens": 300,
                    "output_tokens": 200,
                    "total_cost_usd": 0.005,
                },
            },
            {
                "span_id": f"{trace_id}_s2",
                "trace_id": trace_id,
                "parent_span_id": f"{trace_id}_s1",
                "name": "search",
                "kind": "tool",
                "status": "error" if has_errors else "ok",
                "start_time": start_time + 0.1,
                "end_time": start_time + 0.5,
                "duration_ms": 400.0,
                "attributes": {},
                "events": [],
                "error": {"message": "timeout"} if has_errors else None,
            },
        ],
    }


# ===========================================================================
# Storage Tests
# ===========================================================================

class TestTraceStore:
    @pytest.fixture
    def store(self, tmp_path):
        s = TraceStore(db_path=tmp_path / "test.db")
        yield s
        s.close()

    # ------------------------------------------------------------------
    # Basic CRUD
    # ------------------------------------------------------------------

    def test_save_and_get(self, store):
        store.save_trace(_make_trace_data("t1"))
        result = store.get_trace("t1")
        assert result is not None
        assert result["trace_id"] == "t1"
        assert result["service_name"] == "test-svc"
        assert len(result["spans"]) == 2

    def test_get_nonexistent(self, store):
        assert store.get_trace("no-such") is None

    def test_list_traces(self, store):
        store.save_trace(_make_trace_data("t1"))
        store.save_trace(_make_trace_data("t2", has_errors=True))
        assert len(store.list_traces()) == 2

    def test_list_traces_filter_errors(self, store):
        store.save_trace(_make_trace_data("t1"))
        store.save_trace(_make_trace_data("t2", has_errors=True))
        errors_only = store.list_traces(has_errors=True)
        assert len(errors_only) == 1
        assert errors_only[0]["trace_id"] == "t2"

    def test_list_traces_filter_service(self, store):
        store.save_trace(_make_trace_data("t1"))
        assert len(store.list_traces(service_name="test-svc")) == 1
        assert len(store.list_traces(service_name="other-svc")) == 0

    def test_cost_breakdown(self, store):
        store.save_trace(_make_trace_data("t1"))
        store.save_trace(_make_trace_data("t2"))
        breakdown = store.get_cost_breakdown(group_by="service_name")
        assert len(breakdown) >= 1
        assert breakdown[0]["dimension"] == "test-svc"
        assert breakdown[0]["total_cost_usd"] > 0

    def test_stats(self, store):
        store.save_trace(_make_trace_data("t1"))
        store.save_trace(_make_trace_data("t2", has_errors=True))
        stats = store.get_stats()
        assert stats["total_traces"] == 2
        assert stats["error_traces"] == 1
        assert stats["total_tokens"] == 1000

    # ------------------------------------------------------------------
    # New: delete_trace
    # ------------------------------------------------------------------

    def test_delete_trace_existing(self, store):
        store.save_trace(_make_trace_data("del-1"))
        assert store.get_trace("del-1") is not None
        deleted = store.delete_trace("del-1")
        assert deleted is True
        assert store.get_trace("del-1") is None

    def test_delete_trace_nonexistent(self, store):
        assert store.delete_trace("ghost") is False

    def test_delete_trace_cascades_spans(self, store):
        """Deleting a trace must also remove its spans (ON DELETE CASCADE)."""
        store.save_trace(_make_trace_data("casc-1"))
        store.delete_trace("casc-1")
        # Direct span query should return nothing
        rows = store._conn.execute(
            "SELECT count(*) FROM spans WHERE trace_id = 'casc-1'"
        ).fetchone()
        assert rows[0] == 0

    # ------------------------------------------------------------------
    # New: get_traces_by_time_range
    # ------------------------------------------------------------------

    def test_get_traces_by_time_range(self, store):
        for i in range(5):
            store.save_trace(_make_trace_data(f"tr-{i}", start_time=float(1000 + i * 10)))
        # Only traces with start_time in [1010, 1030] should be returned
        results = store.get_traces_by_time_range(start=1010.0, end=1030.0)
        assert len(results) == 3
        for r in results:
            assert 1010.0 <= r["start_time"] <= 1030.0

    def test_get_traces_by_time_range_empty(self, store):
        store.save_trace(_make_trace_data("tr-x", start_time=2000.0))
        assert store.get_traces_by_time_range(start=3000.0, end=4000.0) == []

    # ------------------------------------------------------------------
    # New: get_error_traces
    # ------------------------------------------------------------------

    def test_get_error_traces(self, store):
        store.save_trace(_make_trace_data("ok-1"))
        store.save_trace(_make_trace_data("err-1", has_errors=True))
        store.save_trace(_make_trace_data("err-2", has_errors=True))
        results = store.get_error_traces()
        assert len(results) == 2
        for r in results:
            assert r["has_errors"] == 1

    def test_get_error_traces_pagination(self, store):
        for i in range(5):
            store.save_trace(_make_trace_data(f"e{i}", has_errors=True))
        page1 = store.get_error_traces(limit=3, offset=0)
        page2 = store.get_error_traces(limit=3, offset=3)
        assert len(page1) == 3
        assert len(page2) == 2

    # ------------------------------------------------------------------
    # New: search_traces
    # ------------------------------------------------------------------

    def test_search_traces_by_span_name(self, store):
        store.save_trace(_make_trace_data("s1"))  # has span named "search"
        store.save_trace(_make_trace_data("s2", service_name="other-svc"))
        results = store.search_traces("search")
        ids = [r["trace_id"] for r in results]
        # Both traces have a span named "search"
        assert "s1" in ids
        assert "s2" in ids

    def test_search_traces_by_service_name(self, store):
        store.save_trace(_make_trace_data("svc1", service_name="my-special-svc"))
        store.save_trace(_make_trace_data("svc2", service_name="other"))
        results = store.search_traces("special")
        assert len(results) == 1
        assert results[0]["trace_id"] == "svc1"

    def test_search_traces_by_error_message(self, store):
        store.save_trace(_make_trace_data("err-search", has_errors=True))  # error: "timeout"
        store.save_trace(_make_trace_data("no-err"))
        results = store.search_traces("timeout")
        assert len(results) == 1
        assert results[0]["trace_id"] == "err-search"

    def test_search_traces_no_match(self, store):
        store.save_trace(_make_trace_data("t1"))
        assert store.search_traces("zzz_no_match_zzz") == []

    # ------------------------------------------------------------------
    # New: cleanup_old_traces
    # ------------------------------------------------------------------

    def test_cleanup_old_traces(self, store):
        # Manually insert a trace with an old created_at timestamp
        old_time = time.time() - 40 * 86_400  # 40 days ago
        store._conn.execute(
            """INSERT INTO traces
               (trace_id, service_name, start_time, end_time, duration_ms,
                span_count, total_tokens, total_cost_usd, has_errors,
                error_count, metadata_json, created_at)
               VALUES (?, '', 0, 0, 0, 0, 0, 0, 0, 0, '{}', ?)""",
            ("old-trace", old_time),
        )
        store._conn.commit()
        store.save_trace(_make_trace_data("new-trace"))  # created now

        deleted = store.cleanup_old_traces(days=30)
        assert deleted == 1
        assert store.get_trace("old-trace") is None
        assert store.get_trace("new-trace") is not None

    def test_cleanup_old_traces_none_to_delete(self, store):
        store.save_trace(_make_trace_data("recent"))
        deleted = store.cleanup_old_traces(days=30)
        assert deleted == 0

    # ------------------------------------------------------------------
    # New: get_cost_trends
    # ------------------------------------------------------------------

    def test_get_cost_trends_daily(self, store):
        store.save_trace(_make_trace_data("t1"))
        store.save_trace(_make_trace_data("t2"))
        trends = store.get_cost_trends(granularity="daily")
        assert isinstance(trends, list)
        # At minimum 1 bucket should exist
        assert len(trends) >= 1
        bucket = trends[0]
        assert "bucket" in bucket
        assert "total_cost_usd" in bucket
        assert "trace_count" in bucket

    def test_get_cost_trends_hourly(self, store):
        store.save_trace(_make_trace_data("t1"))
        trends = store.get_cost_trends(granularity="hourly")
        assert len(trends) >= 1
        # Hourly bucket should look like "2026-03-14T10:00:00"
        assert "T" in trends[0]["bucket"]

    # ------------------------------------------------------------------
    # New: get_pattern_summary
    # ------------------------------------------------------------------

    def test_get_pattern_summary(self, store):
        store.save_trace(_make_trace_data("p1"))
        store.save_trace(_make_trace_data("p2", has_errors=True))
        summary = store.get_pattern_summary()
        assert "by_kind" in summary
        assert "by_name" in summary
        assert "top_errors" in summary
        # Should have "agent" and "tool" kinds
        kinds = [k["kind"] for k in summary["by_kind"]]
        assert "agent" in kinds
        assert "tool" in kinds
        # Top errors should include the timeout from has_errors traces
        error_msgs = [e["error_message"] for e in summary["top_errors"]]
        assert "timeout" in error_msgs

    # ------------------------------------------------------------------
    # Schema migration
    # ------------------------------------------------------------------

    def test_schema_version_is_set(self, store):
        row = store._conn.execute("SELECT version FROM schema_version").fetchone()
        assert row is not None
        assert row[0] == 3  # current SCHEMA_VERSION


# ===========================================================================
# API Tests
# ===========================================================================

class TestAPI:
    @pytest.fixture
    def client(self, tmp_path):
        app = create_app(db_path=str(tmp_path / "api_test.db"))
        from fastapi.testclient import TestClient
        return TestClient(app)

    # Reuse the same helper
    def _trace(self, trace_id="api-t1", has_errors=False, service_name="api-test", start_time=1000.0):
        return _make_trace_data(trace_id, has_errors=has_errors, service_name=service_name, start_time=start_time)

    def _ingest(self, client, trace_id="api-t1", **kwargs):
        r = client.post("/v1/traces/ingest", json=self._trace(trace_id, **kwargs))
        assert r.status_code == 201
        return r

    # ------------------------------------------------------------------
    # Existing tests (preserved)
    # ------------------------------------------------------------------

    def test_health(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_ingest_and_get(self, client):
        r = self._ingest(client, "api-t1")
        assert r.json()["trace_id"] == "api-t1"

        r = client.get("/v1/traces/api-t1")
        assert r.status_code == 200
        assert r.json()["trace_id"] == "api-t1"

    def test_list_traces(self, client):
        r = client.get("/v1/traces")
        assert r.status_code == 200
        assert "traces" in r.json()

    def test_get_nonexistent_trace(self, client):
        r = client.get("/v1/traces/no-such")
        assert r.status_code == 404

    def test_stats(self, client):
        r = client.get("/v1/stats")
        assert r.status_code == 200
        assert "total_traces" in r.json()

    def test_dag_endpoint(self, client):
        trace_data = {
            "trace_id": "dag-t1",
            "service_name": "dag-test",
            "start_time": 1000,
            "end_time": 1001,
            "duration_ms": 1000,
            "span_count": 2,
            "total_tokens": 0,
            "total_cost_usd": 0,
            "has_errors": True,
            "error_count": 1,
            "metadata": {},
            "spans": [
                {
                    "span_id": "d1",
                    "trace_id": "dag-t1",
                    "name": "agent",
                    "kind": "agent",
                    "status": "ok",
                    "start_time": 1000,
                    "end_time": 1001,
                    "attributes": {},
                    "events": [],
                },
                {
                    "span_id": "d2",
                    "trace_id": "dag-t1",
                    "parent_span_id": "d1",
                    "name": "search",
                    "kind": "tool",
                    "status": "error",
                    "start_time": 1000.1,
                    "end_time": 1000.5,
                    "attributes": {},
                    "events": [],
                    "error": {"message": "timeout"},
                },
            ],
        }
        client.post("/v1/traces/ingest", json=trace_data)
        r = client.get("/v1/traces/dag-t1/dag")
        assert r.status_code == 200
        dag = r.json()
        assert dag["has_errors"]
        assert len(dag["root_causes"]) == 1
        assert dag["root_causes"][0] == "d2"

    def test_list_traces_pagination(self, client):
        for i in range(10):
            self._ingest(client, f"pag-{i}", service_name="pagination-test", start_time=1000.0 + i)
        r = client.get("/v1/traces?limit=3&offset=0")
        assert r.status_code == 200
        data = r.json()
        assert len(data["traces"]) == 3
        assert data["limit"] == 3

        r = client.get("/v1/traces?limit=3&offset=3")
        assert r.status_code == 200
        assert r.json()["offset"] == 3
        assert len(r.json()["traces"]) == 3

    def test_cost_breakdown_grouping(self, client):
        for service in ["service-a", "service-b", "service-a"]:
            client.post(
                "/v1/traces/ingest",
                json={
                    "trace_id": f"cost-{service}-x",
                    "service_name": service,
                    "start_time": 1000,
                    "end_time": 1001,
                    "duration_ms": 1000,
                    "span_count": 0,
                    "total_tokens": 1000,
                    "total_cost_usd": 0.01,
                    "has_errors": False,
                    "error_count": 0,
                    "metadata": {},
                    "spans": [],
                },
            )
        r = client.get("/v1/cost/breakdown?group_by=service_name")
        assert r.status_code == 200
        dimensions = [item["dimension"] for item in r.json()]
        assert "service-a" in dimensions
        assert "service-b" in dimensions

    def test_import_jsonl_file(self, tmp_path):
        # The import endpoint requires the target directory to be in _ALLOWED_IMPORT_DIRS.
        allowed = tmp_path.resolve()
        _ALLOWED_IMPORT_DIRS.append(allowed)
        try:
            app = create_app(db_path=str(tmp_path / "import_api_test.db"))
            from fastapi.testclient import TestClient
            c = TestClient(app)

            jsonl_file = tmp_path / "traces.jsonl"
            with open(jsonl_file, "w") as f:
                f.write(json.dumps(_make_trace_data("jsonl-1", service_name="import-test")) + "\n")
                f.write(json.dumps(_make_trace_data("jsonl-2", service_name="import-test", start_time=1001.0)) + "\n")

            r = c.post(f"/v1/traces/import?file_path={jsonl_file}")
            assert r.status_code == 201
            data = r.json()
            assert data["imported"] == 2
            assert data["errors"] == 0

            assert c.get("/v1/traces/jsonl-1").status_code == 200
            assert c.get("/v1/traces/jsonl-2").status_code == 200
        finally:
            _ALLOWED_IMPORT_DIRS.remove(allowed)

    # ------------------------------------------------------------------
    # New: DELETE /v1/traces/{trace_id}
    # ------------------------------------------------------------------

    def test_delete_trace_endpoint(self, client):
        self._ingest(client, "del-api-1")
        r = client.delete("/v1/traces/del-api-1")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "deleted"
        assert data["trace_id"] == "del-api-1"
        # Confirm it's gone
        assert client.get("/v1/traces/del-api-1").status_code == 404

    def test_delete_trace_not_found(self, client):
        r = client.delete("/v1/traces/ghost-trace")
        assert r.status_code == 404

    # ------------------------------------------------------------------
    # New: GET /v1/traces/errors
    # ------------------------------------------------------------------

    def test_list_error_traces_endpoint(self, client):
        self._ingest(client, "ok-1")
        self._ingest(client, "err-1", has_errors=True)
        self._ingest(client, "err-2", has_errors=True)

        r = client.get("/v1/traces/errors")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 2
        for trace in data["traces"]:
            assert trace["has_errors"] == 1

    def test_list_error_traces_empty(self, client):
        self._ingest(client, "ok-1")
        r = client.get("/v1/traces/errors")
        assert r.status_code == 200
        assert r.json()["total"] == 0

    # ------------------------------------------------------------------
    # New: GET /v1/traces/search
    # ------------------------------------------------------------------

    def test_search_endpoint(self, client):
        self._ingest(client, "search-1", service_name="my-special-service")
        self._ingest(client, "search-2", service_name="other-service")

        r = client.get("/v1/traces/search?q=special")
        assert r.status_code == 200
        data = r.json()
        ids = [t["trace_id"] for t in data["traces"]]
        assert "search-1" in ids
        assert "search-2" not in ids

    def test_search_endpoint_missing_query(self, client):
        r = client.get("/v1/traces/search")
        # q is required — FastAPI returns 422 Unprocessable Entity
        assert r.status_code == 422

    def test_search_endpoint_no_results(self, client):
        self._ingest(client, "t1")
        r = client.get("/v1/traces/search?q=zzznomatch")
        assert r.status_code == 200
        assert r.json()["total"] == 0

    # ------------------------------------------------------------------
    # New: POST /v1/traces/cleanup
    # ------------------------------------------------------------------

    def test_cleanup_endpoint(self, client, tmp_path):
        # We need a store we can poke directly to set old created_at
        db_path = str(tmp_path / "cleanup_test.db")
        app = create_app(db_path=db_path)
        from fastapi.testclient import TestClient
        c = TestClient(app)

        # Ingest a fresh trace (will have current created_at)
        c.post("/v1/traces/ingest", json=_make_trace_data("new-trace"))

        # Manually age an old trace in the DB
        store = TraceStore(db_path=db_path)
        old_time = time.time() - 40 * 86_400
        store._conn.execute(
            """INSERT INTO traces
               (trace_id, service_name, start_time, end_time, duration_ms,
                span_count, total_tokens, total_cost_usd, has_errors,
                error_count, metadata_json, created_at)
               VALUES (?, '', 0, 0, 0, 0, 0, 0, 0, 0, '{}', ?)""",
            ("old-trace", old_time),
        )
        store._conn.commit()
        store.close()

        r = c.post("/v1/traces/cleanup", json={"days": 30})
        assert r.status_code == 200
        data = r.json()
        assert data["deleted"] == 1
        assert data["days"] == 30

    def test_cleanup_endpoint_default_days(self, client):
        r = client.post("/v1/traces/cleanup", json={})
        assert r.status_code == 200
        # No old traces → 0 deleted, but endpoint must work
        assert "deleted" in r.json()

    # ------------------------------------------------------------------
    # New: GET /v1/cost/trends
    # ------------------------------------------------------------------

    def test_cost_trends_daily(self, client):
        self._ingest(client, "ct-1")
        self._ingest(client, "ct-2")
        r = client.get("/v1/cost/trends")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        assert "bucket" in data[0]
        assert "total_cost_usd" in data[0]

    def test_cost_trends_hourly(self, client):
        self._ingest(client, "ct-h1")
        r = client.get("/v1/cost/trends?granularity=hourly")
        assert r.status_code == 200
        data = r.json()
        assert len(data) >= 1
        # Hourly bucket format contains "T"
        assert "T" in data[0]["bucket"]

    def test_cost_trends_invalid_granularity(self, client):
        r = client.get("/v1/cost/trends?granularity=weekly")
        assert r.status_code == 422

    # ------------------------------------------------------------------
    # New: GET /v1/patterns/summary
    # ------------------------------------------------------------------

    def test_patterns_summary(self, client):
        self._ingest(client, "pat-1")
        self._ingest(client, "pat-2", has_errors=True)
        r = client.get("/v1/patterns/summary")
        assert r.status_code == 200
        data = r.json()
        assert "by_kind" in data
        assert "by_name" in data
        assert "top_errors" in data
        kinds = [k["kind"] for k in data["by_kind"]]
        assert "agent" in kinds

    def test_patterns_summary_empty_db(self, client):
        r = client.get("/v1/patterns/summary")
        assert r.status_code == 200
        data = r.json()
        assert data["by_kind"] == []
        assert data["top_errors"] == []

    # ------------------------------------------------------------------
    # Rate-limit headers
    # ------------------------------------------------------------------

    def test_rate_limit_headers_present(self, client):
        r = client.get("/health")
        assert "x-ratelimit-limit" in r.headers
        assert "x-ratelimit-remaining" in r.headers

    def test_rate_limit_decrements(self, client):
        r1 = client.get("/health")
        r2 = client.get("/health")
        rem1 = int(r1.headers["x-ratelimit-remaining"])
        rem2 = int(r2.headers["x-ratelimit-remaining"])
        assert rem2 < rem1

    # ------------------------------------------------------------------
    # Pydantic validation
    # ------------------------------------------------------------------

    def test_ingest_missing_trace_id(self, client):
        r = client.post("/v1/traces/ingest", json={"service_name": "x"})
        assert r.status_code == 422

    def test_ingest_negative_tokens(self, client):
        data = _make_trace_data("bad-tokens")
        data["total_tokens"] = -1
        r = client.post("/v1/traces/ingest", json=data)
        assert r.status_code == 422

    def test_cleanup_invalid_days(self, client):
        r = client.post("/v1/traces/cleanup", json={"days": 0})
        assert r.status_code == 422

    # ------------------------------------------------------------------
    # WebSocket
    # ------------------------------------------------------------------

    def test_websocket_handshake(self, client):
        with client.websocket_connect("/ws/traces") as ws:
            msg = ws.receive_json()
            assert msg["event"] == "connected"
            assert "message" in msg["data"]

    def test_websocket_receives_ingest_broadcast(self, client):
        with client.websocket_connect("/ws/traces") as ws:
            # Consume the handshake
            ws.receive_json()
            # Ingest a trace — the server should broadcast it
            client.post("/v1/traces/ingest", json=_make_trace_data("ws-t1"))
            msg = ws.receive_json()
            assert msg["event"] == "trace_ingested"
            assert msg["data"]["trace_id"] == "ws-t1"
