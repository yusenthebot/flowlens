"""
FlowLens Evaluation — Core evaluator base class and built-in evaluators.

Built-in evaluators:
    ExactMatch        — LLM output exactly equals expected string
    ContainsKeywords  — LLM output contains required keywords
    JsonSchemaValid   — LLM output parses as JSON and matches a JSON Schema
    CostThreshold     — Trace total cost is below a USD threshold
    LatencyThreshold  — Trace duration is below a millisecond threshold
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# EvalResult
# ---------------------------------------------------------------------------


@dataclass
class EvalResult:
    """The result of a single evaluator run against a span or trace.

    Attributes:
        score:     Normalised quality score in [0.0, 1.0].
                   1.0 = perfect pass, 0.0 = hard fail.
        label:     Short categorical outcome: "pass", "fail", or "partial".
        reason:    Human-readable explanation of the score.
        evaluator: Name of the evaluator that produced this result.
        metadata:  Optional extra data (e.g. matched keywords, diff snippet).
    """

    score: float
    label: str
    reason: str
    evaluator: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-compatible dictionary."""
        return {
            "score": self.score,
            "label": self.label,
            "reason": self.reason,
            "evaluator": self.evaluator,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvalResult:
        """Deserialise from a dictionary."""
        return cls(
            score=data["score"],
            label=data["label"],
            reason=data["reason"],
            evaluator=data["evaluator"],
            metadata=data.get("metadata", {}),
        )

    def __repr__(self) -> str:
        return (
            f"EvalResult(evaluator={self.evaluator!r}, label={self.label!r}, "
            f"score={self.score:.2f})"
        )


# ---------------------------------------------------------------------------
# Evaluator ABC
# ---------------------------------------------------------------------------


class Evaluator(ABC):
    """Abstract base class for all FlowLens evaluators.

    Subclasses must:
    - Set a class-level ``name`` string attribute.
    - Implement ``evaluate(span_data, trace_data) -> EvalResult``.

    The ``span_data`` dict represents a single span (may be empty ``{}`` when
    evaluating at the trace level).  The ``trace_data`` dict is the full trace
    as returned by the ingest API.
    """

    name: str = "evaluator"

    @abstractmethod
    def evaluate(self, span_data: dict[str, Any], trace_data: dict[str, Any]) -> EvalResult:
        """Evaluate a span or trace and return a scored result.

        Args:
            span_data:  A single span dict, or ``{}`` when evaluating the
                        trace as a whole.
            trace_data: The full trace dict (always provided).

        Returns:
            An :class:`EvalResult` with a score in [0.0, 1.0].
        """
        ...

    # ------------------------------------------------------------------
    # Helpers shared by subclasses
    # ------------------------------------------------------------------

    def _get_output(self, span_data: dict[str, Any], trace_data: dict[str, Any]) -> str:
        """Extract LLM output text from span or trace data.

        Looks for output in order:
        1. ``span_data["attributes"]["gen_ai.completion"]``
        2. ``span_data["output"]``
        3. ``trace_data["output"]``
        4. Empty string fallback.
        """
        # Try span attributes first (OpenTelemetry GenAI semantic conventions)
        attrs = span_data.get("attributes", {}) or {}
        if "gen_ai.completion" in attrs:
            completion = attrs["gen_ai.completion"]
            # May be a JSON list of message dicts or a raw string
            if isinstance(completion, list) and completion:
                first = completion[0]
                if isinstance(first, dict):
                    return str(first.get("text") or first.get("content") or "")
                return str(first)
            return str(completion)

        # Flat output key on span
        if "output" in span_data:
            return str(span_data["output"] or "")

        # Flat output key on trace
        if "output" in trace_data:
            return str(trace_data["output"] or "")

        return ""

    def _pass(self, reason: str, metadata: dict[str, Any] | None = None) -> EvalResult:
        """Convenience constructor for a passing result."""
        return EvalResult(
            score=1.0,
            label="pass",
            reason=reason,
            evaluator=self.name,
            metadata=metadata or {},
        )

    def _fail(self, reason: str, metadata: dict[str, Any] | None = None) -> EvalResult:
        """Convenience constructor for a failing result."""
        return EvalResult(
            score=0.0,
            label="fail",
            reason=reason,
            evaluator=self.name,
            metadata=metadata or {},
        )

    def _partial(
        self, score: float, reason: str, metadata: dict[str, Any] | None = None
    ) -> EvalResult:
        """Convenience constructor for a partial result."""
        return EvalResult(
            score=max(0.0, min(1.0, score)),
            label="partial",
            reason=reason,
            evaluator=self.name,
            metadata=metadata or {},
        )


# ---------------------------------------------------------------------------
# ExactMatch
# ---------------------------------------------------------------------------


class ExactMatch(Evaluator):
    """Pass when the LLM output exactly matches an expected string.

    Comparison is case-sensitive by default.  Leading/trailing whitespace is
    stripped from both sides before comparison.

    Args:
        expected:       The expected output string.
        strip:          Whether to strip surrounding whitespace (default True).
        case_sensitive: Whether the comparison is case-sensitive (default True).

    Example::

        ev = ExactMatch(expected="Paris")
        result = ev.evaluate(span_data, trace_data)
    """

    name = "exact_match"

    def __init__(
        self,
        expected: str,
        *,
        strip: bool = True,
        case_sensitive: bool = True,
    ) -> None:
        self.expected = expected
        self.strip = strip
        self.case_sensitive = case_sensitive

    def evaluate(self, span_data: dict[str, Any], trace_data: dict[str, Any]) -> EvalResult:
        output = self._get_output(span_data, trace_data)

        got = output.strip() if self.strip else output
        want = self.expected.strip() if self.strip else self.expected

        if not self.case_sensitive:
            got = got.lower()
            want = want.lower()

        if got == want:
            return self._pass(
                reason=f"Output exactly matches expected string ({len(want)} chars).",
                metadata={"expected": self.expected, "got": output},
            )

        # Provide a helpful truncated diff in the reason
        truncated_got = got[:120] + "..." if len(got) > 120 else got
        truncated_want = want[:120] + "..." if len(want) > 120 else want
        return self._fail(
            reason=(
                f"Output does not match expected. "
                f"Expected: {truncated_want!r}  Got: {truncated_got!r}"
            ),
            metadata={"expected": self.expected, "got": output},
        )


# ---------------------------------------------------------------------------
# ContainsKeywords
# ---------------------------------------------------------------------------


class ContainsKeywords(Evaluator):
    """Pass when the LLM output contains required keywords.

    Args:
        keywords:    List of strings that must appear in the output.
        require_all: When True (default), ALL keywords must be present for a
                     full pass.  When False, ANY match produces a full pass.
        case_sensitive: Whether matching is case-sensitive (default False —
                        keyword checks are usually case-insensitive).

    Scoring:
        - If ``require_all`` is True: score = matched / total keywords.
          A perfect score (1.0) requires every keyword to be present.
        - If ``require_all`` is False: score is 1.0 if any keyword matches,
          0.0 otherwise.

    Example::

        ev = ContainsKeywords(["Python", "asyncio"], require_all=True)
    """

    name = "contains_keywords"

    def __init__(
        self,
        keywords: list[str],
        require_all: bool = True,
        case_sensitive: bool = False,
    ) -> None:
        if not keywords:
            raise ValueError("ContainsKeywords requires at least one keyword.")
        self.keywords = keywords
        self.require_all = require_all
        self.case_sensitive = case_sensitive

    def evaluate(self, span_data: dict[str, Any], trace_data: dict[str, Any]) -> EvalResult:
        output = self._get_output(span_data, trace_data)

        haystack = output if self.case_sensitive else output.lower()
        found = []
        missing = []

        for kw in self.keywords:
            needle = kw if self.case_sensitive else kw.lower()
            if needle in haystack:
                found.append(kw)
            else:
                missing.append(kw)

        total = len(self.keywords)
        n_found = len(found)

        if self.require_all:
            score = n_found / total if total > 0 else 1.0
            if n_found == total:
                return self._pass(
                    reason=f"All {total} required keywords found: {found}.",
                    metadata={"found": found, "missing": []},
                )
            if n_found == 0:
                return self._fail(
                    reason=f"None of the required keywords were found. Missing: {missing}.",
                    metadata={"found": [], "missing": missing},
                )
            return self._partial(
                score=score,
                reason=(
                    f"{n_found}/{total} required keywords found. "
                    f"Found: {found}. Missing: {missing}."
                ),
                metadata={"found": found, "missing": missing},
            )
        else:
            # require_any
            if n_found > 0:
                return self._pass(
                    reason=f"At least one keyword found: {found}.",
                    metadata={"found": found, "missing": missing},
                )
            return self._fail(
                reason=f"None of the keywords were found in the output. Keywords: {self.keywords}.",
                metadata={"found": [], "missing": missing},
            )


# ---------------------------------------------------------------------------
# JsonSchemaValid
# ---------------------------------------------------------------------------


class JsonSchemaValid(Evaluator):
    """Pass when the LLM output is valid JSON matching a JSON Schema.

    Requires the ``jsonschema`` package at evaluation time.  If the package is
    not installed the evaluator returns a partial result (score=0.5) with an
    explanatory message rather than raising an ImportError at construction time.

    Args:
        schema: A JSON Schema dict to validate against.

    Example::

        ev = JsonSchemaValid(schema={
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        })
    """

    name = "json_schema"

    def __init__(self, schema: dict[str, Any]) -> None:
        if not isinstance(schema, dict):
            raise TypeError("schema must be a dict.")
        self.schema = schema

    def evaluate(self, span_data: dict[str, Any], trace_data: dict[str, Any]) -> EvalResult:
        output = self._get_output(span_data, trace_data)

        if not output.strip():
            return self._fail(
                reason="Output is empty — cannot validate against JSON schema.",
                metadata={"schema": self.schema},
            )

        # Step 1: Parse JSON
        try:
            parsed = json.loads(output)
        except json.JSONDecodeError as exc:
            return self._fail(
                reason=f"Output is not valid JSON: {exc}",
                metadata={"output_snippet": output[:200], "schema": self.schema},
            )

        # Step 2: Validate against schema (optional dependency)
        try:
            import jsonschema  # type: ignore[import-untyped]
        except ImportError:
            # jsonschema not installed — JSON parsed OK, schema check skipped
            return EvalResult(
                score=0.5,
                label="partial",
                reason=(
                    "Output is valid JSON but schema validation was skipped "
                    "because 'jsonschema' is not installed. "
                    "Install it with: pip install jsonschema"
                ),
                evaluator=self.name,
                metadata={"parsed": parsed},
            )

        try:
            jsonschema.validate(instance=parsed, schema=self.schema)
        except jsonschema.ValidationError as exc:
            return self._fail(
                reason=f"JSON schema validation failed: {exc.message}",
                metadata={
                    "schema": self.schema,
                    "validation_path": list(exc.absolute_path),
                    "output_snippet": output[:200],
                },
            )
        except jsonschema.SchemaError as exc:
            # The *schema itself* is invalid — that's a configuration error
            return self._fail(
                reason=f"Provided JSON schema is invalid: {exc.message}",
                metadata={"schema": self.schema},
            )

        return self._pass(
            reason="Output is valid JSON and matches the provided schema.",
            metadata={"schema": self.schema, "parsed": parsed},
        )


# ---------------------------------------------------------------------------
# CostThreshold
# ---------------------------------------------------------------------------


class CostThreshold(Evaluator):
    """Pass when the trace total cost is below a USD threshold.

    Args:
        max_cost_usd: Maximum allowed cost in US dollars (inclusive upper bound).

    Scoring:
        - Pass (1.0) when ``total_cost_usd <= max_cost_usd``.
        - Fail (0.0) otherwise.
        - If cost data is missing the evaluator returns a partial (0.5) with a
          warning rather than crashing.

    Example::

        ev = CostThreshold(max_cost_usd=0.10)
    """

    name = "cost_threshold"

    def __init__(self, max_cost_usd: float) -> None:
        if max_cost_usd < 0:
            raise ValueError("max_cost_usd must be >= 0.")
        self.max_cost_usd = max_cost_usd

    def evaluate(self, span_data: dict[str, Any], trace_data: dict[str, Any]) -> EvalResult:
        # Prefer the span-level cost when available (e.g. a single LLM call),
        # otherwise fall back to the full trace cost.
        cost: float | None = None

        span_cost = span_data.get("cost_usd") or span_data.get("attributes", {}).get(
            "gen_ai.usage.cost_usd"
        )
        if span_cost is not None:
            try:
                cost = float(span_cost)
            except (TypeError, ValueError):
                pass

        if cost is None:
            trace_cost = trace_data.get("total_cost_usd")
            if trace_cost is not None:
                try:
                    cost = float(trace_cost)
                except (TypeError, ValueError):
                    pass

        if cost is None:
            return EvalResult(
                score=0.5,
                label="partial",
                reason=(
                    "Cost data not found in span or trace — cannot evaluate cost threshold. "
                    "Ensure 'total_cost_usd' is populated on the trace."
                ),
                evaluator=self.name,
                metadata={"max_cost_usd": self.max_cost_usd},
            )

        if cost <= self.max_cost_usd:
            return self._pass(
                reason=(
                    f"Cost ${cost:.6f} is within the allowed threshold "
                    f"of ${self.max_cost_usd:.6f}."
                ),
                metadata={"cost_usd": cost, "max_cost_usd": self.max_cost_usd},
            )

        return self._fail(
            reason=(
                f"Cost ${cost:.6f} exceeds the allowed threshold "
                f"of ${self.max_cost_usd:.6f} "
                f"(overage: ${cost - self.max_cost_usd:.6f})."
            ),
            metadata={
                "cost_usd": cost,
                "max_cost_usd": self.max_cost_usd,
                "overage_usd": cost - self.max_cost_usd,
            },
        )


# ---------------------------------------------------------------------------
# LatencyThreshold
# ---------------------------------------------------------------------------


class LatencyThreshold(Evaluator):
    """Pass when the trace or span duration is below a millisecond threshold.

    Args:
        max_ms: Maximum allowed duration in milliseconds (inclusive upper bound).

    Scoring:
        - Pass (1.0) when ``duration_ms <= max_ms``.
        - Fail (0.0) otherwise.
        - If duration data is missing the evaluator returns a partial (0.5).

    Example::

        ev = LatencyThreshold(max_ms=5000)   # must complete in under 5 seconds
    """

    name = "latency_threshold"

    def __init__(self, max_ms: float) -> None:
        if max_ms < 0:
            raise ValueError("max_ms must be >= 0.")
        self.max_ms = max_ms

    def evaluate(self, span_data: dict[str, Any], trace_data: dict[str, Any]) -> EvalResult:
        duration: float | None = None

        # Prefer span-level duration
        span_dur = span_data.get("duration_ms")
        if span_dur is not None:
            try:
                duration = float(span_dur)
            except (TypeError, ValueError):
                pass

        if duration is None:
            trace_dur = trace_data.get("duration_ms")
            if trace_dur is not None:
                try:
                    duration = float(trace_dur)
                except (TypeError, ValueError):
                    pass

        if duration is None:
            return EvalResult(
                score=0.5,
                label="partial",
                reason=(
                    "Duration data not found in span or trace — cannot evaluate latency threshold. "
                    "Ensure 'duration_ms' is populated."
                ),
                evaluator=self.name,
                metadata={"max_ms": self.max_ms},
            )

        if duration <= self.max_ms:
            return self._pass(
                reason=(
                    f"Duration {duration:.1f} ms is within the allowed threshold "
                    f"of {self.max_ms:.1f} ms."
                ),
                metadata={"duration_ms": duration, "max_ms": self.max_ms},
            )

        return self._fail(
            reason=(
                f"Duration {duration:.1f} ms exceeds the allowed threshold "
                f"of {self.max_ms:.1f} ms "
                f"(overage: {duration - self.max_ms:.1f} ms)."
            ),
            metadata={
                "duration_ms": duration,
                "max_ms": self.max_ms,
                "overage_ms": duration - self.max_ms,
            },
        )


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------

__all__ = [
    "EvalResult",
    "Evaluator",
    "ExactMatch",
    "ContainsKeywords",
    "JsonSchemaValid",
    "CostThreshold",
    "LatencyThreshold",
]
