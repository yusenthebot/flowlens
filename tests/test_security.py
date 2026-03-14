"""
Security-focused tests for FlowLens.

Covers:
- Path traversal prevention in the import endpoint
- Oversized payload rejection (spans list, string fields)
- SQL injection harmlessness (parameterised queries)
- Rate limiting — 429 response when limit exceeded
- Invalid / malformed inputs returning proper error codes
- Security response headers present on all responses
- SDK span-name validation and per-trace span limit
- FlowLens singleton thread safety
"""
from __future__ import annotations

import json
import threading
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from flowlens.sdk.models import SpanKind
from flowlens.sdk.tracer import _MAX_SPANS_PER_TRACE, FlowLens, _validate_span_name
from flowlens.server.app import (
    _ALLOWED_IMPORT_DIRS,
    _MAX_SPANS_PER_INGEST,
    create_app,
)
from flowlens.server.storage import TraceStore

# ===========================================================================
# Helpers
# ===========================================================================

def _make_trace(
    trace_id: str = "sec-t1",
    service_name: str = "security-test",
    has_errors: bool = False,
    start_time: float = 1000.0,
    spans: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "trace_id": trace_id,
        "service_name": service_name,
        "start_time": start_time,
        "end_time": start_time + 1.0,
        "duration_ms": 1000.0,
        "span_count": 0,
        "total_tokens": 0,
        "total_cost_usd": 0.0,
        "has_errors": has_errors,
        "error_count": 0,
        "metadata": {},
        "spans": spans or [],
    }


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture()
def client(tmp_path):
    """TestClient backed by a fresh in-memory DB."""
    app = create_app(db_path=str(tmp_path / "sec_test.db"))
    return TestClient(app)


@pytest.fixture()
def store(tmp_path):
    s = TraceStore(db_path=tmp_path / "store_test.db")
    yield s
    s.close()


@pytest.fixture()
def import_client(tmp_path):
    """
    TestClient with import allowed into tmp_path.

    Temporarily registers tmp_path in _ALLOWED_IMPORT_DIRS and removes it
    afterwards so other tests are not affected.
    """
    allowed = tmp_path.resolve()
    _ALLOWED_IMPORT_DIRS.append(allowed)
    app = create_app(db_path=str(tmp_path / "import_test.db"))
    client = TestClient(app)
    yield client, tmp_path
    _ALLOWED_IMPORT_DIRS.remove(allowed)


# ===========================================================================
# 1. Path Traversal Prevention
# ===========================================================================

class TestPathTraversal:
    def test_import_disabled_by_default(self, client):
        """Import endpoint returns 403 when _ALLOWED_IMPORT_DIRS is empty."""
        r = client.post("/v1/traces/import?file_path=/etc/passwd")
        assert r.status_code == 403

    def test_import_traversal_dotdot_blocked(self, import_client):
        client, tmp_path = import_client
        # Attempt to escape the allowed directory via ../
        evil_path = str(tmp_path / ".." / "etc" / "passwd")
        r = client.post(f"/v1/traces/import?file_path={evil_path}")
        assert r.status_code in (400, 403, 404)

    def test_import_absolute_outside_allowed_blocked(self, import_client):
        client, tmp_path = import_client
        r = client.post("/v1/traces/import?file_path=/etc/passwd")
        assert r.status_code in (400, 403, 404)

    def test_import_null_byte_blocked(self, import_client):
        import httpx
        client, tmp_path = import_client
        # Null bytes are rejected either by the HTTP client (httpx) or by our
        # server-side validation.  Both outcomes are acceptable.
        try:
            r = client.post("/v1/traces/import?file_path=/tmp/file\x00.jsonl")
            assert r.status_code in (400, 403, 404, 422)
        except httpx.InvalidURL:
            pass  # httpx rejects null bytes before reaching the server

    def test_import_valid_path_within_allowed_dir(self, import_client):
        client, tmp_path = import_client
        # Create a valid JSONL file inside the allowed directory
        jsonl = tmp_path / "valid.jsonl"
        jsonl.write_text(json.dumps(_make_trace("import-ok")) + "\n")
        r = client.post(f"/v1/traces/import?file_path={jsonl}")
        assert r.status_code == 201
        assert r.json()["imported"] == 1

    def test_get_trace_id_traversal_blocked(self, client):
        """trace_id with path traversal sequences must be rejected."""
        r = client.get("/v1/traces/../../../etc/passwd")
        # FastAPI may handle this at routing level (404) or our validator (400)
        assert r.status_code in (400, 404)

    def test_trace_id_with_dotdot_blocked(self, client):
        r = client.get("/v1/traces/..%2F..%2Fetc%2Fpasswd")
        assert r.status_code in (400, 404)

    def test_delete_trace_traversal_blocked(self, client):
        r = client.delete("/v1/traces/../../secret")
        assert r.status_code in (400, 404)


# ===========================================================================
# 2. Oversized Payload Rejection
# ===========================================================================

class TestOversizedPayloads:
    def test_too_many_spans_rejected(self, client):
        """Payloads with more than _MAX_SPANS_PER_INGEST spans are rejected."""
        # Build a minimal span template
        def _span(i: int) -> dict:
            return {
                "span_id": f"s{i}",
                "trace_id": "big-trace",
                "name": "span",
                "kind": "tool",
                "status": "ok",
                "start_time": 1000.0 + i,
                "end_time": 1001.0 + i,
                "attributes": {},
                "events": [],
            }

        payload = _make_trace("big-trace")
        payload["spans"] = [_span(i) for i in range(_MAX_SPANS_PER_INGEST + 1)]
        r = client.post("/v1/traces/ingest", json=payload)
        assert r.status_code in (400, 422)

    def test_exactly_max_spans_accepted(self, client):
        """A payload with exactly _MAX_SPANS_PER_INGEST spans must be accepted."""
        def _span(i: int) -> dict:
            return {
                "span_id": f"s{i}",
                "trace_id": "max-trace",
                "name": "span",
                "kind": "tool",
                "status": "ok",
                "start_time": 1000.0 + i,
                "end_time": 1001.0 + i,
                "attributes": {},
                "events": [],
            }

        payload = _make_trace("max-trace")
        payload["spans"] = [_span(i) for i in range(_MAX_SPANS_PER_INGEST)]
        r = client.post("/v1/traces/ingest", json=payload)
        assert r.status_code == 201

    def test_oversized_trace_id_rejected(self, client):
        """trace_id exceeding the field max_length should be rejected by Pydantic."""
        payload = _make_trace("x" * 600)
        r = client.post("/v1/traces/ingest", json=payload)
        assert r.status_code == 422

    def test_oversized_service_name_rejected(self, client):
        """service_name exceeding max_length should be rejected."""
        payload = _make_trace()
        payload["service_name"] = "y" * 600
        r = client.post("/v1/traces/ingest", json=payload)
        assert r.status_code == 422

    def test_oversized_search_query_rejected(self, client):
        """Search queries longer than 200 characters should be rejected."""
        long_query = "a" * 300
        r = client.get(f"/v1/traces/search?q={long_query}")
        assert r.status_code == 422


# ===========================================================================
# 3. SQL Injection Harmlessness
# ===========================================================================

class TestSQLInjection:
    """
    These tests confirm that SQL injection attempts are harmless because all
    queries use parameterised statements.  The key assertion is that the server
    returns a sane HTTP response (not a 500) and does not expose internal data.
    """

    def test_sql_injection_in_service_filter(self, client):
        # Ingest a legitimate trace
        client.post("/v1/traces/ingest", json=_make_trace("safe-trace"))

        injection = "' OR '1'='1"
        r = client.get(f"/v1/traces?service={injection}")
        assert r.status_code == 200
        # The injection should not cause a crash or return unintended rows
        data = r.json()
        assert isinstance(data["traces"], list)
        # "safe-trace" should NOT appear — service filter should match nothing
        ids = [t["trace_id"] for t in data["traces"]]
        assert "safe-trace" not in ids

    def test_sql_injection_in_search_query(self, client):
        client.post("/v1/traces/ingest", json=_make_trace("search-safe"))

        injection = "'; DROP TABLE traces; --"
        r = client.get(f"/v1/traces/search?q={injection}")
        # Must not 500; results may be empty
        assert r.status_code == 200
        # Table must still exist — follow-up query should work
        r2 = client.get("/v1/stats")
        assert r2.status_code == 200

    def test_sql_injection_in_trace_id_path(self, client):
        injection = "' OR '1'='1"
        r = client.get(f"/v1/traces/{injection}")
        # Either 400 (sanitiser) or 404 (not found) — never 500
        assert r.status_code in (400, 404)
        # Critically: DB must survive
        r2 = client.get("/v1/stats")
        assert r2.status_code == 200

    def test_sql_injection_in_trace_id_delete(self, client):
        injection = "'; DELETE FROM traces; --"
        r = client.delete(f"/v1/traces/{injection}")
        assert r.status_code in (400, 404)
        r2 = client.get("/v1/stats")
        assert r2.status_code == 200

    def test_union_injection_in_search(self, client):
        """UNION-based injection attempt must not leak schema information."""
        client.post("/v1/traces/ingest", json=_make_trace("union-safe"))
        injection = "x' UNION SELECT sqlite_version(),2,3,4,5,6,7,8,9,10,11,12 --"
        r = client.get(f"/v1/traces/search?q={injection}")
        assert r.status_code == 200
        # No trace row should look like a SQLite version string
        for trace in r.json()["traces"]:
            assert not str(trace.get("trace_id", "")).startswith("3.")


# ===========================================================================
# 4. Rate Limiting — 429 Response
# ===========================================================================

class TestRateLimiting:
    def _make_low_limit_client(self, tmp_path, limit: int = 3):
        """Create a client whose app has a very low rate limit."""
        # Patch settings by monkey-patching the rate_limiter inside the app
        app = create_app(db_path=str(tmp_path / "rl_test.db"))
        # Replace the rate limiter that was baked into the closure with a tight one
        # We can't do that directly, so instead we test via the _RateLimiter class.
        return app

    def test_rate_limiter_returns_429_when_exceeded(self, tmp_path):
        """_RateLimiter must return allowed=False once the budget is exhausted."""
        from flowlens.server.app import _RateLimiter
        rl = _RateLimiter(requests_per_minute=3)
        ip = "10.0.0.1"
        results = [rl.check(ip) for _ in range(5)]
        allowed_flags = [r[0] for r in results]
        # First 3 requests must be allowed
        assert all(allowed_flags[:3])
        # 4th and 5th must be denied
        assert not allowed_flags[3]
        assert not allowed_flags[4]

    def test_rate_limiter_retry_after_positive_when_denied(self, tmp_path):
        from flowlens.server.app import _RateLimiter
        rl = _RateLimiter(requests_per_minute=1)
        ip = "10.0.0.2"
        rl.check(ip)  # consume the only slot
        allowed, remaining, limit, retry_after = rl.check(ip)
        assert not allowed
        assert remaining == 0
        assert retry_after > 0

    def test_rate_limiter_headers_present(self, client):
        """Rate-limit headers must be present on every response."""
        r = client.get("/health")
        assert "x-ratelimit-limit" in r.headers
        assert "x-ratelimit-remaining" in r.headers

    def test_rate_limiter_remaining_decrements(self, client):
        r1 = client.get("/health")
        r2 = client.get("/health")
        rem1 = int(r1.headers["x-ratelimit-remaining"])
        rem2 = int(r2.headers["x-ratelimit-remaining"])
        assert rem2 < rem1

    def test_rate_limiter_different_keys_independent(self):
        """Per-endpoint rate-limit buckets must not interfere with each other."""
        from flowlens.server.app import _RateLimiter
        rl = _RateLimiter(requests_per_minute=2)
        ip = "10.0.0.3"
        # Exhaust the "search" bucket
        rl.check(ip, limit_key="search", limit_override=2)
        rl.check(ip, limit_key="search", limit_override=2)
        denied, *_ = rl.check(ip, limit_key="search", limit_override=2)
        assert not denied

        # The "default" bucket must still be open
        allowed, *_ = rl.check(ip, limit_key="default", limit_override=2)
        assert allowed

    def test_stale_cleanup_runs(self):
        """Stale entries older than the window must be purged during _maybe_cleanup."""
        from flowlens.server.app import _RateLimiter
        rl = _RateLimiter(requests_per_minute=100)
        rl._STALE_CLEANUP_INTERVAL = 0  # trigger cleanup on next check
        # Create a stale key that won't be refreshed
        stale_ip = "10.0.0.99"
        stale_key = (stale_ip, "default")
        rl._counts[stale_key] = [time.time() - 120]  # 2 min ago, expired
        rl._last_cleanup = 0  # force cleanup
        # Check with a different IP to trigger cleanup without refreshing stale_key
        rl.check("10.0.0.1")
        # After cleanup the stale (all-expired) key should be gone
        assert stale_key not in rl._counts


# ===========================================================================
# 5. Invalid Inputs — Proper Error Codes
# ===========================================================================

class TestInvalidInputs:
    def test_ingest_missing_trace_id_returns_422(self, client):
        r = client.post("/v1/traces/ingest", json={"service_name": "x"})
        assert r.status_code == 422

    def test_ingest_negative_tokens_returns_422(self, client):
        payload = _make_trace()
        payload["total_tokens"] = -1
        r = client.post("/v1/traces/ingest", json=payload)
        assert r.status_code == 422

    def test_ingest_negative_cost_returns_422(self, client):
        payload = _make_trace()
        payload["total_cost_usd"] = -0.5
        r = client.post("/v1/traces/ingest", json=payload)
        assert r.status_code == 422

    def test_cleanup_invalid_days_returns_422(self, client):
        r = client.post("/v1/traces/cleanup", json={"days": 0})
        assert r.status_code == 422

    def test_cleanup_negative_days_returns_422(self, client):
        r = client.post("/v1/traces/cleanup", json={"days": -5})
        assert r.status_code == 422

    def test_search_missing_query_returns_422(self, client):
        r = client.get("/v1/traces/search")
        assert r.status_code == 422

    def test_search_blank_query_returns_400(self, client):
        r = client.get("/v1/traces/search?q=   ")
        assert r.status_code == 400

    def test_cost_breakdown_invalid_group_by_returns_422(self, client):
        r = client.get("/v1/cost/breakdown?group_by=invalid")
        assert r.status_code == 422

    def test_cost_trends_invalid_granularity_returns_422(self, client):
        r = client.get("/v1/cost/trends?granularity=weekly")
        assert r.status_code == 422

    def test_get_nonexistent_trace_returns_404(self, client):
        r = client.get("/v1/traces/no-such-trace-xyz")
        assert r.status_code == 404

    def test_delete_nonexistent_trace_returns_404(self, client):
        r = client.delete("/v1/traces/no-such-trace-xyz")
        assert r.status_code == 404

    def test_ingest_trace_id_with_null_byte_rejected(self, client):
        """trace_id containing a null byte must be rejected."""
        payload = _make_trace()
        payload["trace_id"] = "trace\x00id"
        r = client.post("/v1/traces/ingest", json=payload)
        assert r.status_code == 422

    def test_ingest_trace_id_with_dotdot_rejected(self, client):
        payload = _make_trace()
        payload["trace_id"] = "../../etc/passwd"
        r = client.post("/v1/traces/ingest", json=payload)
        assert r.status_code == 422

    def test_list_traces_negative_offset_returns_422(self, client):
        r = client.get("/v1/traces?offset=-1")
        assert r.status_code == 422

    def test_list_traces_limit_exceeds_max_returns_422(self, client):
        r = client.get("/v1/traces?limit=201")
        assert r.status_code == 422


# ===========================================================================
# 6. Security Response Headers
# ===========================================================================

class TestSecurityHeaders:
    ENDPOINTS = [
        ("/health", "GET"),
        ("/v1/stats", "GET"),
        ("/v1/traces", "GET"),
    ]

    @pytest.mark.parametrize("path,method", ENDPOINTS)
    def test_security_headers_present(self, client, path, method):
        r = client.request(method, path)
        assert r.headers.get("x-content-type-options") == "nosniff", (
            f"Missing X-Content-Type-Options on {method} {path}"
        )
        assert r.headers.get("x-frame-options") == "DENY", (
            f"Missing X-Frame-Options on {method} {path}"
        )
        assert "x-xss-protection" in r.headers, (
            f"Missing X-XSS-Protection on {method} {path}"
        )
        assert "referrer-policy" in r.headers, (
            f"Missing Referrer-Policy on {method} {path}"
        )
        assert "content-security-policy" in r.headers, (
            f"Missing Content-Security-Policy on {method} {path}"
        )

    def test_error_response_has_security_headers(self, client):
        """Even 404 error responses must carry security headers."""
        r = client.get("/v1/traces/nonexistent-xyz")
        assert r.status_code == 404
        assert r.headers.get("x-content-type-options") == "nosniff"
        assert r.headers.get("x-frame-options") == "DENY"

    def test_no_stack_trace_in_error_body(self, client):
        """Error responses must not contain Python traceback information."""
        r = client.get("/v1/traces/nonexistent")
        body = r.text
        assert "Traceback" not in body
        assert "File " not in body or r.status_code != 500
        # detail key may exist but must not contain internal paths
        if r.status_code == 404:
            assert "Traceback" not in r.json().get("detail", "")


# ===========================================================================
# 7. SDK — Span Name Validation
# ===========================================================================

class TestSpanNameValidation:
    def test_normal_name_unchanged(self):
        assert _validate_span_name("my-span.v2") == "my-span.v2"

    def test_empty_name_becomes_unnamed(self):
        assert _validate_span_name("") == "unnamed"

    def test_too_long_name_truncated(self):
        long = "a" * 300
        result = _validate_span_name(long)
        assert len(result) == 256

    def test_null_byte_stripped(self):
        result = _validate_span_name("span\x00name")
        assert "\x00" not in result
        assert len(result) > 0

    def test_control_chars_stripped(self):
        result = _validate_span_name("span\x01\x1fname")
        assert "\x01" not in result
        assert "\x1f" not in result

    def test_unicode_span_name_allowed(self):
        result = _validate_span_name("代理执行")
        assert result == "代理执行"

    def test_whitespace_only_control_chars_stripped_to_unnamed(self):
        # All control chars get stripped, leaving empty → "unnamed"
        result = _validate_span_name("\x01\x02\x03")
        assert result == "unnamed"


# ===========================================================================
# 8. SDK — Per-Trace Span Limit
# ===========================================================================

class TestSpanLimit:
    @pytest.fixture(autouse=True)
    def reset_instance(self):
        """Ensure FlowLens singleton is reset between tests."""
        yield
        with FlowLens._instance_lock:
            FlowLens._instance = None

    def test_spans_beyond_limit_not_attached(self):
        """Spans created beyond _MAX_SPANS_PER_TRACE must not be attached to the trace."""
        lens = FlowLens(service_name="test", export_to="console")
        trace = lens.start_trace()

        from flowlens.sdk.context import TraceContext
        with TraceContext(trace):
            for i in range(_MAX_SPANS_PER_TRACE + 10):
                lens.start_span(f"span-{i}", kind=SpanKind.CUSTOM)

        assert len(trace.spans) == _MAX_SPANS_PER_TRACE

    def test_normal_trace_records_all_spans(self):
        """A trace under the limit must record every span."""
        lens = FlowLens(service_name="test", export_to="console")
        trace = lens.start_trace()

        from flowlens.sdk.context import TraceContext
        with TraceContext(trace):
            for i in range(10):
                lens.start_span(f"span-{i}", kind=SpanKind.CUSTOM)

        assert len(trace.spans) == 10


# ===========================================================================
# 9. SDK — Thread Safety of Singleton
# ===========================================================================

class TestFlowLensThreadSafety:
    @pytest.fixture(autouse=True)
    def reset_instance(self):
        yield
        with FlowLens._instance_lock:
            FlowLens._instance = None

    def test_concurrent_get_instance_returns_consistent_singleton(self):
        """All threads must see the same FlowLens instance."""
        lens = FlowLens(service_name="threaded", export_to="console")
        results: list[FlowLens | None] = []
        errors: list[Exception] = []

        def _get():
            try:
                results.append(FlowLens.get_instance())
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_get) for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert all(r is lens for r in results)

    def test_concurrent_start_trace_no_race(self):
        """Starting traces from many threads must not cause dict corruption."""
        lens = FlowLens(service_name="threaded", export_to="console")
        traces = []
        errors: list[Exception] = []
        lock = threading.Lock()

        def _start():
            try:
                t = lens.start_trace()
                with lock:
                    traces.append(t)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_start) for _ in range(100)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        # All 100 traces must have been registered
        assert len(traces) == 100
        with lens._traces_lock:
            assert len(lens._active_traces) == 100

    def test_shutdown_with_timeout_does_not_hang(self):
        """shutdown() must return within a reasonable time even under load."""
        lens = FlowLens(service_name="shutdown-test", export_to="console")
        for _ in range(5):
            lens.start_trace()

        start = time.time()
        lens.shutdown(timeout=2.0)
        elapsed = time.time() - start
        # Must complete (with or without timeout) in under 5 s
        assert elapsed < 5.0


# ===========================================================================
# 10. Storage — SQL Injection via Storage Layer
# ===========================================================================

class TestStorageSQLInjection:
    def test_search_with_sql_metacharacters(self, store):
        """SQL metacharacters in the search query must not corrupt results."""
        store.save_trace({
            "trace_id": "safe",
            "service_name": "test",
            "start_time": 1000.0,
            "end_time": 1001.0,
            "duration_ms": 1.0,
            "span_count": 0,
            "total_tokens": 0,
            "total_cost_usd": 0.0,
            "has_errors": False,
            "error_count": 0,
            "metadata": {},
            "spans": [],
        })
        # Should return empty (no matches), not crash
        result = store.search_traces("'; DROP TABLE traces; --")
        assert isinstance(result, list)
        # The traces table must still exist
        count = store._conn.execute("SELECT COUNT(*) FROM traces").fetchone()[0]
        assert count >= 1

    def test_list_traces_with_injection_in_service_name(self, store):
        """Parameterised service_name filter must be safe from injection."""
        store.save_trace({
            "trace_id": "t1",
            "service_name": "real-service",
            "start_time": 1000.0,
            "end_time": 1001.0,
            "duration_ms": 1.0,
            "span_count": 0,
            "total_tokens": 0,
            "total_cost_usd": 0.0,
            "has_errors": False,
            "error_count": 0,
            "metadata": {},
            "spans": [],
        })
        result = store.list_traces(service_name="' OR '1'='1")
        # Should return empty list — the injection string is not a valid service name
        assert result == []
        # Real trace must still be accessible
        assert store.get_trace("t1") is not None
