"""
Tests for flowlens.server.validation — trace payload validation module.

Covers:
- Valid trace passes validation
- Missing / empty trace_id fails
- trace_id too long or contains invalid characters fails
- Orphan parent_span_id (no matching span in trace) fails
- Circular parent-child relationship detected
- Span count exceeding limit fails
- Invalid kind value fails
- Empty spans list fails (strict mode) / passes (lenient mode)
- Duplicate span_ids detected
- Missing start_time / end_time are allowed (lenient)
- Invalid (non-numeric) start_time / end_time fail
- Payload size check
- Integration: ingest endpoint rejects invalid traces (422)
- Integration: import endpoint skips invalid traces
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from flowlens.server.app import _ALLOWED_IMPORT_DIRS, create_app
from flowlens.server.validation import (
    _MAX_PAYLOAD_BYTES,
    _MAX_SPANS_PER_TRACE,
    _VALID_KINDS,
    check_payload_size,
    validate_trace,
)

# ===========================================================================
# Helpers
# ===========================================================================


def _make_span(
    span_id: str = "s1",
    parent_span_id: str | None = None,
    kind: str = "agent",
    start_time: float = 1000.0,
    end_time: float = 1001.0,
) -> dict[str, Any]:
    return {
        "span_id": span_id,
        "parent_span_id": parent_span_id,
        "name": f"span-{span_id}",
        "kind": kind,
        "status": "ok",
        "start_time": start_time,
        "end_time": end_time,
        "duration_ms": (end_time - start_time) * 1000,
        "attributes": {},
        "events": [],
    }


def _make_trace(
    trace_id: str = "abc123",
    spans: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if spans is None:
        spans = [_make_span("s1")]
    return {
        "trace_id": trace_id,
        "service_name": "test-svc",
        "start_time": 1000.0,
        "end_time": 1001.0,
        "duration_ms": 1000.0,
        "span_count": len(spans),
        "total_tokens": 0,
        "total_cost_usd": 0.0,
        "has_errors": False,
        "error_count": 0,
        "metadata": {},
        "spans": spans,
    }


# ===========================================================================
# Unit tests for validate_trace()
# ===========================================================================


class TestValidTracePassesValidation:
    """A well-formed trace should pass without errors."""

    def test_minimal_valid_trace(self):
        trace = _make_trace()
        ok, err = validate_trace(trace)
        assert ok is True
        assert err is None

    def test_valid_trace_with_parent_child(self):
        spans = [
            _make_span("root", parent_span_id=None),
            _make_span("child", parent_span_id="root"),
            _make_span("grandchild", parent_span_id="child"),
        ]
        trace = _make_trace(spans=spans)
        ok, err = validate_trace(trace)
        assert ok is True
        assert err is None

    def test_valid_trace_all_span_kinds(self):
        spans = [
            _make_span(f"s{i}", kind=kind, parent_span_id=None if i == 0 else "s0")
            for i, kind in enumerate(sorted(_VALID_KINDS))
        ]
        trace = _make_trace(spans=spans)
        ok, err = validate_trace(trace)
        assert ok is True
        assert err is None

    def test_valid_trace_uuid_style_id(self):
        trace = _make_trace(trace_id="550e8400-e29b-41d4-a716-446655440000")
        ok, err = validate_trace(trace)
        assert ok is True

    def test_valid_trace_hex_id(self):
        trace = _make_trace(trace_id="deadbeef1234567890abcdef")
        ok, err = validate_trace(trace)
        assert ok is True

    def test_missing_end_time_on_span_allowed(self):
        """end_time = 0 / missing should not cause rejection (lenient)."""
        spans = [{"span_id": "s1", "name": "test", "kind": "tool", "start_time": 1000.0}]
        trace = _make_trace(spans=spans)
        ok, err = validate_trace(trace)
        assert ok is True

    def test_zero_timestamps_allowed(self):
        """start_time=0 and end_time=0 should pass (legacy / default values)."""
        spans = [{"span_id": "s1", "name": "test", "kind": "tool", "start_time": 0, "end_time": 0}]
        trace = _make_trace(spans=spans)
        ok, err = validate_trace(trace)
        assert ok is True


class TestMissingTraceIdFails:
    def test_none_trace_id(self):
        trace = _make_trace()
        trace["trace_id"] = None
        ok, err = validate_trace(trace)
        assert ok is False
        assert "trace_id" in err

    def test_empty_string_trace_id(self):
        trace = _make_trace()
        trace["trace_id"] = ""
        ok, err = validate_trace(trace)
        assert ok is False
        assert "trace_id" in err

    def test_missing_trace_id_key(self):
        trace = _make_trace()
        del trace["trace_id"]
        ok, err = validate_trace(trace)
        assert ok is False
        assert "trace_id" in err

    def test_numeric_trace_id_fails(self):
        trace = _make_trace()
        trace["trace_id"] = 12345  # not a string
        ok, err = validate_trace(trace)
        assert ok is False

    def test_trace_id_too_long(self):
        trace = _make_trace(trace_id="a" * 65)
        ok, err = validate_trace(trace)
        assert ok is False
        assert "64" in err

    def test_trace_id_exactly_at_limit(self):
        trace = _make_trace(trace_id="a" * 64)
        ok, err = validate_trace(trace)
        assert ok is True

    def test_trace_id_invalid_characters(self):
        trace = _make_trace(trace_id="bad\x00id")
        ok, err = validate_trace(trace)
        assert ok is False
        assert "invalid characters" in err.lower() or "trace_id" in err


class TestOrphanParentSpanIdFails:
    def test_orphan_parent_reference(self):
        spans = [
            _make_span("s1", parent_span_id="nonexistent-span"),
        ]
        trace = _make_trace(spans=spans)
        ok, err = validate_trace(trace)
        assert ok is False
        assert "orphan" in err.lower() or "nonexistent-span" in err or "does not exist" in err

    def test_self_reference_as_parent_fails(self):
        """A span referencing itself as parent is an orphan/cycle."""
        spans = [
            _make_span("s1", parent_span_id="s1"),
        ]
        trace = _make_trace(spans=spans)
        ok, err = validate_trace(trace)
        # Either orphan (s1 references itself, which appears to exist but creates a cycle)
        # or circular detection — either way it must fail
        assert ok is False

    def test_partial_orphan_in_multi_span_trace(self):
        spans = [
            _make_span("root", parent_span_id=None),
            _make_span("child", parent_span_id="root"),
            _make_span("orphan-child", parent_span_id="ghost-span"),
        ]
        trace = _make_trace(spans=spans)
        ok, err = validate_trace(trace)
        assert ok is False


class TestCircularParentChildDetected:
    def test_simple_two_node_cycle(self):
        spans = [
            _make_span("s1", parent_span_id="s2"),
            _make_span("s2", parent_span_id="s1"),
        ]
        trace = _make_trace(spans=spans)
        ok, err = validate_trace(trace)
        assert ok is False
        assert "circular" in err.lower() or "cycle" in err.lower()

    def test_three_node_cycle(self):
        spans = [
            _make_span("s1", parent_span_id="s3"),
            _make_span("s2", parent_span_id="s1"),
            _make_span("s3", parent_span_id="s2"),
        ]
        trace = _make_trace(spans=spans)
        ok, err = validate_trace(trace)
        assert ok is False
        assert "circular" in err.lower() or "cycle" in err.lower()

    def test_cycle_in_larger_valid_graph(self):
        """A cycle in one sub-tree is caught even when the rest of the graph is valid."""
        spans = [
            _make_span("root", parent_span_id=None),
            _make_span("child1", parent_span_id="root"),
            _make_span("child2", parent_span_id="root"),
            # Hidden cycle: child2 <-> cycle-a <-> cycle-b
            _make_span("cycle-a", parent_span_id="cycle-b"),
            _make_span("cycle-b", parent_span_id="cycle-a"),
        ]
        trace = _make_trace(spans=spans)
        ok, err = validate_trace(trace)
        assert ok is False


class TestSpanCountExceedingLimitFails:
    def test_exactly_at_limit_passes(self):
        spans = [_make_span(f"s{i}") for i in range(_MAX_SPANS_PER_TRACE)]
        # All have no parent so no orphan issues; just a flat list
        trace = _make_trace(spans=spans)
        ok, err = validate_trace(trace)
        assert ok is True

    def test_one_over_limit_fails(self):
        spans = [_make_span(f"s{i}") for i in range(_MAX_SPANS_PER_TRACE + 1)]
        trace = _make_trace(spans=spans)
        ok, err = validate_trace(trace)
        assert ok is False
        assert str(_MAX_SPANS_PER_TRACE) in err or "spans" in err.lower()

    def test_env_var_override(self, monkeypatch):
        """FLOWLENS_MAX_SPANS_PER_TRACE env var changes the limit."""
        import importlib

        import flowlens.server.validation as val_module

        monkeypatch.setenv("FLOWLENS_MAX_SPANS_PER_TRACE", "5")
        # Reload the module so the env var is picked up
        importlib.reload(val_module)

        # 6 spans should now fail
        spans = (
            [val_module._make_span_for_test(i) for i in range(6)]
            if hasattr(val_module, "_make_span_for_test")
            else [{"span_id": f"s{i}", "name": f"span-{i}", "kind": "tool"} for i in range(6)]
        )
        trace = {"trace_id": "t1", "spans": spans}
        ok, err = val_module.validate_trace(trace)
        assert ok is False

        # Restore module to default state
        monkeypatch.delenv("FLOWLENS_MAX_SPANS_PER_TRACE", raising=False)
        importlib.reload(val_module)


class TestInvalidKindValueFails:
    def test_unknown_kind_fails(self):
        spans = [_make_span("s1", kind="unknown-kind")]
        trace = _make_trace(spans=spans)
        ok, err = validate_trace(trace)
        assert ok is False
        assert "kind" in err.lower()
        assert "unknown-kind" in err

    def test_uppercase_kind_fails(self):
        """kind values are case-sensitive — 'AGENT' is not 'agent'."""
        spans = [_make_span("s1", kind="AGENT")]
        trace = _make_trace(spans=spans)
        ok, err = validate_trace(trace)
        assert ok is False

    def test_none_kind_is_allowed(self):
        """kind=None (missing field) should pass — lenient for optional field."""
        spans = [{"span_id": "s1", "name": "test"}]
        trace = _make_trace(spans=spans)
        ok, err = validate_trace(trace)
        assert ok is True

    @pytest.mark.parametrize("valid_kind", sorted(_VALID_KINDS))
    def test_each_valid_kind_passes(self, valid_kind):
        spans = [_make_span("s1", kind=valid_kind)]
        trace = _make_trace(spans=spans)
        ok, err = validate_trace(trace)
        assert ok is True, f"Expected kind '{valid_kind}' to be valid, got: {err}"


class TestEmptySpansListFails:
    def test_empty_spans_fails_in_strict_mode(self):
        """Default require_spans=True: empty list fails."""
        trace = _make_trace(spans=[])
        ok, err = validate_trace(trace, require_spans=True)
        assert ok is False
        assert "empty" in err.lower() or "spans" in err.lower()

    def test_empty_spans_passes_in_lenient_mode(self):
        """require_spans=False: empty list is allowed (backward compat)."""
        trace = _make_trace(spans=[])
        ok, err = validate_trace(trace, require_spans=False)
        assert ok is True
        assert err is None

    def test_none_spans_always_fails(self):
        """spans=None fails regardless of mode."""
        trace = _make_trace()
        trace["spans"] = None
        ok, err = validate_trace(trace)
        assert ok is False

    def test_missing_spans_key_fails(self):
        trace = _make_trace()
        del trace["spans"]
        ok, err = validate_trace(trace)
        assert ok is False
        assert "spans" in err.lower()


class TestDuplicateSpanIdsDetected:
    def test_two_spans_same_id_fails(self):
        spans = [
            _make_span("duplicate-id"),
            _make_span("duplicate-id"),
        ]
        trace = _make_trace(spans=spans)
        ok, err = validate_trace(trace)
        assert ok is False
        assert "duplicate" in err.lower()
        assert "duplicate-id" in err

    def test_three_spans_one_duplicate_fails(self):
        spans = [
            _make_span("s1"),
            _make_span("s2"),
            _make_span("s1"),  # duplicate of first
        ]
        trace = _make_trace(spans=spans)
        ok, err = validate_trace(trace)
        assert ok is False
        assert "s1" in err

    def test_all_unique_span_ids_passes(self):
        spans = [_make_span(f"span-{i}") for i in range(10)]
        trace = _make_trace(spans=spans)
        ok, err = validate_trace(trace)
        assert ok is True


class TestSpanTimestampValidation:
    def test_negative_start_time_fails(self):
        spans = [_make_span("s1", start_time=-1.0, end_time=1000.0)]
        trace = _make_trace(spans=spans)
        ok, err = validate_trace(trace)
        assert ok is False
        assert "start_time" in err

    def test_negative_end_time_fails(self):
        spans = [_make_span("s1", start_time=1000.0, end_time=-5.0)]
        trace = _make_trace(spans=spans)
        ok, err = validate_trace(trace)
        assert ok is False
        assert "end_time" in err

    def test_valid_timestamps_pass(self):
        spans = [_make_span("s1", start_time=1000.0, end_time=1001.0)]
        trace = _make_trace(spans=spans)
        ok, err = validate_trace(trace)
        assert ok is True


class TestCheckPayloadSize:
    def test_small_payload_passes(self):
        ok, err = check_payload_size(b"hello world")
        assert ok is True
        assert err is None

    def test_exact_limit_passes(self):
        ok, err = check_payload_size(b"x" * _MAX_PAYLOAD_BYTES)
        assert ok is True

    def test_one_byte_over_limit_fails(self):
        ok, err = check_payload_size(b"x" * (_MAX_PAYLOAD_BYTES + 1))
        assert ok is False
        assert "MB" in err or "large" in err.lower()

    def test_empty_payload_passes(self):
        ok, err = check_payload_size(b"")
        assert ok is True


# ===========================================================================
# Integration tests — HTTP endpoint behaviour
# ===========================================================================


@pytest.fixture()
def client(tmp_path):
    """TestClient backed by a fresh temporary DB."""
    app = create_app(db_path=str(tmp_path / "test_validation.db"))
    return TestClient(app)


@pytest.fixture()
def import_client(tmp_path):
    """TestClient with import endpoint enabled for tmp_path."""
    allowed = tmp_path.resolve()
    _ALLOWED_IMPORT_DIRS.append(allowed)
    app = create_app(db_path=str(tmp_path / "import_val.db"))
    c = TestClient(app)
    yield c, tmp_path
    _ALLOWED_IMPORT_DIRS.remove(allowed)


def _post_trace(client, trace: dict[str, Any]) -> Any:
    return client.post("/v1/traces/ingest", json=trace)


class TestIngestEndpointValidation:
    """Ingest endpoint should reject structurally invalid traces with 422."""

    def test_valid_trace_accepted(self, client):
        trace = _make_trace("valid-trace-1")
        resp = _post_trace(client, trace)
        assert resp.status_code == 201

    def test_trace_with_valid_parent_child_accepted(self, client):
        spans = [
            _make_span("root"),
            _make_span("child", parent_span_id="root"),
        ]
        trace = _make_trace("valid-trace-2", spans=spans)
        resp = _post_trace(client, trace)
        assert resp.status_code == 201

    def test_orphan_parent_rejected(self, client):
        spans = [_make_span("s1", parent_span_id="ghost")]
        trace = _make_trace("orphan-trace", spans=spans)
        resp = _post_trace(client, trace)
        assert resp.status_code == 422
        assert "ghost" in resp.json()["detail"] or "validation" in resp.json()["detail"].lower()

    def test_circular_reference_rejected(self, client):
        spans = [
            _make_span("a", parent_span_id="b"),
            _make_span("b", parent_span_id="a"),
        ]
        trace = _make_trace("cycle-trace", spans=spans)
        resp = _post_trace(client, trace)
        assert resp.status_code == 422

    def test_duplicate_span_ids_rejected(self, client):
        spans = [_make_span("dup"), _make_span("dup")]
        trace = _make_trace("dup-trace", spans=spans)
        resp = _post_trace(client, trace)
        assert resp.status_code == 422

    def test_invalid_kind_rejected(self, client):
        spans = [_make_span("s1", kind="bad-kind")]
        trace = _make_trace("bad-kind-trace", spans=spans)
        resp = _post_trace(client, trace)
        assert resp.status_code == 422

    def test_empty_spans_accepted_for_backward_compat(self, client):
        """Empty spans list must still be accepted for existing integrations."""
        trace = _make_trace("empty-spans-trace", spans=[])
        resp = _post_trace(client, trace)
        assert resp.status_code == 201

    def test_invalid_trace_id_characters_rejected(self, client):
        """trace_id with null byte should be caught by Pydantic or validation."""
        # Pydantic catches null byte before our validator, both give 422
        trace = _make_trace()
        trace["trace_id"] = "bad\x00id"
        resp = _post_trace(client, trace)
        assert resp.status_code in (400, 422)

    def test_trace_id_too_long_rejected(self, client):
        """trace_id exceeding 64 chars should be rejected."""
        trace = _make_trace(trace_id="a" * 65)
        resp = _post_trace(client, trace)
        assert resp.status_code == 422


class TestImportEndpointValidation:
    """Import endpoint should skip invalid traces and report the count."""

    def test_valid_jsonl_all_imported(self, import_client):
        client, tmp_path = import_client
        lines = [json.dumps(_make_trace(f"t{i}")) for i in range(3)]
        jsonl_file = tmp_path / "valid.jsonl"
        jsonl_file.write_text("\n".join(lines))

        resp = client.post(f"/v1/traces/import?file_path={jsonl_file}")
        assert resp.status_code == 201
        data = resp.json()
        assert data["imported"] == 3
        assert data["errors"] == 0

    def test_invalid_traces_skipped_count_reported(self, import_client):
        client, tmp_path = import_client
        valid_trace = json.dumps(_make_trace("valid-1"))
        # Orphan parent reference — invalid
        invalid_spans = [_make_span("s1", parent_span_id="nonexistent")]
        invalid_trace = json.dumps(_make_trace("invalid-1", spans=invalid_spans))

        jsonl_file = tmp_path / "mixed.jsonl"
        jsonl_file.write_text(f"{valid_trace}\n{invalid_trace}\n")

        resp = client.post(f"/v1/traces/import?file_path={jsonl_file}")
        assert resp.status_code == 201
        data = resp.json()
        assert data["imported"] == 1
        assert data["errors"] == 1

    def test_all_invalid_traces_reported(self, import_client):
        client, tmp_path = import_client
        # Circular cycle
        spans = [_make_span("a", parent_span_id="b"), _make_span("b", parent_span_id="a")]
        bad_trace = json.dumps(_make_trace("bad-1", spans=spans))

        jsonl_file = tmp_path / "allbad.jsonl"
        jsonl_file.write_text(bad_trace)

        resp = client.post(f"/v1/traces/import?file_path={jsonl_file}")
        assert resp.status_code == 201
        data = resp.json()
        assert data["imported"] == 0
        assert data["errors"] == 1
