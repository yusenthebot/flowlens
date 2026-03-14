"""
Tests for new features added in Cycle 4:
- flowlens.exceptions hierarchy
- POST /v1/traces/batch-delete endpoint
- API key authentication middleware
- storage.batch_delete_traces method
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from flowlens.exceptions import (
    ExportError,
    FlowLensError,
    RateLimitError,
    StorageError,
    ValidationError,
)
from flowlens.server.app import create_app
from flowlens.server.storage import TraceStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_trace(trace_id: str = "t1", service_name: str = "test-svc") -> dict:
    return {
        "trace_id": trace_id,
        "service_name": service_name,
        "start_time": 1000.0,
        "end_time": 1001.0,
        "duration_ms": 1000.0,
        "span_count": 0,
        "total_tokens": 0,
        "total_cost_usd": 0.0,
        "has_errors": False,
        "error_count": 0,
        "metadata": {},
        "spans": [],
    }


# ---------------------------------------------------------------------------
# 1. Exception hierarchy
# ---------------------------------------------------------------------------

class TestExceptionHierarchy:
    def test_base_is_exception(self):
        assert issubclass(FlowLensError, Exception)

    def test_storage_error_is_flowlens_error(self):
        assert issubclass(StorageError, FlowLensError)

    def test_export_error_is_flowlens_error(self):
        assert issubclass(ExportError, FlowLensError)

    def test_validation_error_is_flowlens_error(self):
        assert issubclass(ValidationError, FlowLensError)

    def test_rate_limit_error_is_flowlens_error(self):
        assert issubclass(RateLimitError, FlowLensError)

    def test_catch_all_with_base_class(self):
        for exc_cls in (StorageError, ExportError, ValidationError, RateLimitError):
            with pytest.raises(FlowLensError):
                raise exc_cls("test message")

    def test_storage_error_message(self):
        err = StorageError("disk full")
        assert str(err) == "disk full"

    def test_individual_catches(self):
        with pytest.raises(StorageError):
            raise StorageError("storage problem")
        with pytest.raises(ExportError):
            raise ExportError("export problem")
        with pytest.raises(ValidationError):
            raise ValidationError("validation problem")
        with pytest.raises(RateLimitError):
            raise RateLimitError("rate limit exceeded")

    def test_child_not_caught_by_sibling(self):
        """StorageError must not be caught by ExportError handler."""
        with pytest.raises(StorageError):
            try:
                raise StorageError("storage problem")
            except ExportError:
                pass  # should NOT be caught here


# ---------------------------------------------------------------------------
# 2. Storage — batch_delete_traces
# ---------------------------------------------------------------------------

class TestBatchDeleteStorage:
    @pytest.fixture
    def store(self, tmp_path):
        s = TraceStore(db_path=tmp_path / "batch_test.db")
        yield s
        s.close()

    def test_batch_delete_all_exist(self, store):
        for i in range(5):
            store.save_trace(_make_trace(f"t{i}"))
        deleted = store.batch_delete_traces(["t0", "t1", "t2"])
        assert deleted == 3
        assert store.get_trace("t0") is None
        assert store.get_trace("t3") is not None

    def test_batch_delete_some_missing(self, store):
        store.save_trace(_make_trace("exists"))
        deleted = store.batch_delete_traces(["exists", "ghost"])
        assert deleted == 1
        assert store.get_trace("exists") is None

    def test_batch_delete_empty_list(self, store):
        store.save_trace(_make_trace("t1"))
        deleted = store.batch_delete_traces([])
        assert deleted == 0
        assert store.get_trace("t1") is not None

    def test_batch_delete_all_missing(self, store):
        deleted = store.batch_delete_traces(["no-such-1", "no-such-2"])
        assert deleted == 0

    def test_batch_delete_cascades_spans(self, store):
        """Deleting via batch-delete must also remove child spans."""
        trace = _make_trace("casc")
        trace["spans"] = [{
            "span_id": "casc_s1",
            "trace_id": "casc",
            "name": "test",
            "kind": "tool",
            "status": "ok",
            "start_time": 1000.0,
            "end_time": 1001.0,
            "attributes": {},
            "events": [],
        }]
        store.save_trace(trace)
        store.batch_delete_traces(["casc"])
        rows = store._conn.execute(
            "SELECT count(*) FROM spans WHERE trace_id = 'casc'"
        ).fetchone()
        assert rows[0] == 0

    def test_batch_delete_large_list(self, store):
        """Ensure chunked deletion works for lists exceeding SQLite variable limit."""
        ids = [f"bulk-{i}" for i in range(1000)]
        for tid in ids:
            store.save_trace(_make_trace(tid))
        deleted = store.batch_delete_traces(ids)
        assert deleted == 1000


# ---------------------------------------------------------------------------
# 3. API — POST /v1/traces/batch-delete
# ---------------------------------------------------------------------------

class TestBatchDeleteEndpoint:
    @pytest.fixture
    def client(self, tmp_path):
        app = create_app(db_path=str(tmp_path / "batch_api_test.db"))
        return TestClient(app)

    def _ingest(self, client, trace_id: str) -> None:
        r = client.post("/v1/traces/ingest", json=_make_trace(trace_id))
        assert r.status_code == 201

    def test_batch_delete_basic(self, client):
        self._ingest(client, "bd-1")
        self._ingest(client, "bd-2")
        self._ingest(client, "bd-3")

        r = client.post(
            "/v1/traces/batch-delete",
            json={"trace_ids": ["bd-1", "bd-2"]},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["deleted"] == 2
        assert data["requested"] == 2

        # Confirm deletions
        assert client.get("/v1/traces/bd-1").status_code == 404
        assert client.get("/v1/traces/bd-2").status_code == 404
        assert client.get("/v1/traces/bd-3").status_code == 200

    def test_batch_delete_some_missing(self, client):
        self._ingest(client, "bd-exists")
        r = client.post(
            "/v1/traces/batch-delete",
            json={"trace_ids": ["bd-exists", "bd-ghost"]},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["deleted"] == 1
        assert data["requested"] == 2

    def test_batch_delete_all_missing(self, client):
        r = client.post(
            "/v1/traces/batch-delete",
            json={"trace_ids": ["no-such-1", "no-such-2"]},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["deleted"] == 0

    def test_batch_delete_empty_list_rejected(self, client):
        """An empty trace_ids list should fail Pydantic min_length validation."""
        r = client.post("/v1/traces/batch-delete", json={"trace_ids": []})
        assert r.status_code == 422

    def test_batch_delete_missing_body_rejected(self, client):
        r = client.post("/v1/traces/batch-delete", json={})
        assert r.status_code == 422

    def test_batch_delete_invalid_trace_id_rejected(self, client):
        """trace_ids with path-traversal sequences must be rejected (400)."""
        r = client.post(
            "/v1/traces/batch-delete",
            json={"trace_ids": ["../../etc/passwd"]},
        )
        assert r.status_code == 400

    def test_batch_delete_over_100_ids_rejected(self, client):
        """More than 100 trace IDs in a single request must be rejected (422)."""
        r = client.post(
            "/v1/traces/batch-delete",
            json={"trace_ids": [f"id-{i}" for i in range(101)]},
        )
        assert r.status_code == 422

    def test_batch_delete_exactly_100_ids_accepted(self, client):
        """Exactly 100 trace IDs must be accepted (200 response)."""
        r = client.post(
            "/v1/traces/batch-delete",
            json={"trace_ids": [f"id-{i}" for i in range(100)]},
        )
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# 4. API key authentication middleware
# ---------------------------------------------------------------------------

class TestApiKeyAuth:
    def _make_client_with_key(self, tmp_path, api_key: str) -> TestClient:
        """Create a TestClient with FLOWLENS_API_KEY set in the environment."""
        old = os.environ.get("FLOWLENS_API_KEY")
        os.environ["FLOWLENS_API_KEY"] = api_key
        try:
            app = create_app(db_path=str(tmp_path / "auth_test.db"))
        finally:
            if old is None:
                os.environ.pop("FLOWLENS_API_KEY", None)
            else:
                os.environ["FLOWLENS_API_KEY"] = old
        return TestClient(app)

    def test_no_api_key_env_allows_all(self, tmp_path):
        """When FLOWLENS_API_KEY is not set, all requests are allowed."""
        os.environ.pop("FLOWLENS_API_KEY", None)
        app = create_app(db_path=str(tmp_path / "noauth_test.db"))
        client = TestClient(app)
        r = client.get("/health")
        assert r.status_code == 200

    def test_valid_api_key_header_allowed(self, tmp_path):
        client = self._make_client_with_key(tmp_path, "secret-key-123")
        r = client.get("/health", headers={"X-API-Key": "secret-key-123"})
        assert r.status_code == 200

    def test_missing_api_key_header_rejected(self, tmp_path):
        client = self._make_client_with_key(tmp_path, "secret-key-123")
        r = client.get("/health")
        assert r.status_code == 401

    def test_wrong_api_key_header_rejected(self, tmp_path):
        client = self._make_client_with_key(tmp_path, "secret-key-123")
        r = client.get("/health", headers={"X-API-Key": "wrong-key"})
        assert r.status_code == 401

    def test_root_path_exempt_from_auth(self, tmp_path):
        """The dashboard at / must be accessible without an API key."""
        client = self._make_client_with_key(tmp_path, "secret-key-123")
        r = client.get("/")
        # Dashboard serves HTML; either 200 (HTML served) or 500 (file missing)
        # but NOT 401
        assert r.status_code != 401

    def test_dashboard_alias_exempt_from_auth(self, tmp_path):
        """/dashboard must be accessible without an API key."""
        client = self._make_client_with_key(tmp_path, "secret-key-123")
        r = client.get("/dashboard")
        assert r.status_code != 401

    def test_api_endpoints_require_key_when_set(self, tmp_path):
        """Protected endpoints must return 401 without the correct API key."""
        client = self._make_client_with_key(tmp_path, "mykey")
        for path in ["/health", "/v1/stats", "/v1/traces"]:
            r = client.get(path)
            assert r.status_code == 401, f"Expected 401 for {path}, got {r.status_code}"

    def test_unauthorized_response_has_detail(self, tmp_path):
        """401 responses must include a detail field."""
        client = self._make_client_with_key(tmp_path, "mykey")
        r = client.get("/health")
        assert r.status_code == 401
        assert "detail" in r.json()

    def test_api_key_with_ingest_endpoint(self, tmp_path):
        """Ingest endpoint also requires the API key."""
        client = self._make_client_with_key(tmp_path, "mykey")
        r = client.post("/v1/traces/ingest", json=_make_trace("auth-t1"))
        assert r.status_code == 401

        # With key it should work
        r = client.post(
            "/v1/traces/ingest",
            json=_make_trace("auth-t2"),
            headers={"X-API-Key": "mykey"},
        )
        assert r.status_code == 201
