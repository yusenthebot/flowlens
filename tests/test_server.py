"""Tests for FlowLens API Server and Storage."""
import json
import os
import tempfile
import pytest
from flowlens.server.storage import TraceStore
from flowlens.server.app import create_app


# ===== Storage Tests =====

class TestTraceStore:
    @pytest.fixture
    def store(self, tmp_path):
        s = TraceStore(db_path=tmp_path / "test.db")
        yield s
        s.close()

    def _make_trace_data(self, trace_id="t1", has_errors=False):
        return {
            "trace_id": trace_id,
            "service_name": "test-svc",
            "start_time": 1000.0,
            "end_time": 1001.0,
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
                    "start_time": 1000.0,
                    "end_time": 1001.0,
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
                    "start_time": 1000.1,
                    "end_time": 1000.5,
                    "duration_ms": 400.0,
                    "attributes": {},
                    "events": [],
                    "error": {"message": "timeout"} if has_errors else None,
                },
            ],
        }

    def test_save_and_get(self, store):
        data = self._make_trace_data("t1")
        store.save_trace(data)

        result = store.get_trace("t1")
        assert result is not None
        assert result["trace_id"] == "t1"
        assert result["service_name"] == "test-svc"
        assert len(result["spans"]) == 2

    def test_get_nonexistent(self, store):
        assert store.get_trace("no-such") is None

    def test_list_traces(self, store):
        store.save_trace(self._make_trace_data("t1"))
        store.save_trace(self._make_trace_data("t2", has_errors=True))

        traces = store.list_traces()
        assert len(traces) == 2

    def test_list_traces_filter_errors(self, store):
        store.save_trace(self._make_trace_data("t1"))
        store.save_trace(self._make_trace_data("t2", has_errors=True))

        errors_only = store.list_traces(has_errors=True)
        assert len(errors_only) == 1
        assert errors_only[0]["trace_id"] == "t2"

    def test_list_traces_filter_service(self, store):
        store.save_trace(self._make_trace_data("t1"))
        results = store.list_traces(service_name="test-svc")
        assert len(results) == 1
        results = store.list_traces(service_name="other-svc")
        assert len(results) == 0

    def test_cost_breakdown(self, store):
        store.save_trace(self._make_trace_data("t1"))
        store.save_trace(self._make_trace_data("t2"))

        breakdown = store.get_cost_breakdown(group_by="service_name")
        assert len(breakdown) >= 1
        assert breakdown[0]["dimension"] == "test-svc"
        assert breakdown[0]["total_cost_usd"] > 0

    def test_stats(self, store):
        store.save_trace(self._make_trace_data("t1"))
        store.save_trace(self._make_trace_data("t2", has_errors=True))

        stats = store.get_stats()
        assert stats["total_traces"] == 2
        assert stats["error_traces"] == 1
        assert stats["total_tokens"] == 1000


# ===== API Tests =====

class TestAPI:
    @pytest.fixture
    def client(self, tmp_path):
        app = create_app(db_path=str(tmp_path / "api_test.db"))
        from fastapi.testclient import TestClient
        return TestClient(app)

    def test_health(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_ingest_and_get(self, client):
        trace_data = {
            "trace_id": "api-t1",
            "service_name": "api-test",
            "start_time": 1000,
            "end_time": 1001,
            "duration_ms": 1000,
            "span_count": 1,
            "total_tokens": 100,
            "total_cost_usd": 0.001,
            "has_errors": False,
            "error_count": 0,
            "metadata": {},
            "spans": [
                {
                    "span_id": "s1",
                    "trace_id": "api-t1",
                    "name": "root",
                    "kind": "agent",
                    "status": "ok",
                    "start_time": 1000,
                    "end_time": 1001,
                    "duration_ms": 1000,
                    "attributes": {},
                    "events": [],
                },
            ],
        }
        r = client.post("/v1/traces/ingest", json=trace_data)
        assert r.status_code == 201
        assert r.json()["trace_id"] == "api-t1"

        # Get it back
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
        """Ingest a trace with errors then get its DAG"""
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
