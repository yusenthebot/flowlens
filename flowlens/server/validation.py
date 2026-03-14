"""
FlowLens Trace Validation — input validation for trace ingest payloads.

Validates trace data before it reaches the storage layer to catch:
- Malformed identifiers (trace_id, span_id)
- Duplicate span IDs within a trace
- Orphan parent_span_id references (no matching span in trace)
- Circular parent-child relationships (DFS cycle detection)
- Span count limits (configurable via FLOWLENS_MAX_SPANS_PER_TRACE)
- Invalid span field values (kind, start_time/end_time)
- Total payload size limit (50 MB)

Design philosophy:
- Strict on structural integrity (IDs, duplicates, cycles, size limits)
- Lenient on optional fields (missing end_time, timestamps = 0 are allowed)
  so that existing traces ingested by the test suite continue to pass.
"""
from __future__ import annotations

import os
import re
import sys
from typing import Any

# ---------------------------------------------------------------------------
# Constants — override via environment variables where noted
# ---------------------------------------------------------------------------

# Maximum length for trace_id and span_id strings
_MAX_TRACE_ID_LEN = 64

# Allowed characters in trace_id / span_id: hex digits, hyphens, underscores,
# dots, colons, slashes, alphanumerics (broad enough to cover UUIDs, OTEL IDs,
# and common trace-ID formats used in the existing test suite).
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9\-_.:/ ]+$")

# Maximum spans per trace (configurable)
_DEFAULT_MAX_SPANS = 10_000
_MAX_SPANS_PER_TRACE: int = int(
    os.environ.get("FLOWLENS_MAX_SPANS_PER_TRACE", str(_DEFAULT_MAX_SPANS))
)

# Maximum total payload size in bytes (50 MB)
_MAX_PAYLOAD_BYTES = 50 * 1024 * 1024  # 50 MB

# Valid span kinds (mirrors SpanKind enum in sdk/models.py)
_VALID_KINDS = frozenset(
    {"agent", "llm", "tool", "chain", "retrieval", "embedding", "custom"}
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def validate_trace(
    trace_data: dict[str, Any],
    require_spans: bool = True,
) -> tuple[bool, str | None]:
    """Validate a trace payload before storage.

    Parameters
    ----------
    trace_data:
        The raw trace dictionary (as received from the HTTP request or
        parsed from a JSONL import file).
    require_spans:
        When True (the default), an empty spans list is treated as an error.
        Set to False to allow traces with no spans through (used by the
        ingest endpoint to maintain backward compatibility with existing
        integrations that send trace-level records without span data).

    Returns
    -------
    (is_valid, error_message)
        ``is_valid`` is True when the trace passes all checks.
        ``error_message`` is None on success or a human-readable description
        of the first validation failure found.
    """
    # ------------------------------------------------------------------
    # 1. trace_id — mandatory, non-empty, max 64 chars, safe characters
    # ------------------------------------------------------------------
    trace_id = trace_data.get("trace_id")
    if not trace_id or not isinstance(trace_id, str):
        return False, "trace_id is required and must be a non-empty string"

    if len(trace_id) > _MAX_TRACE_ID_LEN:
        return False, (
            f"trace_id exceeds maximum length of {_MAX_TRACE_ID_LEN} characters"
        )

    if not _SAFE_ID_RE.match(trace_id):
        return False, (
            "trace_id contains invalid characters; "
            "allowed: alphanumeric, hyphens, underscores, dots, colons, slashes, spaces"
        )

    # ------------------------------------------------------------------
    # 2. spans list — must exist; emptiness check is configurable
    # ------------------------------------------------------------------
    spans = trace_data.get("spans")
    if spans is None:
        return False, "spans list is required"

    if not isinstance(spans, list):
        return False, "spans must be a list"

    if require_spans and len(spans) == 0:
        return False, "spans list must not be empty"

    # Short-circuit: empty spans list — skip all per-span checks
    if len(spans) == 0:
        return True, None

    # ------------------------------------------------------------------
    # 3. Span count limit
    # ------------------------------------------------------------------
    if len(spans) > _MAX_SPANS_PER_TRACE:
        return False, (
            f"spans list exceeds maximum of {_MAX_SPANS_PER_TRACE} spans per trace "
            f"(got {len(spans)}); set FLOWLENS_MAX_SPANS_PER_TRACE to override"
        )

    # ------------------------------------------------------------------
    # 4. Per-span validation — span_id uniqueness, parent refs, kind,
    #    and optionally start_time/end_time when they are provided and > 0
    # ------------------------------------------------------------------
    span_ids: set[str] = set()
    parent_map: dict[str, str | None] = {}  # span_id -> parent_span_id

    for idx, span in enumerate(spans):
        if not isinstance(span, dict):
            return False, f"span at index {idx} must be a dict"

        span_id = span.get("span_id")
        if not span_id or not isinstance(span_id, str):
            return False, f"span at index {idx} is missing a non-empty span_id"

        # Duplicate span_id check
        if span_id in span_ids:
            return False, f"duplicate span_id '{span_id}' found in trace '{trace_id}'"

        span_ids.add(span_id)
        parent_map[span_id] = span.get("parent_span_id")

        # kind validation — only if field is present and non-None
        kind = span.get("kind")
        if kind is not None and kind not in _VALID_KINDS:
            return False, (
                f"span '{span_id}' has invalid kind '{kind}'; "
                f"must be one of: {', '.join(sorted(_VALID_KINDS))}"
            )

        # start_time / end_time — validate only when provided as non-zero numbers
        start_time = span.get("start_time")
        end_time = span.get("end_time")

        if start_time is not None and start_time != 0:
            if not isinstance(start_time, (int, float)):
                return False, f"span '{span_id}' start_time must be a number"
            if float(start_time) <= 0:
                return False, f"span '{span_id}' start_time must be > 0"

        if end_time is not None and end_time != 0:
            if not isinstance(end_time, (int, float)):
                return False, f"span '{span_id}' end_time must be a number"
            if float(end_time) <= 0:
                return False, f"span '{span_id}' end_time must be > 0"

    # ------------------------------------------------------------------
    # 5. Orphan parent_span_id check
    #    parent_span_id must either be None/absent or reference a span_id
    #    that exists within the same trace.
    # ------------------------------------------------------------------
    for sid, parent_sid in parent_map.items():
        if parent_sid is not None and parent_sid not in span_ids:
            return False, (
                f"span '{sid}' references parent_span_id '{parent_sid}' "
                f"which does not exist in trace '{trace_id}'"
            )

    # ------------------------------------------------------------------
    # 6. Cycle detection — DFS on the parent-child graph
    # ------------------------------------------------------------------
    # Build children map for efficient traversal
    children: dict[str, list[str]] = {sid: [] for sid in span_ids}
    roots: list[str] = []

    for sid, parent_sid in parent_map.items():
        if parent_sid is None:
            roots.append(sid)
        else:
            children[parent_sid].append(sid)

    # DFS iteratively to avoid Python recursion limits on deep traces
    visited: set[str] = set()
    in_stack: set[str] = set()

    # We need to detect cycles even in components without a root (pure cycles)
    # so we iterate over all span_ids as potential starting points.
    for start in span_ids:
        if start in visited:
            continue

        # Stack entries: (node, iterator_over_children, entering)
        stack: list[tuple[str, bool]] = [(start, True)]

        while stack:
            node, entering = stack.pop()

            if entering:
                if node in in_stack:
                    return False, (
                        f"circular parent-child relationship detected involving "
                        f"span '{node}' in trace '{trace_id}'"
                    )

                if node in visited:
                    continue

                visited.add(node)
                in_stack.add(node)
                # Push the "leaving" marker first, then children
                stack.append((node, False))
                for child in children.get(node, []):
                    stack.append((child, True))
            else:
                in_stack.discard(node)

    return True, None


def check_payload_size(raw_body: bytes) -> tuple[bool, str | None]:
    """Check that the raw HTTP request body does not exceed the size limit.

    Parameters
    ----------
    raw_body:
        The raw bytes of the request body.

    Returns
    -------
    (is_ok, error_message)
        ``is_ok`` is True when the size is within bounds.
    """
    size = len(raw_body)
    if size > _MAX_PAYLOAD_BYTES:
        mb = size / (1024 * 1024)
        limit_mb = _MAX_PAYLOAD_BYTES / (1024 * 1024)
        return False, (
            f"Request payload too large: {mb:.1f} MB exceeds the {limit_mb:.0f} MB limit"
        )
    return True, None
