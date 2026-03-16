"""
Tests for the Evaluation Engine — storage, API routes, and CLI gate.
"""

from __future__ import annotations

import time
import uuid

import pytest
from click.testing import CliRunner
from fastapi.testclient import TestClient

from flowlens.cli import cli
from flowlens.server.app import create_app
from flowlens.server.storage import TraceStore

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_DUMMY_TRACE = {
    "trace_id": "",  # filled per test
    "service_name": "test-svc",
    "start_time": time.time(),
    "end_time": time.time() + 2,
    "duration_ms": 2000.0,
    "total_tokens": 5000,
    "total_cost_usd": 0.05,
    "has_errors": False,
    "error_count": 0,
    "span_count": 3,
    "metadata": {},
    "spans": [],
}


def _make_trace(**overrides):
    t = dict(_DUMMY_TRACE)
    t["trace_id"] = uuid.uuid4().hex
    t.update(overrides)
    return t


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


def _ingest(client, **overrides) -> str:
    payload = _make_trace(**overrides)
    r = client.post("/v1/traces/ingest", json=payload)
    assert r.status_code == 201, r.text
    return payload["trace_id"]


# ====================================================================# Storage-level tests
# ====================================================================


class TestEvaluationStorage:
    def _save_trace(self, store, **overrides) -> str:
        t = _make_trace(**overrides)
        store.save_trace(t)
        return t["trace_id"]

    def test_save_and_retrieve_evaluation(self, store):
        tid = self._save_trace(store)
        eval_data = {
            "eval_id": uuid.uuid4().hex,
            "trace_id": tid,
            "evaluator_name": "cost_threshold",
            "score": 0.9,
            "label": "pass",
            "reason": "cost ok",
            "metadata": {"config": {"max_cost_usd": 0.10}},
        }
        returned_id = store.save_evaluation(eval_data)
        assert returned_id == eval_data["eval_id"]

        evals = store.get_evaluations_for_trace(tid)
        assert len(evals) == 1
        e = evals[0]
        assert e["score"] == 0.9
        assert e["label"] == "pass"
        assert e["reason"] == "cost ok"
        assert isinstance(e["metadata"], dict)

    def test_list_evaluations_no_filter(self, store):
        t1 = self._save_trace(store)
        t2 = self._save_trace(store)
        for tid, ev_name in [(t1, "cost_threshold"), (t2, "no_errors")]:
            store.save_evaluation(
                {
                    "eval_id": uuid.uuid4().hex,
                    "trace_id": tid,
                    "evaluator_name": ev_name,
                    "score": 1.0,
                    "label": "pass",
                }
            )
        results = store.list_evaluations(limit=10)
        assert len(results) == 2

    def test_list_evaluations_filter_by_evaluator(self, store):
        tid = self._save_trace(store)
        for name in ["cost_threshold", "no_errors", "cost_threshold"]:
            store.save_evaluation(
                {
                    "eval_id": uuid.uuid4().hex,
                    "trace_id": tid,
                    "evaluator_name": name,
                    "score": 1.0,
                    "label": "pass",
                }
            )
        results = store.list_evaluations(evaluator_name="cost_threshold")
        assert all(r["evaluator_name"] == "cost_threshold" for r in results)
        assert len(results) == 2

    def test_evaluations_empty_for_unknown_trace(self, store):
        assert store.get_evaluations_for_trace("nonexistent") == []


class TestDatasetStorage:
    def _save_trace(self, store, **overrides) -> str:
        t = _make_trace(**overrides)
        store.save_trace(t)
        return t["trace_id"]

    def test_create_and_get_dataset(self, store):
        ds_id = store.create_dataset("golden-v1", "Golden test set")
        assert isinstance(ds_id, str)

        ds = store.get_dataset(ds_id)
        assert ds is not None
        assert ds["name"] == "golden-v1"
        assert ds["description"] == "Golden test set"
        assert ds["item_count"] == 0

    def test_duplicate_name_raises(self, store):
        store.create_dataset("dup-set")
        with pytest.raises(ValueError, match="already exists"):
            store.create_dataset("dup-set")

    def test_add_traces_to_dataset(self, store):
        t1 = self._save_trace(store)
        t2 = self._save_trace(store)
        ds_id = store.create_dataset("my-ds")
        store.add_to_dataset(ds_id, [t1, t2])

        ds = store.get_dataset(ds_id)
        assert ds["item_count"] == 2

    def test_add_duplicate_traces_idempotent(self, store):
        tid = self._save_trace(store)
        ds_id = store.create_dataset("idem-ds")
        store.add_to_dataset(ds_id, [tid])
        store.add_to_dataset(ds_id, [tid])  # second call should not raise or duplicate
        ds = store.get_dataset(ds_id)
        assert ds["item_count"] == 1

    def test_list_datasets(self, store):
        store.create_dataset("ds-a")
        store.create_dataset("ds-b")
        datasets = store.list_datasets()
        names = [d["name"] for d in datasets]
        assert "ds-a" in names
        assert "ds-b" in names

    def test_get_dataset_traces(self, store):
        t1 = self._save_trace(store)
        t2 = self._save_trace(store)
        ds_id = store.create_dataset("trace-ds")
        store.add_to_dataset(ds_id, [t1, t2])

        traces = store.get_dataset_traces(ds_id)
        assert len(traces) == 2
        trace_ids = {t["trace_id"] for t in traces}
        assert t1 in trace_ids
        assert t2 in trace_ids

    def test_get_nonexistent_dataset_returns_none(self, store):
        assert store.get_dataset("nonexistent") is None


# ====================================================================# API route tests
# ====================================================================


class TestEvaluationRunEndpoint:
    def test_run_cost_threshold_pass(self, client):
        tid = _ingest(client, total_cost_usd=0.02)
        r = client.post(
            "/v1/evaluations/run",
            json={
                "evaluator": "cost_threshold",
                "config": {"max_cost_usd": 0.10},
                "trace_ids": [tid],
            },
        )
        assert r.status_code == 201
        body = r.json()
        results = body["results"]
        assert len(results) == 1
        assert results[0]["label"] == "pass"
        assert results[0]["score"] == 1.0

    def test_run_cost_threshold_fail(self, client):
        tid = _ingest(client, total_cost_usd=0.50)
        r = client.post(
            "/v1/evaluations/run",
            json={
                "evaluator": "cost_threshold",
                "config": {"max_cost_usd": 0.10},
                "trace_ids": [tid],
            },
        )
        assert r.status_code == 201
        result = r.json()["results"][0]
        assert result["label"] == "fail"
        assert result["score"] < 1.0

    def test_run_no_errors_pass(self, client):
        tid = _ingest(client, has_errors=False, error_count=0)
        r = client.post(
            "/v1/evaluations/run",
            json={"evaluator": "no_errors", "config": {}, "trace_ids": [tid]},
        )
        assert r.status_code == 201
        assert r.json()["results"][0]["label"] == "pass"

    def test_run_no_errors_fail(self, client):
        tid = _ingest(client, has_errors=True, error_count=2)
        r = client.post(
            "/v1/evaluations/run",
            json={"evaluator": "no_errors", "config": {}, "trace_ids": [tid]},
        )
        assert r.status_code == 201
        assert r.json()["results"][0]["label"] == "fail"
        assert r.json()["results"][0]["score"] == 0.0

    def test_run_unknown_evaluator_returns_400(self, client):
        tid = _ingest(client)
        r = client.post(
            "/v1/evaluations/run",
            json={"evaluator": "does_not_exist", "config": {}, "trace_ids": [tid]},
        )
        assert r.status_code == 400

    def test_run_missing_trace_returns_error_label(self, client):
        r = client.post(
            "/v1/evaluations/run",
            json={
                "evaluator": "no_errors",
                "config": {},
                "trace_ids": ["phantom-trace-id"],
            },
        )
        assert r.status_code == 201
        result = r.json()["results"][0]
        assert result["label"] == "error"
        assert result["score"] is None

    def test_run_multiple_traces(self, client):
        t1 = _ingest(client, total_cost_usd=0.01)
        t2 = _ingest(client, total_cost_usd=0.20)
        r = client.post(
            "/v1/evaluations/run",
            json={
                "evaluator": "cost_threshold",
                "config": {"max_cost_usd": 0.10},
                "trace_ids": [t1, t2],
            },
        )
        assert r.status_code == 201
        results = r.json()["results"]
        assert len(results) == 2
        labels = {result["trace_id"]: result["label"] for result in results}
        assert labels[t1] == "pass"
        assert labels[t2] == "fail"

    def test_results_persisted(self, client):
        tid = _ingest(client)
        client.post(
            "/v1/evaluations/run",
            json={"evaluator": "no_errors", "config": {}, "trace_ids": [tid]},
        )
        r = client.get(f"/v1/traces/{tid}/evaluations")
        assert r.status_code == 200
        assert len(r.json()) >= 1


class TestEvaluationResultsEndpoint:
    def test_list_all_results(self, client):
        for _ in range(3):
            tid = _ingest(client)
            client.post(
                "/v1/evaluations/run",
                json={"evaluator": "no_errors", "config": {}, "trace_ids": [tid]},
            )
        r = client.get("/v1/evaluations/results")
        assert r.status_code == 200
        assert len(r.json()) >= 3

    def test_list_filtered_by_evaluator(self, client):
        tid1 = _ingest(client)
        tid2 = _ingest(client)
        client.post(
            "/v1/evaluations/run",
            json={"evaluator": "no_errors", "config": {}, "trace_ids": [tid1]},
        )
        client.post(
            "/v1/evaluations/run",
            json={
                "evaluator": "cost_threshold",
                "config": {"max_cost_usd": 0.10},
                "trace_ids": [tid2],
            },
        )
        r = client.get("/v1/evaluations/results?evaluator=no_errors")
        assert r.status_code == 200
        body = r.json()
        assert all(e["evaluator_name"] == "no_errors" for e in body)

    def test_limit_respected(self, client):
        for _ in range(5):
            tid = _ingest(client)
            client.post(
                "/v1/evaluations/run",
                json={"evaluator": "no_errors", "config": {}, "trace_ids": [tid]},
            )
        r = client.get("/v1/evaluations/results?limit=3")
        assert r.status_code == 200
        assert len(r.json()) <= 3


class TestTraceEvaluationsEndpoint:
    def test_returns_empty_list_for_no_evals(self, client):
        tid = _ingest(client)
        r = client.get(f"/v1/traces/{tid}/evaluations")
        assert r.status_code == 200
        assert r.json() == []

    def test_returns_evaluations_for_trace(self, client):
        tid = _ingest(client)
        client.post(
            "/v1/evaluations/run",
            json={"evaluator": "no_errors", "config": {}, "trace_ids": [tid]},
        )
        r = client.get(f"/v1/traces/{tid}/evaluations")
        assert r.status_code == 200
        evals = r.json()
        assert len(evals) == 1
        assert evals[0]["trace_id"] == tid


class TestDatasetEndpoints:
    def test_create_dataset(self, client):
        r = client.post(
            "/v1/datasets",
            json={"name": "golden-v1", "description": "Golden set"},
        )
        assert r.status_code == 201
        body = r.json()
        assert body["name"] == "golden-v1"
        assert "dataset_id" in body

    def test_create_dataset_conflict(self, client):
        client.post("/v1/datasets", json={"name": "dup"})
        r = client.post("/v1/datasets", json={"name": "dup"})
        assert r.status_code == 409

    def test_create_dataset_with_traces(self, client):
        t1 = _ingest(client)
        t2 = _ingest(client)
        r = client.post(
            "/v1/datasets",
            json={"name": "with-traces", "trace_ids": [t1, t2]},
        )
        assert r.status_code == 201
        assert r.json()["item_count"] == 2

    def test_list_datasets(self, client):
        client.post("/v1/datasets", json={"name": "ds-list-1"})
        client.post("/v1/datasets", json={"name": "ds-list-2"})
        r = client.get("/v1/datasets")
        assert r.status_code == 200
        names = [d["name"] for d in r.json()]
        assert "ds-list-1" in names
        assert "ds-list-2" in names

    def test_get_dataset_with_traces(self, client):
        tid = _ingest(client)
        cr = client.post(
            "/v1/datasets",
            json={"name": "get-with-traces", "trace_ids": [tid]},
        )
        ds_id = cr.json()["dataset_id"]
        r = client.get(f"/v1/datasets/{ds_id}")
        assert r.status_code == 200
        body = r.json()
        assert body["dataset_id"] == ds_id
        assert len(body["traces"]) == 1
        assert body["traces"][0]["trace_id"] == tid

    def test_get_nonexistent_dataset_404(self, client):
        r = client.get("/v1/datasets/nonexistent-id")
        assert r.status_code == 404

    def test_evaluate_dataset(self, client):
        t1 = _ingest(client, total_cost_usd=0.01)
        t2 = _ingest(client, total_cost_usd=0.50)
        cr = client.post(
            "/v1/datasets",
            json={"name": "eval-ds", "trace_ids": [t1, t2]},
        )
        ds_id = cr.json()["dataset_id"]

        r = client.post(
            f"/v1/datasets/{ds_id}/evaluate",
            json={"evaluators": [{"name": "cost_threshold", "config": {"max_cost_usd": 0.10}}]},
        )
        assert r.status_code == 201
        body = r.json()
        assert body["dataset_id"] == ds_id
        assert len(body["results"]) == 2
        assert "cost_threshold" in body["summary"]
        summary = body["summary"]["cost_threshold"]
        assert summary["trace_count"] == 2
        assert summary["pass_count"] == 1
        assert summary["fail_count"] == 1

    def test_evaluate_nonexistent_dataset_404(self, client):
        r = client.post(
            "/v1/datasets/nonexistent/evaluate",
            json={"evaluators": [{"name": "no_errors", "config": {}}]},
        )
        assert r.status_code == 404


class TestListEvaluatorsEndpoint:
    def test_returns_list(self, client):
        r = client.get("/v1/evaluators")
        assert r.status_code == 200
        evaluators = r.json()
        assert isinstance(evaluators, list)
        assert "cost_threshold" in evaluators
        assert "no_errors" in evaluators
        assert "latency_threshold" in evaluators
        assert "token_budget" in evaluators


# ====================================================================# CLI tests
# ====================================================================


class TestEvalCLI:
    def _populate_db(self, db_path: str) -> str:
        """Seed one trace and return its trace_id."""
        store = TraceStore(db_path=db_path)
        t = _make_trace(total_cost_usd=0.03)
        store.save_trace(t)
        store.close()
        return t["trace_id"]

    def test_eval_run_pass(self, tmp_path):
        db = str(tmp_path / "test.db")
        tid = self._populate_db(db)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "eval",
                "run",
                "--evaluator",
                "cost_threshold",
                "--trace-id",
                tid,
                "--config",
                '{"max_cost_usd": 0.10}',
                "--db",
                db,
            ],
        )
        assert result.exit_code == 0, result.output
        assert "pass" in result.output

    def test_eval_run_missing_trace_exits_1(self, tmp_path):
        db = str(tmp_path / "test.db")
        # Initialise DB without any traces
        store = TraceStore(db_path=db)
        store.close()
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["eval", "run", "--evaluator", "no_errors", "--trace-id", "fake", "--db", db],
        )
        assert result.exit_code == 1

    def test_eval_run_unknown_evaluator_exits_1(self, tmp_path):
        db = str(tmp_path / "test.db")
        tid = self._populate_db(db)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "eval",
                "run",
                "--evaluator",
                "nonexistent_evaluator",
                "--trace-id",
                tid,
                "--db",
                db,
            ],
        )
        assert result.exit_code == 1

    def test_eval_gate_pass(self, tmp_path):
        db = str(tmp_path / "test.db")
        store = TraceStore(db_path=db)
        # Create dataset with low-cost traces
        t1 = _make_trace(total_cost_usd=0.01)
        t2 = _make_trace(total_cost_usd=0.02)
        store.save_trace(t1)
        store.save_trace(t2)
        ds_id = store.create_dataset("gate-pass-ds")
        store.add_to_dataset(ds_id, [t1["trace_id"], t2["trace_id"]])
        store.close()

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "eval",
                "gate",
                "--dataset",
                "gate-pass-ds",
                "--min-score",
                "0.8",
                "--evaluator",
                "cost_threshold",
                "--config",
                '{"max_cost_usd": 0.10}',
                "--db",
                db,
            ],
        )
        assert result.exit_code == 0, result.output
        assert "GATE PASSED" in result.output

    def test_eval_gate_fail(self, tmp_path):
        db = str(tmp_path / "test.db")
        store = TraceStore(db_path=db)
        # Create dataset with expensive traces that will fail
        t1 = _make_trace(total_cost_usd=0.50)
        t2 = _make_trace(total_cost_usd=0.80)
        store.save_trace(t1)
        store.save_trace(t2)
        ds_id = store.create_dataset("gate-fail-ds")
        store.add_to_dataset(ds_id, [t1["trace_id"], t2["trace_id"]])
        store.close()

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "eval",
                "gate",
                "--dataset",
                "gate-fail-ds",
                "--min-score",
                "0.9",
                "--evaluator",
                "cost_threshold",
                "--config",
                '{"max_cost_usd": 0.10}',
                "--db",
                db,
            ],
        )
        assert result.exit_code == 1
        assert "GATE FAILED" in result.output

    def test_eval_gate_missing_dataset_exits_1(self, tmp_path):
        db = str(tmp_path / "test.db")
        store = TraceStore(db_path=db)
        store.close()
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "eval",
                "gate",
                "--dataset",
                "nonexistent",
                "--min-score",
                "0.8",
                "--db",
                db,
            ],
        )
        assert result.exit_code == 1
