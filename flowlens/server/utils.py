"""
Shared utilities for FlowLens server route handlers.

Contains:
- _sanitize_id: validate string IDs for security
- _reconstruct_trace: rebuild Trace objects from stored dicts
- _parse_tags: safely parse JSON or dict tags from trace metadata
- _AGENT_PROFILES: built-in agent profile definitions
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from ..sdk.models import Span, SpanKind, SpanStatus, TokenUsage, Trace

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Security constants
# ---------------------------------------------------------------------------

# Maximum allowed length for string identifiers (trace_id, service_name, etc.)
_MAX_ID_LENGTH = 512
# Maximum number of spans per ingest request
_MAX_SPANS_PER_INGEST = 10_000
# Allowed characters for identifiers: alphanumeric, hyphens, underscores, dots, colons
_SAFE_ID_RE = re.compile(r"^[\w\-.:/ ]+$")
# Allowed base directories for the import endpoint (empty means disabled)
_ALLOWED_IMPORT_DIRS: list[Path] = []


def _sanitize_id(value: str, field_name: str = "identifier") -> str:
    """
    Validate a string ID for safety.

    - Enforces a maximum length to prevent oversized inputs.
    - Rejects values containing path-traversal sequences (../).
    - Does NOT restrict to a strict character whitelist so that legitimate
      Unicode service names remain accepted.

    Raises HTTPException(400) when the value fails validation.
    """
    if len(value) > _MAX_ID_LENGTH:
        raise HTTPException(
            400,
            f"Invalid {field_name}: exceeds maximum length of {_MAX_ID_LENGTH} characters",
        )
    if ".." in value or value.startswith("/") or "\x00" in value:
        raise HTTPException(400, f"Invalid {field_name}: contains disallowed sequences")
    return value


def _is_subpath(child: Path, parent: Path) -> bool:
    """Return True if *child* is the same as or inside *parent*."""
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _parse_tags(tags: Any) -> dict[str, Any]:
    """Safely parse tags field which may be a dict or JSON string."""
    if isinstance(tags, dict):
        return tags
    if isinstance(tags, str):
        try:
            return json.loads(tags)
        except Exception:
            return {}
    return {}


def _reconstruct_trace(trace_data: dict[str, Any]) -> Trace:
    """Rebuild a Trace domain object from a storage dict (used for analysis)."""
    trace = Trace(
        trace_id=trace_data["trace_id"],
        service_name=trace_data.get("service_name", ""),
        start_time=trace_data.get("start_time", 0),
        end_time=trace_data.get("end_time", 0),
    )

    for sd in trace_data.get("spans", []):
        span = Span(
            span_id=sd["span_id"],
            trace_id=sd["trace_id"],
            parent_span_id=sd.get("parent_span_id"),
            name=sd["name"],
            kind=SpanKind(sd["kind"]),
            status=SpanStatus(sd["status"]),
            start_time=sd.get("start_time", 0),
            end_time=sd.get("end_time", 0),
            attributes=sd.get("attributes", {}),
        )

        tu = sd.get("token_usage")
        if tu:
            span.token_usage = TokenUsage(
                input_tokens=tu.get("input_tokens", 0),
                output_tokens=tu.get("output_tokens", 0),
                total_tokens=tu.get("input_tokens", 0) + tu.get("output_tokens", 0),
                total_cost_usd=tu.get("total_cost_usd", 0),
            )

        err = sd.get("error")
        if isinstance(err, dict):
            span.error_message = err.get("message")
            span.error_type = err.get("type")

        trace.spans.append(span)

    return trace


# ---------------------------------------------------------------------------
# Built-in agent profile definitions
# ---------------------------------------------------------------------------

_AGENT_PROFILES: dict[str, dict[str, str]] = {
    "vr-alpha": {"name": "Alpha", "role": "Core Developer", "color": "#3b82f6", "icon": "shield"},
    "vr-beta": {"name": "Beta", "role": "Worker Engineer", "color": "#10b981", "icon": "gear"},
    "vr-gamma": {"name": "Gamma", "role": "Test & Monitor", "color": "#8b5cf6", "icon": "bolt"},
    "vr-lead": {"name": "Lead", "role": "Architect", "color": "#f59e0b", "icon": "crown"},
    "vr-scribe": {"name": "Scribe", "role": "Documentation", "color": "#6b7280", "icon": "book"},
    "main": {"name": "Main", "role": "Session", "color": "#6366f1", "icon": "terminal"},
    "Explore": {"name": "Explore", "role": "Explorer", "color": "#06b6d4", "icon": "search"},
}
