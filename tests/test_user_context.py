"""
Tests for user/session/experiment context tracking in FlowLens.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from flowlens.sdk.models import Trace
from flowlens.sdk.tracer import FlowLens
from flowlens.server.app import create_app
from flowlens.server.storage import TraceStore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def store(tmp_path):
    s = TraceStore(db_path=str(tmp_path / "test.db"))
    yield s
    s.close()


@pytest.fixture()
def client(tmp_path):
    app = create_app(db_path=str(tmp_path / "test.db"))
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def _make_trace_payload(**kwargs) -> dict:
    """Build a minimal valid ingest payload."""
    import time
    import uuid

    payload = {
        "trace_id": uuid.uuid4().hex,
        "service_name": "test-svc",
        "start_time": time.time(),
        "end_time": time.time() + 0.5,
        "duration_ms": 500.0,
        "total_tokens": 100,
        "total_cost_usd": 0.001,
        "has_errors": False,
        "error_count": 0,
        "span_count": 1,
        "metadata": {},
        "spans": [],
    }
    payload.update(kwargs)
    return payload


# ---------------------------------------------------------------------------
# Part 1: Model round-trip
# ---------------------------------------------------------------------------


class TestTraceModel:
    def test_default_fields_are_none(self):
        trace = Trace(service_name="svc")
        assert trace.user_id is None
        assert trace.session_id is None
        assert trace.experiment is None
        assert trace.tags is None

    def test_fields_assigned(self):
        trace = Trace(
            service_name="svc",
            user_id="u1",
            session_id="sess-abc",
            experiment="exp-A",
            tags={"env": "prod", "region": "us-east-1"},
        )
        assert trace.user_id == "u1"
        assert trace.session_id == "sess-abc"
        assert trace.experiment == "exp-A"
        assert trace.tags == {"env": "prod", "region": "us-east-1"}

    def test_to_dict_includes_new_fields(self):
        trace = Trace(
            service_name="svc",
            user_id="u1",
            session_id="sess-abc",
            experiment="exp-A",
            tags={"k": "v"},
        )
        d = trace.to_dict()
        assert d["user_id"] == "u1"
        assert d["session_id"] == "sess-abc"
        assert d["experiment"] == "exp-A"
        assert d["tags"] == {"k": "v"}

    def test_to_dict_none_fields(self):
        trace = Trace(service_name="svc")
        d = trace.to_dict()
        assert "user_id" in d
        assert d["user_id"] is None
        assert d["session_id"] is None
        assert d["experiment"] is None
        assert d["tags"] is None


# ---------------------------------------------------------------------------
# Part 2: Storage round-trip
# ---------------------------------------------------------------------------


class TestStorageUserContext:
    def test_save_and_retrieve_user_context(self, store):
        import time
        import uuid

        trace_id = uuid.uuid4().hex
        payload = {
            "trace_id": trace_id,
            "service_name": "svc",
            "start_time": time.time(),
            "end_time": time.time() + 1,
            "duration_ms": 1000.0,
            "total_tokens": 0,
            "total_cost_usd": 0.0,
            "has_errors": False,
            "error_count": 0,
            "span_count": 0,
            "metadata": {},
            "user_id": "alice",
            "session_id": "sess-001",
            "experiment": "beta-prompt",
            "tags": {"env": "staging"},
            "spans": [],
        }
        store.save_trace(payload)
        retrieved = store.get_trace(trace_id)
        assert retrieved is not None
        assert retrieved["user_id"] == "alice"
        assert retrieved["session_id"] == "sess-001"
        assert retrieved["experiment"] == "beta-prompt"
        assert retrieved["tags"] == {"env": "staging"}

    def test_filter_by_user_id(self, store):
        import time
        import uuid

        for user in ("alice", "bob", "alice"):
            store.save_trace(
                {
                    "trace_id": uuid.uuid4().hex,
                    "service_name": "svc",
                    "start_time": time.time(),
                    "end_time": time.time() + 1,
                    "duration_ms": 100.0,
                    "total_tokens": 0,
                    "total_cost_usd": 0.0,
                    "has_errors": False,
                    "error_count": 0,
                    "span_count": 0,
                    "metadata": {},
                    "user_id": user,
                    "spans": [],
                }
            )
        alice_traces = store.list_traces(user_id="alice")
        assert len(alice_traces) == 2
        bob_traces = store.list_traces(user_id="bob")
        assert len(bob_traces) == 1

    def test_filter_by_session_id(self, store):
        import time
        import uuid

        for sess in ("s1", "s2", "s1"):
            store.save_trace(
                {
                    "trace_id": uuid.uuid4().hex,
                    "service_name": "svc",
                    "start_time": time.time(),
                    "end_time": time.time() + 1,
                    "duration_ms": 100.0,
                    "total_tokens": 0,
                    "total_cost_usd": 0.0,
                    "has_errors": False,
                    "error_count": 0,
                    "span_count": 0,
                    "metadata": {},
                    "session_id": sess,
                    "spans": [],
                }
            )
        assert len(store.list_traces(session_id="s1")) == 2
        assert len(store.list_traces(session_id="s2")) == 1

    def test_filter_by_experiment(self, store):
        import time
        import uuid

        for exp in ("ctrl", "variant-A", "ctrl"):
            store.save_trace(
                {
                    "trace_id": uuid.uuid4().hex,
                    "service_name": "svc",
                    "start_time": time.time(),
                    "end_time": time.time() + 1,
                    "duration_ms": 100.0,
                    "total_tokens": 0,
                    "total_cost_usd": 0.0,
                    "has_errors": False,
                    "error_count": 0,
                    "span_count": 0,
                    "metadata": {},
                    "experiment": exp,
                    "spans": [],
                }
            )
        assert len(store.list_traces(experiment="ctrl")) == 2
        assert len(store.list_traces(experiment="variant-A")) == 1


# ---------------------------------------------------------------------------
# Part 3: API endpoints
# ---------------------------------------------------------------------------


class TestAPIFilters:
    def test_ingest_with_user_context(self, client):
        payload = _make_trace_payload(user_id="u1", session_id="sess-1", experiment="exp-A")
        resp = client.post("/v1/traces/ingest", json=payload)
        assert resp.status_code == 201

        # Verify it's retrievable
        resp2 = client.get(f"/v1/traces/{payload['trace_id']}")
        assert resp2.status_code == 200
        data = resp2.json()
        assert data["user_id"] == "u1"
        assert data["session_id"] == "sess-1"
        assert data["experiment"] == "exp-A"

    def test_list_filter_user_id(self, client):
        t1 = _make_trace_payload(user_id="alice")
        t2 = _make_trace_payload(user_id="bob")
        client.post("/v1/traces/ingest", json=t1)
        client.post("/v1/traces/ingest", json=t2)

        resp = client.get("/v1/traces?user_id=alice")
        assert resp.status_code == 200
        traces = resp.json()["traces"]
        assert all(t["user_id"] == "alice" for t in traces)
        assert len(traces) == 1

    def test_list_filter_session_id(self, client):
        t1 = _make_trace_payload(session_id="sess-abc")
        t2 = _make_trace_payload(session_id="sess-xyz")
        client.post("/v1/traces/ingest", json=t1)
        client.post("/v1/traces/ingest", json=t2)

        resp = client.get("/v1/traces?session_id=sess-abc")
        assert resp.status_code == 200
        traces = resp.json()["traces"]
        assert len(traces) == 1

    def test_list_filter_experiment(self, client):
        t1 = _make_trace_payload(experiment="ctrl")
        t2 = _make_trace_payload(experiment="variant")
        t3 = _make_trace_payload(experiment="ctrl")
        for t in [t1, t2, t3]:
            client.post("/v1/traces/ingest", json=t)

        resp = client.get("/v1/traces?experiment=ctrl")
        assert resp.status_code == 200
        assert resp.json()["total"] == 2

    def test_user_metrics_endpoint(self, client):
        for uid in ["alice", "bob", "alice"]:
            t = _make_trace_payload(user_id=uid)
            client.post("/v1/traces/ingest", json=t)

        resp = client.get("/v1/metrics/users")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        users = {row["user_id"]: row for row in data}
        assert "alice" in users
        assert users["alice"]["trace_count"] == 2
        assert "bob" in users
        assert users["bob"]["trace_count"] == 1

    def test_experiment_metrics_endpoint(self, client):
        for exp in ["ctrl", "variant", "ctrl"]:
            t = _make_trace_payload(experiment=exp)
            client.post("/v1/traces/ingest", json=t)

        resp = client.get("/v1/metrics/experiments")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        exps = {row["experiment"]: row for row in data}
        assert "ctrl" in exps
        assert exps["ctrl"]["trace_count"] == 2
        assert "variant" in exps


# ---------------------------------------------------------------------------
# Part 4: SDK start_trace() with context fields
# ---------------------------------------------------------------------------


class TestSDKUserContext:
    def test_start_trace_with_user_fields(self, tmp_path):
        lens = FlowLens(service_name="svc", export_to="console")
        trace = lens.start_trace(
            user_id="u42",
            session_id="sess-99",
            experiment="prompt-v2",
            tags={"region": "eu"},
        )
        assert trace.user_id == "u42"
        assert trace.session_id == "sess-99"
        assert trace.experiment == "prompt-v2"
        assert trace.tags == {"region": "eu"}
        lens.end_trace(trace)

    def test_start_trace_to_dict_round_trip(self, tmp_path):
        lens = FlowLens(service_name="svc", export_to="console")
        trace = lens.start_trace(user_id="u1", session_id="s1", experiment="e1", tags={"a": "b"})
        d = trace.to_dict()
        assert d["user_id"] == "u1"
        assert d["session_id"] == "s1"
        assert d["experiment"] == "e1"
        assert d["tags"] == {"a": "b"}
        lens.end_trace(trace)
