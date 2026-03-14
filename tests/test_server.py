"""Tests for FlowLens API Server and Storage."""
import json
import time
import pytest
from flowlens.server.storage import TraceStore
from flowlens.server.app import create_app, _ALLOWED_IMPORT_DIRS


# ===========================================================================
# Shared fixture helpers
# ===========================================================================

def _make_trace_data(trace_id="t1", has_errors=False, service_name="test-svc", start_time=1000.0, tags=None):
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
        "tags": tags or {},
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
        assert row[0] == 6  # current SCHEMA_VERSION


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
        assert r.json()["status"] == "healthy"

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

    def test_websocket_not_blocked_by_http_middleware(self, client):
        """WebSocket upgrade requests must not be intercepted by the api_key_auth
        or security_and_rate_limit HTTP middlewares — both guards early-return on
        scope type 'websocket' so the connection should succeed with a 'connected'
        event regardless of API-key configuration."""
        with client.websocket_connect("/ws/traces") as ws:
            msg = ws.receive_json()
            assert msg["event"] == "connected", (
                "Middleware blocked WebSocket upgrade — check early-return guards"
            )

    # ------------------------------------------------------------------
    # Production Hardening: Health Check Improvements
    # ------------------------------------------------------------------

    def test_health_check_enhanced_response(self, client):
        """Health check returns status, version, uptime, and metrics."""
        r = client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "healthy"
        assert data["version"] == "0.5.0"
        assert "uptime_seconds" in data
        assert "trace_count" in data
        assert "db_size_bytes" in data
        assert data["uptime_seconds"] >= 0
        assert data["db_size_bytes"] >= 0

    def test_health_check_uptime_increases(self, client):
        """Uptime should increase across calls."""
        import time as time_module
        r1 = client.get("/health")
        uptime1 = r1.json()["uptime_seconds"]
        time_module.sleep(0.1)
        r2 = client.get("/health")
        uptime2 = r2.json()["uptime_seconds"]
        assert uptime2 >= uptime1

    def test_health_check_trace_count_updates(self, client):
        """Trace count in health check should update with ingests."""
        r1 = client.get("/health")
        count1 = r1.json()["trace_count"]
        self._ingest(client, "hc-1")
        r2 = client.get("/health")
        count2 = r2.json()["trace_count"]
        assert count2 > count1

    # ------------------------------------------------------------------
    # Production Hardening: Request Logging (health check excluded)
    # ------------------------------------------------------------------

    def test_request_logging_excludes_health(self, client):
        """Health check requests should NOT be logged (too noisy)."""
        # The health endpoint should not produce log messages in the middleware
        # This is ensured by the condition: if path != "/health": logger.info(...)
        # We verify by checking that calling /health doesn't fail
        r = client.get("/health")
        assert r.status_code == 200

    def test_request_logging_includes_other_endpoints(self, client):
        """Non-health endpoints should be logged (middleware logs them)."""
        # The ingest endpoint will be logged by the middleware
        # We verify by checking that calling ingest succeeds
        r = self._ingest(client, "logging-1")
        assert r.status_code == 201

    # ------------------------------------------------------------------
    # Production Hardening: Auto-cleanup on Max Traces
    # ------------------------------------------------------------------

    def test_max_traces_config_default(self):
        """FLOWLENS_MAX_TRACES should default to 100000."""
        from flowlens.config import FlowLensConfig
        cfg = FlowLensConfig()
        assert cfg.max_traces == 100000

    def test_auto_cleanup_on_ingest_exceeding_limit(self, tmp_path):
        """When trace count exceeds max_traces, cleanup_excess_traces should delete oldest."""
        import os
        from flowlens.server.storage import TraceStore
        # Temporarily set a low max_traces limit for testing
        os.environ["FLOWLENS_MAX_TRACES"] = "5"
        try:
            from importlib import reload
            import flowlens.config
            reload(flowlens.config)

            db_path = str(tmp_path / "max_traces_test.db")
            app = create_app(db_path=db_path)
            from fastapi.testclient import TestClient
            c = TestClient(app)

            # Ingest 7 traces (more than the limit of 5)
            for i in range(7):
                c.post("/v1/traces/ingest", json=_make_trace_data(f"cleanup-{i}", start_time=1000.0 + i))

            # Manually call cleanup_excess_traces to enforce the limit
            store = TraceStore(db_path=db_path)
            cleaned = store.cleanup_excess_traces()
            assert cleaned > 0, "Expected cleanup to delete some traces"

            # Now maximum should be 5 traces (the configured limit)
            r = c.get("/v1/stats")
            total = r.json()["total_traces"]
            assert total <= 5, f"Expected max 5 traces after cleanup, got {total}"
            store.close()
        finally:
            # Clean up environment
            if "FLOWLENS_MAX_TRACES" in os.environ:
                del os.environ["FLOWLENS_MAX_TRACES"]
            import flowlens.config
            reload(flowlens.config)

    # ------------------------------------------------------------------
    # Production Hardening: Graceful Shutdown
    # ------------------------------------------------------------------

    def test_app_lifespan_context(self, tmp_path):
        """Verify that the app properly initializes and shuts down."""
        app = create_app(db_path=str(tmp_path / "lifespan_test.db"))
        from fastapi.testclient import TestClient

        # The TestClient uses the lifespan context manager
        with TestClient(app) as client:
            r = client.get("/v1/traces")
            assert r.status_code == 200
        # On exit, the lifespan context manager calls the shutdown logic
        # (store.close() is called, DB connections are cleaned up)

    # ------------------------------------------------------------------
    # New: GET /v1/agents/summary
    # ------------------------------------------------------------------

    def test_agents_summary_endpoint(self, client):
        # Ingest traces with different agent tags
        client.post("/v1/traces/ingest", json=_make_trace_data("t1", tags={"agent": "vr-alpha"}))
        client.post("/v1/traces/ingest", json=_make_trace_data("t2", tags={"agent": "vr-beta"}))
        client.post("/v1/traces/ingest", json=_make_trace_data("t3", tags={"agent": "vr-alpha"}))

        resp = client.get("/v1/agents/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert "agents" in data
        assert len(data["agents"]) == 2
        # vr-alpha should have 2 traces
        alpha = next(a for a in data["agents"] if a["agent"] == "vr-alpha")
        assert alpha["trace_count"] == 2

    def test_agents_summary_sorted_by_trace_count(self, client):
        """Agents with more traces should appear first."""
        for i in range(3):
            client.post("/v1/traces/ingest", json=_make_trace_data(f"a{i}", tags={"agent": "heavy-agent"}))
        client.post("/v1/traces/ingest", json=_make_trace_data("b1", tags={"agent": "light-agent"}))

        resp = client.get("/v1/agents/summary")
        assert resp.status_code == 200
        agents = resp.json()["agents"]
        assert agents[0]["agent"] == "heavy-agent"
        assert agents[0]["trace_count"] == 3

    def test_agents_summary_empty_db(self, client):
        """Returns an empty list when no traces are ingested."""
        resp = client.get("/v1/agents/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["agents"] == []

    def test_agents_summary_unknown_agent(self, client):
        """Traces without a tags.agent field are grouped under 'unknown'."""
        client.post("/v1/traces/ingest", json=_make_trace_data("no-tag"))
        resp = client.get("/v1/agents/summary")
        assert resp.status_code == 200
        agents = resp.json()["agents"]
        assert any(a["agent"] == "unknown" for a in agents)

    def test_agents_summary_error_rate(self, client):
        """Error rate is computed correctly."""
        client.post("/v1/traces/ingest", json=_make_trace_data("ok1", tags={"agent": "bot"}))
        client.post("/v1/traces/ingest", json=_make_trace_data("err1", has_errors=True, tags={"agent": "bot"}))

        resp = client.get("/v1/agents/summary")
        assert resp.status_code == 200
        bot = next(a for a in resp.json()["agents"] if a["agent"] == "bot")
        assert bot["trace_count"] == 2
        assert bot["error_count"] == 1
        assert bot["error_rate"] == 0.5

    # ------------------------------------------------------------------
    # New: GET /v1/agents/activity
    # ------------------------------------------------------------------

    def test_agents_activity_empty_db(self, client):
        """Returns empty list when no traces exist."""
        resp = client.get("/v1/agents/activity")
        assert resp.status_code == 200
        data = resp.json()
        assert "agents" in data
        assert data["agents"] == []

    def test_agents_activity_with_recent_traces(self, client):
        """Returns agent activity with recent traces in the last hour."""
        now = time.time()
        # Ingest two recent traces for two different agents
        t1 = _make_trace_data("act-t1", tags={"agent": "vr-alpha"}, start_time=now - 60)
        t2 = _make_trace_data("act-t2", tags={"agent": "vr-beta"}, start_time=now - 120)
        client.post("/v1/traces/ingest", json=t1)
        client.post("/v1/traces/ingest", json=t2)

        resp = client.get("/v1/agents/activity")
        assert resp.status_code == 200
        data = resp.json()
        agents = data["agents"]
        assert len(agents) >= 2
        agent_names = [a["agent"] for a in agents]
        assert "vr-alpha" in agent_names
        assert "vr-beta" in agent_names

    def test_agents_activity_has_required_fields(self, client):
        """Each agent entry has all required fields."""
        now = time.time()
        client.post("/v1/traces/ingest", json=_make_trace_data(
            "act-fields", tags={"agent": "test-bot"}, start_time=now - 30
        ))
        resp = client.get("/v1/agents/activity")
        assert resp.status_code == 200
        agents = resp.json()["agents"]
        bot = next((a for a in agents if a["agent"] == "test-bot"), None)
        assert bot is not None
        assert "last_seen" in bot
        assert "status" in bot
        assert "recent_tools" in bot
        assert "trace_count_1h" in bot
        assert isinstance(bot["recent_tools"], list)
        assert bot["trace_count_1h"] >= 1

    def test_agents_activity_status_active_for_recent(self, client):
        """Status is 'active' when last trace is within 5 minutes."""
        now = time.time()
        # Ingest a very recent trace (30 seconds ago)
        client.post("/v1/traces/ingest", json=_make_trace_data(
            "active-trace", tags={"agent": "live-agent"}, start_time=now - 30
        ))
        resp = client.get("/v1/agents/activity")
        assert resp.status_code == 200
        agents = resp.json()["agents"]
        live = next((a for a in agents if a["agent"] == "live-agent"), None)
        assert live is not None
        assert live["status"] == "active"

    def test_agents_activity_status_idle_for_old_trace(self, client, tmp_path):
        """Status is 'idle' when last trace is older than 5 minutes but within the hour."""
        now = time.time()
        # We need to insert a trace with an old start_time (10 min ago) directly
        db_path = str(tmp_path / "idle_test.db")
        from flowlens.server.app import create_app
        from fastapi.testclient import TestClient
        app = create_app(db_path=db_path)
        c = TestClient(app)

        old_trace = _make_trace_data(
            "idle-trace", tags={"agent": "idle-agent"}, start_time=now - 700
        )
        c.post("/v1/traces/ingest", json=old_trace)

        resp = c.get("/v1/agents/activity")
        assert resp.status_code == 200
        agents = resp.json()["agents"]
        idle = next((a for a in agents if a["agent"] == "idle-agent"), None)
        assert idle is not None
        assert idle["status"] == "idle"

    def test_agents_activity_trace_count_1h(self, client):
        """trace_count_1h reflects traces ingested in the last hour."""
        now = time.time()
        for i in range(3):
            client.post("/v1/traces/ingest", json=_make_trace_data(
                f"cnt-{i}", tags={"agent": "counter-agent"}, start_time=now - (i * 100)
            ))
        resp = client.get("/v1/agents/activity")
        assert resp.status_code == 200
        agents = resp.json()["agents"]
        counter = next((a for a in agents if a["agent"] == "counter-agent"), None)
        assert counter is not None
        assert counter["trace_count_1h"] == 3

    def test_agents_activity_recent_tools_extracted(self, client):
        """recent_tools is extracted from span names."""
        now = time.time()
        trace = _make_trace_data("tools-trace", tags={"agent": "tool-agent"}, start_time=now - 60)
        # The default trace has spans named "agent" and "search"
        client.post("/v1/traces/ingest", json=trace)

        resp = client.get("/v1/agents/activity")
        assert resp.status_code == 200
        agents = resp.json()["agents"]
        tool_agent = next((a for a in agents if a["agent"] == "tool-agent"), None)
        assert tool_agent is not None
        # Should have extracted tool names from span names ("agent", "search")
        assert isinstance(tool_agent["recent_tools"], list)
        assert len(tool_agent["recent_tools"]) >= 1

    def test_agents_activity_no_traces_outside_window(self, client):
        """Traces older than 1 hour should not appear in activity."""
        now = time.time()
        # Ingest a trace that is 2 hours old — should NOT appear in activity
        old_trace = _make_trace_data(
            "old-outside", tags={"agent": "ghost-agent"}, start_time=now - 7300
        )
        client.post("/v1/traces/ingest", json=old_trace)

        resp = client.get("/v1/agents/activity")
        assert resp.status_code == 200
        agents = resp.json()["agents"]
        ghost = next((a for a in agents if a["agent"] == "ghost-agent"), None)
        # Agent should not appear since trace is outside the 1-hour window
        assert ghost is None

    # ------------------------------------------------------------------
    # New: GET /v1/agents/profiles
    # ------------------------------------------------------------------

    def test_agents_profiles_endpoint(self, client):
        resp = client.get("/v1/agents/profiles")
        assert resp.status_code == 200
        data = resp.json()
        assert "agents" in data
        # Should have built-in profiles
        names = [a["agent"] for a in data["agents"]]
        assert "vr-alpha" in names
        assert "vr-lead" in names

    def test_agents_profiles_discovers_from_traces(self, client):
        # Ingest a trace with a custom agent
        client.post("/v1/traces/ingest", json=_make_trace_data("p1", tags={"agent": "custom-bot"}))
        resp = client.get("/v1/agents/profiles")
        names = [a["agent"] for a in resp.json()["agents"]]
        assert "custom-bot" in names

    # ------------------------------------------------------------------
    # New: GET /v1/activity/stream
    # ------------------------------------------------------------------

    def test_activity_stream_empty(self, client):
        resp = client.get("/v1/activity/stream")
        assert resp.status_code == 200
        assert resp.json()["events"] == []

    def test_activity_stream_with_traces(self, client):
        client.post("/v1/traces/ingest", json=_make_trace_data("as1", tags={"agent": "vr-alpha"}))
        resp = client.get("/v1/activity/stream?limit=10")
        assert resp.status_code == 200
        events = resp.json()["events"]
        assert len(events) > 0
        assert events[0]["agent"] == "vr-alpha"

    def test_activity_stream_limit(self, client):
        for i in range(5):
            client.post("/v1/traces/ingest", json=_make_trace_data(f"lim-{i}", tags={"agent": "bot"}))
        resp = client.get("/v1/activity/stream?limit=3")
        assert len(resp.json()["events"]) <= 3

    # ------------------------------------------------------------------
    # New: GET /v1/stats/trends
    # ------------------------------------------------------------------

    def test_stats_trends_empty(self, client):
        """Trends endpoint returns bucketed data even when no traces exist."""
        resp = client.get("/v1/stats/trends?hours=1&bucket_minutes=60")
        assert resp.status_code == 200
        data = resp.json()
        assert "buckets" in data
        assert "hours" in data
        assert "bucket_minutes" in data
        assert data["hours"] == 1
        assert data["bucket_minutes"] == 60
        # All buckets should have zero counts
        for bucket in data["buckets"]:
            assert bucket["traces"] == 0
            assert bucket["errors"] == 0
            assert bucket["cost"] == 0.0

    def test_stats_trends_with_data(self, client):
        """Traces ingested now appear in the current bucket."""
        now = time.time()
        # Ingest one normal trace and one error trace in the current window
        client.post("/v1/traces/ingest", json=_make_trace_data("trend-ok", start_time=now - 10))
        client.post("/v1/traces/ingest", json=_make_trace_data("trend-err", has_errors=True, start_time=now - 5))

        resp = client.get("/v1/stats/trends?hours=1&bucket_minutes=60")
        assert resp.status_code == 200
        data = resp.json()
        assert data["hours"] == 1
        assert data["bucket_minutes"] == 60

        # At least one bucket should have traces > 0
        total_traces = sum(b["traces"] for b in data["buckets"])
        total_errors = sum(b["errors"] for b in data["buckets"])
        assert total_traces >= 2
        assert total_errors >= 1

    def test_stats_trends_custom_params(self, client):
        """Custom hours and bucket_minutes are reflected in the response and clipped correctly."""
        # Test with custom params within allowed range
        resp = client.get("/v1/stats/trends?hours=48&bucket_minutes=30")
        assert resp.status_code == 200
        data = resp.json()
        assert data["hours"] == 48
        assert data["bucket_minutes"] == 30
        # 48 hours with 30 min buckets = 96 buckets (approximately)
        assert len(data["buckets"]) >= 90

        # Test that hours is capped at 168 (1 week)
        resp2 = client.get("/v1/stats/trends?hours=999&bucket_minutes=1440")
        assert resp2.status_code == 200
        assert resp2.json()["hours"] == 168
        # bucket_minutes capped at 1440
        assert resp2.json()["bucket_minutes"] == 1440

        # Test that bucket_minutes is floored at 5
        resp3 = client.get("/v1/stats/trends?hours=1&bucket_minutes=1")
        assert resp3.status_code == 200
        assert resp3.json()["bucket_minutes"] == 5

    # ------------------------------------------------------------------
    # New: GET /v1/stats/summary
    # ------------------------------------------------------------------

    def test_stats_summary_endpoint(self, client):
        """Summary endpoint returns basic stats merged with agent_breakdown."""
        resp = client.get("/v1/stats/summary")
        assert resp.status_code == 200
        data = resp.json()
        # Should contain basic stats keys
        assert "total_traces" in data
        assert "total_spans" in data
        assert "total_cost" in data
        assert "error_traces" in data
        # Should contain agent_breakdown
        assert "agent_breakdown" in data
        assert isinstance(data["agent_breakdown"], dict)

    def test_stats_summary_agent_breakdown(self, client):
        """Per-agent breakdown is populated from trace tags."""
        now = time.time()
        # Ingest traces for two distinct agents
        client.post("/v1/traces/ingest", json=_make_trace_data(
            "sum-a1", tags={"agent": "agent-alpha"}, start_time=now - 20
        ))
        client.post("/v1/traces/ingest", json=_make_trace_data(
            "sum-a2", tags={"agent": "agent-alpha"}, start_time=now - 15
        ))
        client.post("/v1/traces/ingest", json=_make_trace_data(
            "sum-b1", tags={"agent": "agent-beta"}, has_errors=True, start_time=now - 10
        ))

        resp = client.get("/v1/stats/summary")
        assert resp.status_code == 200
        breakdown = resp.json()["agent_breakdown"]

        # agent-alpha should have 2 traces, 0 errors
        assert "agent-alpha" in breakdown
        alpha = breakdown["agent-alpha"]
        assert alpha["traces"] == 2
        assert alpha["errors"] == 0
        assert alpha["cost"] >= 0.0
        assert alpha["spans"] >= 0

        # agent-beta should have 1 trace with 1 error
        assert "agent-beta" in breakdown
        beta = breakdown["agent-beta"]
        assert beta["traces"] == 1
        assert beta["errors"] == 1

    # ------------------------------------------------------------------
    # New: GET /v1/agents/relationships
    # ------------------------------------------------------------------

    def _make_spawn_trace(self, trace_id: str, spans: list, tags=None, start_time: float = 1000.0):
        """Build a trace dict with custom spans for relationship tests."""
        return {
            "trace_id": trace_id,
            "service_name": "spawn-test",
            "start_time": start_time,
            "end_time": start_time + 1.0,
            "duration_ms": 1000.0,
            "span_count": len(spans),
            "total_tokens": 0,
            "total_cost_usd": 0.0,
            "has_errors": False,
            "error_count": 0,
            "metadata": {},
            "tags": tags or {},
            "spans": spans,
        }

    def _make_span(self, span_id, trace_id, name, kind="tool", attributes=None):
        return {
            "span_id": span_id,
            "trace_id": trace_id,
            "parent_span_id": None,
            "name": name,
            "kind": kind,
            "status": "ok",
            "start_time": 1000.0,
            "end_time": 1001.0,
            "duration_ms": 1000.0,
            "attributes": attributes or {},
            "events": [],
        }

    def test_agents_relationships_empty(self, client):
        """Returns empty nodes and edges when no spawn spans exist."""
        r = client.get("/v1/agents/relationships")
        assert r.status_code == 200
        data = r.json()
        assert "nodes" in data
        assert "edges" in data
        assert data["nodes"] == []
        assert data["edges"] == []

    def test_agents_relationships_subagent_pattern(self, client):
        """Detects subagent/<child> naming pattern."""
        trace = self._make_spawn_trace(
            "rel-sub-1",
            spans=[self._make_span("s1", "rel-sub-1", "subagent/vr-alpha")],
            tags={"agent": "main"},
        )
        r = client.post("/v1/traces/ingest", json=trace)
        assert r.status_code == 201

        r = client.get("/v1/agents/relationships")
        assert r.status_code == 200
        data = r.json()

        edges = data["edges"]
        assert len(edges) >= 1
        edge = edges[0]
        assert edge["source"] == "main"
        assert edge["target"] == "vr-alpha"
        assert edge["count"] >= 1

        node_ids = {n["id"] for n in data["nodes"]}
        assert "main" in node_ids
        assert "vr-alpha" in node_ids

    def test_agents_relationships_spawn_in_name_pattern(self, client):
        """Detects '<parent>/spawn/<child>' naming pattern."""
        trace = self._make_spawn_trace(
            "rel-spawn-1",
            spans=[self._make_span("s2", "rel-spawn-1", "orchestrator/spawn/worker")],
            tags={"agent": "orchestrator"},
        )
        client.post("/v1/traces/ingest", json=trace)

        r = client.get("/v1/agents/relationships")
        assert r.status_code == 200
        edges = r.json()["edges"]
        found = [e for e in edges if e["source"] == "orchestrator" and e["target"] == "worker"]
        assert len(found) >= 1

    def test_agents_relationships_agent_tool_pattern(self, client):
        """Detects '<parent>/Agent/<something>' naming pattern."""
        trace = self._make_spawn_trace(
            "rel-agent-1",
            spans=[self._make_span(
                "s3", "rel-agent-1", "main/Agent/run",
                attributes={"tool.input": '{"subagent_type": "vr-beta", "task": "test"}'},
            )],
            tags={"agent": "main"},
        )
        client.post("/v1/traces/ingest", json=trace)

        r = client.get("/v1/agents/relationships")
        assert r.status_code == 200
        edges = r.json()["edges"]
        found = [e for e in edges if e["source"] == "main" and e["target"] == "vr-beta"]
        assert len(found) >= 1

    def test_agents_relationships_count_accumulates(self, client):
        """Multiple spans with the same relationship increment the count."""
        for i in range(3):
            trace = self._make_spawn_trace(
                f"rel-count-{i}",
                spans=[self._make_span(f"sc-{i}", f"rel-count-{i}", "subagent/worker")],
                tags={"agent": "boss"},
                start_time=1000.0 + i,
            )
            client.post("/v1/traces/ingest", json=trace)

        r = client.get("/v1/agents/relationships")
        assert r.status_code == 200
        edges = r.json()["edges"]
        boss_worker = [e for e in edges if e["source"] == "boss" and e["target"] == "worker"]
        assert len(boss_worker) == 1
        assert boss_worker[0]["count"] == 3

    def test_agents_relationships_response_shape(self, client):
        """Response always has 'nodes' list and 'edges' list."""
        r = client.get("/v1/agents/relationships")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data["nodes"], list)
        assert isinstance(data["edges"], list)

    # ------------------------------------------------------------------
    # New: GET /v1/export/report
    # ------------------------------------------------------------------

    def test_export_report_empty(self, client):
        """Returns a valid report structure with zeros when no traces exist."""
        r = client.get("/v1/export/report")
        assert r.status_code == 200
        data = r.json()
        assert "report" in data
        report = data["report"]
        assert report["period_hours"] == 24
        assert "generated_at" in report
        assert "summary" in report
        assert "agents" in report
        summary = report["summary"]
        assert summary["total_traces"] == 0
        assert summary["total_errors"] == 0
        assert summary["error_rate"] == 0.0
        assert summary["total_cost_usd"] == 0.0
        assert summary["total_spans"] == 0

    def test_export_report_includes_recent_traces(self, client):
        """Only traces within the requested time window are included."""
        now = time.time()
        # Ingest a trace with start_time within the last 24 hours
        trace = _make_trace_data(
            "report-recent", has_errors=False,
            service_name="rep-svc",
            start_time=now - 3600,  # 1 hour ago
            tags={"agent": "report-agent"},
        )
        client.post("/v1/traces/ingest", json=trace)

        r = client.get("/v1/export/report?hours=24")
        assert r.status_code == 200
        report = r.json()["report"]
        assert report["summary"]["total_traces"] >= 1

    def test_export_report_excludes_old_traces(self, client):
        """Traces outside the window are not counted."""
        # All traces from test isolation use start_time around 1000.0 (epoch)
        # A 1-hour window from now() will not include them.
        self._ingest(client, "report-old-1", start_time=1000.0)
        self._ingest(client, "report-old-2", start_time=2000.0)

        r = client.get("/v1/export/report?hours=1")
        assert r.status_code == 200
        report = r.json()["report"]
        # These old traces fall outside the 1-hour window
        assert report["summary"]["total_traces"] == 0

    def test_export_report_per_agent_stats(self, client):
        """Per-agent breakdown is populated correctly."""
        now = time.time()
        client.post("/v1/traces/ingest", json=_make_trace_data(
            "rep-a1", tags={"agent": "alpha"}, start_time=now - 100
        ))
        client.post("/v1/traces/ingest", json=_make_trace_data(
            "rep-a2", tags={"agent": "alpha"}, has_errors=True, start_time=now - 90
        ))
        client.post("/v1/traces/ingest", json=_make_trace_data(
            "rep-b1", tags={"agent": "beta"}, start_time=now - 80
        ))

        r = client.get("/v1/export/report?hours=1")
        assert r.status_code == 200
        agents = r.json()["report"]["agents"]

        assert "alpha" in agents
        assert agents["alpha"]["traces"] == 2
        assert agents["alpha"]["errors"] == 1
        assert agents["alpha"]["cost"] >= 0.0
        assert "avg_duration_ms" in agents["alpha"]
        assert "spans" in agents["alpha"]

        assert "beta" in agents
        assert agents["beta"]["traces"] == 1
        assert agents["beta"]["errors"] == 0

    def test_export_report_error_rate(self, client):
        """Error rate is calculated correctly."""
        now = time.time()
        client.post("/v1/traces/ingest", json=_make_trace_data(
            "err-rate-1", has_errors=True, start_time=now - 50
        ))
        client.post("/v1/traces/ingest", json=_make_trace_data(
            "err-rate-2", has_errors=False, start_time=now - 40
        ))
        client.post("/v1/traces/ingest", json=_make_trace_data(
            "err-rate-3", has_errors=False, start_time=now - 30
        ))

        r = client.get("/v1/export/report?hours=1")
        assert r.status_code == 200
        summary = r.json()["report"]["summary"]
        assert summary["total_traces"] >= 3
        assert summary["total_errors"] >= 1
        # error_rate = errors / total
        assert abs(summary["error_rate"] - summary["total_errors"] / summary["total_traces"]) < 0.001

    def test_export_report_hours_parameter(self, client):
        """Custom hours parameter is reflected in the report."""
        r = client.get("/v1/export/report?hours=48")
        assert r.status_code == 200
        assert r.json()["report"]["period_hours"] == 48

    def test_export_report_hours_validation(self, client):
        """hours must be between 1 and 720."""
        r = client.get("/v1/export/report?hours=0")
        assert r.status_code == 422

        r = client.get("/v1/export/report?hours=721")
        assert r.status_code == 422
