"""
Tests for feedback collection in FlowLens.
"""

from __future__ import annotations

import time
import uuid

import pytest
from fastapi.testclient import TestClient

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


def _ingest_trace(client, **kwargs) -> str:
    """Ingest a minimal trace and return its trace_id."""
    payload = {
        "trace_id": uuid.uuid4().hex,
        "service_name": "svc",
        "start_time": time.time(),
        "end_time": time.time() + 1.0,
        "duration_ms": 1000.0,
        "total_tokens": 0,
        "total_cost_usd": 0.0,
        "has_errors": False,
        "error_count": 0,
        "span_count": 0,
        "metadata": {},
        "spans": [],
    }
    payload.update(kwargs)
    resp = client.post("/v1/traces/ingest", json=payload)
    assert resp.status_code == 201
    return payload["trace_id"]


# ---------------------------------------------------------------------------
# Part 1: Storage-level CRUD
# ---------------------------------------------------------------------------


class TestFeedbackStorage:
    def _save_trace(self, store, trace_id: str | None = None) -> str:
        tid = trace_id or uuid.uuid4().hex
        store.save_trace(
            {
                "trace_id": tid,
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
                "spans": [],
            }
        )
        return tid

    def test_save_and_get_feedback(self, store):
        tid = self._save_trace(store)
        fid = store.save_feedback(tid, rating=4, comment="Good", metadata={"source": "test"})
        assert isinstance(fid, int) and fid > 0

        feedbacks = store.get_feedback(tid)
        assert len(feedbacks) == 1
        fb = feedbacks[0]
        assert fb["trace_id"] == tid
        assert fb["rating"] == 4
        assert fb["comment"] == "Good"
        assert fb["metadata"] == {"source": "test"}

    def test_multiple_feedbacks_for_trace(self, store):
        tid = self._save_trace(store)
        store.save_feedback(tid, rating=5)
        store.save_feedback(tid, rating=3, comment="average")
        feedbacks = store.get_feedback(tid)
        assert len(feedbacks) == 2

    def test_get_feedback_empty(self, store):
        assert store.get_feedback("nonexistent-trace-id") == []

    def test_feedback_without_comment_or_metadata(self, store):
        tid = self._save_trace(store)
        store.save_feedback(tid, rating=5)
        feedbacks = store.get_feedback(tid)
        assert len(feedbacks) == 1
        assert feedbacks[0]["comment"] is None
        assert feedbacks[0]["metadata"] == {}

    def test_rating_validation_low(self, store):
        tid = self._save_trace(store)
        with pytest.raises(ValueError, match="rating must be between 1 and 5"):
            store.save_feedback(tid, rating=0)

    def test_rating_validation_high(self, store):
        tid = self._save_trace(store)
        with pytest.raises(ValueError, match="rating must be between 1 and 5"):
            store.save_feedback(tid, rating=6)

    def test_rating_boundary_1(self, store):
        tid = self._save_trace(store)
        store.save_feedback(tid, rating=1)
        assert store.get_feedback(tid)[0]["rating"] == 1

    def test_rating_boundary_5(self, store):
        tid = self._save_trace(store)
        store.save_feedback(tid, rating=5)
        assert store.get_feedback(tid)[0]["rating"] == 5

    def test_feedback_summary_empty(self, store):
        summary = store.get_feedback_summary()
        assert summary["total_count"] == 0
        assert summary["avg_rating"] is None
        assert summary["rating_distribution"] == {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0}
        assert summary["low_rating_traces"] == []

    def test_feedback_summary_with_data(self, store):
        t1 = self._save_trace(store)
        t2 = self._save_trace(store)
        store.save_feedback(t1, rating=5)
        store.save_feedback(t1, rating=4)
        store.save_feedback(t2, rating=1)
        store.save_feedback(t2, rating=2)

        summary = store.get_feedback_summary()
        assert summary["total_count"] == 4
        assert summary["avg_rating"] is not None
        assert summary["rating_distribution"]["5"] == 1
        assert summary["rating_distribution"]["4"] == 1
        assert summary["rating_distribution"]["1"] == 1
        assert summary["rating_distribution"]["2"] == 1
        assert summary["rating_distribution"]["3"] == 0

    def test_feedback_summary_low_rating_traces(self, store):
        t1 = self._save_trace(store)
        t2 = self._save_trace(store)
        # t1 has low avg (1+2)/2 = 1.5
        store.save_feedback(t1, rating=1)
        store.save_feedback(t1, rating=2)
        # t2 has high avg (4+5)/2 = 4.5
        store.save_feedback(t2, rating=4)
        store.save_feedback(t2, rating=5)

        summary = store.get_feedback_summary()
        low_ids = [r["trace_id"] for r in summary["low_rating_traces"]]
        assert t1 in low_ids
        assert t2 not in low_ids

    def test_get_recent_feedback_returns_newest_first(self, store):
        """get_recent_feedback returns entries newest first."""
        t1 = self._save_trace(store)
        t2 = self._save_trace(store)
        store.save_feedback(t1, rating=5, comment="first")
        store.save_feedback(t2, rating=2, comment="second")

        recent = store.get_recent_feedback(limit=10)
        assert len(recent) == 2
        assert recent[0]["comment"] == "second"
        assert recent[1]["comment"] == "first"

    def test_get_recent_feedback_limit_respected(self, store):
        """get_recent_feedback limit parameter is respected."""
        t = self._save_trace(store)
        for _ in range(5):
            store.save_feedback(t, rating=3)
        recent = store.get_recent_feedback(limit=3)
        assert len(recent) == 3

    def test_get_recent_feedback_empty(self, store):
        """get_recent_feedback returns empty list when no feedback."""
        assert store.get_recent_feedback() == []


# ---------------------------------------------------------------------------
# Part 2: API endpoints
# ---------------------------------------------------------------------------


class TestFeedbackAPI:
    def test_submit_feedback(self, client):
        tid = _ingest_trace(client)
        resp = client.post(
            f"/v1/traces/{tid}/feedback",
            json={"rating": 5, "comment": "Excellent!"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["status"] == "ok"
        assert body["trace_id"] == tid
        assert "feedback_id" in body

    def test_submit_feedback_minimal(self, client):
        tid = _ingest_trace(client)
        resp = client.post(f"/v1/traces/{tid}/feedback", json={"rating": 3})
        assert resp.status_code == 201

    def test_submit_feedback_with_metadata(self, client):
        tid = _ingest_trace(client)
        resp = client.post(
            f"/v1/traces/{tid}/feedback",
            json={"rating": 4, "metadata": {"source": "manual", "reviewer": "qa"}},
        )
        assert resp.status_code == 201

    def test_get_feedback_for_trace(self, client):
        tid = _ingest_trace(client)
        client.post(f"/v1/traces/{tid}/feedback", json={"rating": 4, "comment": "Good"})
        client.post(f"/v1/traces/{tid}/feedback", json={"rating": 2, "comment": "Bad"})

        resp = client.get(f"/v1/traces/{tid}/feedback")
        assert resp.status_code == 200
        feedbacks = resp.json()
        assert isinstance(feedbacks, list)
        assert len(feedbacks) == 2

    def test_get_feedback_empty(self, client):
        tid = _ingest_trace(client)
        resp = client.get(f"/v1/traces/{tid}/feedback")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_rating_validation_too_low(self, client):
        tid = _ingest_trace(client)
        resp = client.post(f"/v1/traces/{tid}/feedback", json={"rating": 0})
        assert resp.status_code == 422  # Pydantic validation error

    def test_rating_validation_too_high(self, client):
        tid = _ingest_trace(client)
        resp = client.post(f"/v1/traces/{tid}/feedback", json={"rating": 6})
        assert resp.status_code == 422  # Pydantic validation error

    def test_rating_boundary_1(self, client):
        tid = _ingest_trace(client)
        resp = client.post(f"/v1/traces/{tid}/feedback", json={"rating": 1})
        assert resp.status_code == 201

    def test_rating_boundary_5(self, client):
        tid = _ingest_trace(client)
        resp = client.post(f"/v1/traces/{tid}/feedback", json={"rating": 5})
        assert resp.status_code == 201

    def test_feedback_summary_endpoint(self, client):
        t1 = _ingest_trace(client)
        t2 = _ingest_trace(client)
        client.post(f"/v1/traces/{t1}/feedback", json={"rating": 5})
        client.post(f"/v1/traces/{t2}/feedback", json={"rating": 1})

        resp = client.get("/v1/feedback/summary")
        assert resp.status_code == 200
        summary = resp.json()
        assert summary["total_count"] == 2
        assert summary["avg_rating"] is not None
        assert "rating_distribution" in summary
        assert "low_rating_traces" in summary

    def test_feedback_summary_distribution(self, client):
        tid = _ingest_trace(client)
        for rating in [1, 2, 3, 4, 5]:
            client.post(f"/v1/traces/{tid}/feedback", json={"rating": rating})

        resp = client.get("/v1/feedback/summary")
        assert resp.status_code == 200
        dist = resp.json()["rating_distribution"]
        for r in ["1", "2", "3", "4", "5"]:
            assert dist[r] == 1

    def test_feedback_summary_low_rating_traces(self, client):
        good_trace = _ingest_trace(client)
        bad_trace = _ingest_trace(client)

        client.post(f"/v1/traces/{good_trace}/feedback", json={"rating": 5})
        client.post(f"/v1/traces/{bad_trace}/feedback", json={"rating": 1})
        client.post(f"/v1/traces/{bad_trace}/feedback", json={"rating": 2})

        resp = client.get("/v1/feedback/summary")
        summary = resp.json()
        low_ids = [r["trace_id"] for r in summary["low_rating_traces"]]
        assert bad_trace in low_ids
        assert good_trace not in low_ids

    def test_feedback_recent_endpoint_empty(self, client):
        resp = client.get("/v1/feedback/recent")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_feedback_recent_endpoint_returns_entries(self, client):
        t1 = _ingest_trace(client)
        t2 = _ingest_trace(client)
        client.post(f"/v1/traces/{t1}/feedback", json={"rating": 4, "comment": "good trace"})
        client.post(f"/v1/traces/{t2}/feedback", json={"rating": 2, "comment": "needs work"})

        resp = client.get("/v1/feedback/recent")
        assert resp.status_code == 200
        entries = resp.json()
        assert isinstance(entries, list)
        assert len(entries) == 2
        # Newest first
        assert entries[0]["comment"] == "needs work"
        assert entries[1]["comment"] == "good trace"

    def test_feedback_recent_endpoint_limit(self, client):
        """Limit parameter restricts result count."""
        t = _ingest_trace(client)
        for _i in range(5):
            client.post(f"/v1/traces/{t}/feedback", json={"rating": 3})

        resp = client.get("/v1/feedback/recent?limit=2")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_feedback_recent_endpoint_limit_max(self, client):
        """Limit above 100 is rejected."""
        resp = client.get("/v1/feedback/recent?limit=101")
        assert resp.status_code == 422  # Pydantic / FastAPI validation error

    def test_feedback_recent_fields_present(self, client):
        """Each entry has required fields."""
        tid = _ingest_trace(client)
        client.post(f"/v1/traces/{tid}/feedback", json={"rating": 5, "comment": "great"})

        resp = client.get("/v1/feedback/recent")
        assert resp.status_code == 200
        entry = resp.json()[0]
        assert "id" in entry
        assert "trace_id" in entry
        assert entry["trace_id"] == tid
        assert "rating" in entry
        assert entry["rating"] == 5
        assert "comment" in entry
        assert entry["comment"] == "great"
        assert "created_at" in entry
