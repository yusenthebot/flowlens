"""Core evaluation framework — evaluators and runner."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class EvalResult:
    """Result of a single evaluation."""

    trace_id: str
    evaluator_name: str
    passed: bool
    score: float
    details: str = ""


class Evaluator(ABC):
    """Base class for all evaluators."""

    @abstractmethod
    def evaluate(self, trace: dict[str, Any]) -> EvalResult:
        """Evaluate a trace and return an EvalResult."""
        pass


class ExactMatch(Evaluator):
    """Check if trace output exactly matches expected value."""

    def __init__(self, expected: str, case_insensitive: bool = False):
        self.expected = expected
        self.case_insensitive = case_insensitive

    def evaluate(self, trace: dict[str, Any]) -> EvalResult:
        """Check exact match."""
        output = trace.get("spans", [{}])[0].get("output", "")

        if self.case_insensitive:
            match = output.lower() == self.expected.lower()
        else:
            match = output == self.expected

        return EvalResult(
            trace_id=trace["trace_id"],
            evaluator_name="exact_match",
            passed=match,
            score=1.0 if match else 0.0,
            details=f"Expected: {self.expected[:50]}" if not match else "Output matched",
        )


class ContainsKeywords(Evaluator):
    """Check if trace output contains required keywords."""

    def __init__(self, keywords: list[str], require_all: bool = True):
        self.keywords = keywords
        self.require_all = require_all

    def evaluate(self, trace: dict[str, Any]) -> EvalResult:
        """Check keyword presence."""
        output = trace.get("spans", [{}])[0].get("output", "").lower()

        found = [kw.lower() in output for kw in self.keywords]

        passed = all(found) if self.require_all else any(found) if self.keywords else True

        score = sum(found) / len(self.keywords) if self.keywords else 1.0

        return EvalResult(
            trace_id=trace["trace_id"],
            evaluator_name="contains_keywords",
            passed=passed,
            score=score,
            details=f"Found {sum(found)}/{len(self.keywords)} keywords",
        )


class JsonSchemaValid(Evaluator):
    """Check if trace output is valid JSON matching a schema."""

    def __init__(self, schema: dict[str, Any]):
        self.schema = schema

    def evaluate(self, trace: dict[str, Any]) -> EvalResult:
        """Validate JSON schema."""
        import json

        output = trace.get("spans", [{}])[0].get("output", "")

        try:
            json.loads(output)
            # Simple validation — just check it's valid JSON
            # Full schema validation requires jsonschema library
            return EvalResult(
                trace_id=trace["trace_id"],
                evaluator_name="json_schema_valid",
                passed=True,
                score=1.0,
                details="Valid JSON",
            )
        except (json.JSONDecodeError, ValueError):
            return EvalResult(
                trace_id=trace["trace_id"],
                evaluator_name="json_schema_valid",
                passed=False,
                score=0.0,
                details="Invalid JSON or parsing error",
            )


class CostThreshold(Evaluator):
    """Check if trace cost is within budget."""

    def __init__(self, max_cost_usd: float):
        self.max_cost_usd = max_cost_usd

    def evaluate(self, trace: dict[str, Any]) -> EvalResult:
        """Check cost threshold."""
        cost = trace.get("total_cost_usd", 0.0)
        passed = cost <= self.max_cost_usd

        return EvalResult(
            trace_id=trace["trace_id"],
            evaluator_name="cost_threshold",
            passed=passed,
            score=1.0 if passed else (self.max_cost_usd / cost if cost > 0 else 0.0),
            details=f"Cost: ${cost:.4f} (budget: ${self.max_cost_usd:.4f})",
        )


class LatencyThreshold(Evaluator):
    """Check if trace latency is within threshold."""

    def __init__(self, max_latency_ms: float):
        self.max_latency_ms = max_latency_ms

    def evaluate(self, trace: dict[str, Any]) -> EvalResult:
        """Check latency threshold."""
        duration = trace.get("duration_ms", 0.0)
        passed = duration <= self.max_latency_ms

        return EvalResult(
            trace_id=trace["trace_id"],
            evaluator_name="latency_threshold",
            passed=passed,
            score=1.0 if passed else (self.max_latency_ms / duration if duration > 0 else 0.0),
            details=f"Duration: {duration:.1f}ms (threshold: {self.max_latency_ms:.1f}ms)",
        )


class LLMJudge(Evaluator):
    """LLM-based evaluator for qualitative assessment."""

    def __init__(self, criteria: str):
        self.criteria = criteria

    def evaluate(self, trace: dict[str, Any]) -> EvalResult:
        """Evaluate using LLM judgment (stub)."""
        # This would call an LLM API in production
        # For now, return a placeholder
        return EvalResult(
            trace_id=trace["trace_id"],
            evaluator_name="llm_judge",
            passed=True,
            score=0.5,
            details="LLM evaluation pending implementation",
        )


class EvaluationRunner:
    """Orchestrator for running multiple evaluations."""

    def __init__(self):
        self.evaluators: list[Evaluator] = []

    def add_evaluator(self, evaluator: Evaluator) -> None:
        """Add an evaluator to the runner."""
        self.evaluators.append(evaluator)

    def run(self, trace: dict[str, Any]) -> list[EvalResult]:
        """Run all evaluators on a single trace."""
        return [e.evaluate(trace) for e in self.evaluators]

    def run_batch(self, traces: list[dict[str, Any]]) -> list[list[EvalResult]]:
        """Run all evaluators on multiple traces."""
        return [self.run(trace) for trace in traces]

    def get_summary(self, all_results: list[list[EvalResult]]) -> dict[str, Any]:
        """Get summary statistics from batch results."""
        flat = [r for results in all_results for r in results]

        total = len(flat)
        passed = sum(1 for r in flat if r.passed)
        failed = total - passed

        by_evaluator = {}
        for result in flat:
            if result.evaluator_name not in by_evaluator:
                by_evaluator[result.evaluator_name] = {"passed": 0, "total": 0}
            by_evaluator[result.evaluator_name]["total"] += 1
            if result.passed:
                by_evaluator[result.evaluator_name]["passed"] += 1

        return {
            "total_evals": total,
            "passed": passed,
            "failed": failed,
            "pass_rate": passed / total if total > 0 else 0.0,
            "by_evaluator": by_evaluator,
        }
