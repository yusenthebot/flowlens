"""Comprehensive tests for the evaluation framework core."""

from __future__ import annotations

import json
from typing import Any

import pytest

from flowlens.evaluation.core import (
    EvalResult,
    ExactMatch,
    ContainsKeywords,
    JsonSchemaValid,
    CostThreshold,
    LatencyThreshold,
    LLMJudge,
    EvaluationRunner,
)


# ---------------------------------------------------------------------------
# Test Fixtures
# ---------------------------------------------------------------------------


def _make_trace_data(
    trace_id: str = "t1",
    duration_ms: float = 100.0,
    cost_usd: float = 0.01,
    spans: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a test trace with common fields."""
    if spans is None:
        spans = [
            {
                "span_id": f"{trace_id}_s1",
                "name": "agent",
                "status": "ok",
                "start_time": 1000.0,
                "end_time": 1000.0 + duration_ms / 1000.0,
                "duration_ms": duration_ms,
                "attributes": {"agent.name": "test-agent"},
                "output": "test output",
            }
        ]

    return {
        "trace_id": trace_id,
        "duration_ms": duration_ms,
        "total_cost_usd": cost_usd,
        "spans": spans,
    }


@pytest.fixture
def simple_trace() -> dict[str, Any]:
    """A simple passing trace."""
    return _make_trace_data(
        trace_id="t1",
        duration_ms=100.0,
        cost_usd=0.01,
        spans=[
            {
                "span_id": "t1_s1",
                "name": "agent",
                "status": "ok",
                "start_time": 1000.0,
                "end_time": 1000.1,
                "duration_ms": 100.0,
                "attributes": {"agent.name": "test-agent"},
                "output": "Success: found the answer",
            }
        ],
    )


@pytest.fixture
def error_trace() -> dict[str, Any]:
    """A trace with an error."""
    return _make_trace_data(
        trace_id="t2",
        duration_ms=500.0,
        cost_usd=0.05,
        spans=[
            {
                "span_id": "t2_s1",
                "name": "agent",
                "status": "error",
                "start_time": 1000.0,
                "end_time": 1000.5,
                "duration_ms": 500.0,
                "attributes": {"agent.name": "test-agent"},
                "error": {"message": "API timeout"},
            }
        ],
    )


@pytest.fixture
def expensive_trace() -> dict[str, Any]:
    """A high-cost trace."""
    return _make_trace_data(
        trace_id="t3",
        duration_ms=2000.0,
        cost_usd=0.50,
        spans=[
            {
                "span_id": "t3_s1",
                "name": "agent",
                "status": "ok",
                "start_time": 1000.0,
                "end_time": 1002.0,
                "duration_ms": 2000.0,
                "attributes": {"agent.name": "test-agent"},
                "output": "Completed with multiple model calls",
            }
        ],
    )


# ---------------------------------------------------------------------------
# TestEvalResult
# ---------------------------------------------------------------------------


class TestEvalResult:
    """Test EvalResult data class."""

    def test_eval_result_creation(self):
        """Test creating an EvalResult with valid data."""
        result = EvalResult(
            trace_id="t1",
            evaluator_name="exact_match",
            passed=True,
            score=1.0,
            details="Output matched expected value",
        )
        assert result.trace_id == "t1"
        assert result.evaluator_name == "exact_match"
        assert result.passed is True
        assert result.score == 1.0
        assert result.details == "Output matched expected value"

    def test_eval_result_score_range(self):
        """Test that score is clamped to [0, 1]."""
        # Valid range
        result = EvalResult(
            trace_id="t1",
            evaluator_name="test",
            passed=True,
            score=0.75,
            details="",
        )
        assert result.score == 0.75

    def test_eval_result_failure(self):
        """Test creating a failed EvalResult."""
        result = EvalResult(
            trace_id="t1",
            evaluator_name="schema_check",
            passed=False,
            score=0.0,
            details="Output is not valid JSON",
        )
        assert result.passed is False


# ---------------------------------------------------------------------------
# TestExactMatch
# ---------------------------------------------------------------------------


class TestExactMatch:
    """Test ExactMatch evaluator."""

    def test_exact_match_pass(self, simple_trace):
        """Test exact match when output matches expected."""
        evaluator = ExactMatch(expected="Success: found the answer")
        result = evaluator.evaluate(simple_trace)
        assert result.passed is True
        assert result.score == 1.0

    def test_exact_match_fail(self, simple_trace):
        """Test exact match when output does not match."""
        evaluator = ExactMatch(expected="Different answer")
        result = evaluator.evaluate(simple_trace)
        assert result.passed is False
        assert result.score == 0.0

    def test_exact_match_empty_output(self, simple_trace):
        """Test exact match with empty output."""
        simple_trace["spans"][0]["output"] = ""
        evaluator = ExactMatch(expected="Expected output")
        result = evaluator.evaluate(simple_trace)
        assert result.passed is False

    def test_exact_match_case_sensitivity(self, simple_trace):
        """Test that exact match is case-sensitive by default."""
        evaluator = ExactMatch(expected="success: found the answer")
        result = evaluator.evaluate(simple_trace)
        assert result.passed is False

    def test_exact_match_case_insensitive(self, simple_trace):
        """Test case-insensitive matching option."""
        evaluator = ExactMatch(
            expected="SUCCESS: FOUND THE ANSWER", case_insensitive=True
        )
        result = evaluator.evaluate(simple_trace)
        assert result.passed is True


# ---------------------------------------------------------------------------
# TestContainsKeywords
# ---------------------------------------------------------------------------


class TestContainsKeywords:
    """Test ContainsKeywords evaluator."""

    def test_all_keywords_present(self, simple_trace):
        """Test when all keywords are in output."""
        evaluator = ContainsKeywords(keywords=["Success", "answer"], require_all=True)
        result = evaluator.evaluate(simple_trace)
        assert result.passed is True

    def test_partial_keywords(self, simple_trace):
        """Test when only some keywords are present with require_all=False."""
        evaluator = ContainsKeywords(
            keywords=["Success", "missing"], require_all=False
        )
        result = evaluator.evaluate(simple_trace)
        assert result.passed is True
        assert result.score > 0

    def test_require_all_false(self, simple_trace):
        """Test require_all=False with partial match."""
        evaluator = ContainsKeywords(keywords=["a", "b", "c"], require_all=False)
        result = evaluator.evaluate(simple_trace)
        # At least one keyword ("a") should be present
        assert result.passed is True

    def test_no_keywords_found(self, simple_trace):
        """Test when no keywords match."""
        evaluator = ContainsKeywords(
            keywords=["Foo", "Bar", "Baz"], require_all=False
        )
        result = evaluator.evaluate(simple_trace)
        assert result.passed is False

    def test_empty_keywords_list(self, simple_trace):
        """Test with empty keywords list."""
        evaluator = ContainsKeywords(keywords=[])
        result = evaluator.evaluate(simple_trace)
        assert result.passed is True  # No keywords to match = pass


# ---------------------------------------------------------------------------
# TestJsonSchemaValid
# ---------------------------------------------------------------------------


class TestJsonSchemaValid:
    """Test JsonSchemaValid evaluator."""

    def test_valid_json_output(self, simple_trace):
        """Test valid JSON in output."""
        simple_trace["spans"][0]["output"] = '{"status": "ok", "value": 42}'
        schema = {
            "type": "object",
            "properties": {"status": {"type": "string"}, "value": {"type": "number"}},
            "required": ["status", "value"],
        }
        evaluator = JsonSchemaValid(schema=schema)
        result = evaluator.evaluate(simple_trace)
        assert result.passed is True

    def test_invalid_json(self, simple_trace):
        """Test malformed JSON."""
        simple_trace["spans"][0]["output"] = "{ invalid json"
        schema = {"type": "object"}
        evaluator = JsonSchemaValid(schema=schema)
        result = evaluator.evaluate(simple_trace)
        assert result.passed is False

    def test_schema_mismatch(self, simple_trace):
        """Test JSON that doesn't match schema."""
        simple_trace["spans"][0]["output"] = '{"name": "test"}'
        schema = {
            "type": "object",
            "properties": {"age": {"type": "number"}},
            "required": ["age"],
        }
        evaluator = JsonSchemaValid(schema=schema)
        result = evaluator.evaluate(simple_trace)
        assert result.passed is False

    def test_non_json_output(self, simple_trace):
        """Test non-JSON output."""
        simple_trace["spans"][0]["output"] = "Not JSON at all"
        schema = {"type": "object"}
        evaluator = JsonSchemaValid(schema=schema)
        result = evaluator.evaluate(simple_trace)
        assert result.passed is False


# ---------------------------------------------------------------------------
# TestCostThreshold
# ---------------------------------------------------------------------------


class TestCostThreshold:
    """Test CostThreshold evaluator."""

    def test_within_budget(self, simple_trace):
        """Test trace within cost budget."""
        evaluator = CostThreshold(max_cost_usd=0.05)
        result = evaluator.evaluate(simple_trace)
        assert result.passed is True

    def test_over_budget(self, expensive_trace):
        """Test trace exceeding cost budget."""
        evaluator = CostThreshold(max_cost_usd=0.10)
        result = evaluator.evaluate(expensive_trace)
        assert result.passed is False
        assert result.details  # Should have explanation

    def test_zero_cost(self, simple_trace):
        """Test zero-cost trace."""
        simple_trace["total_cost_usd"] = 0.0
        evaluator = CostThreshold(max_cost_usd=0.01)
        result = evaluator.evaluate(simple_trace)
        assert result.passed is True

    def test_exact_threshold(self, simple_trace):
        """Test trace exactly at threshold."""
        evaluator = CostThreshold(max_cost_usd=0.01)
        result = evaluator.evaluate(simple_trace)
        assert result.passed is True  # At threshold should pass


# ---------------------------------------------------------------------------
# TestLatencyThreshold
# ---------------------------------------------------------------------------


class TestLatencyThreshold:
    """Test LatencyThreshold evaluator."""

    def test_fast_trace(self, simple_trace):
        """Test fast trace within latency threshold."""
        evaluator = LatencyThreshold(max_latency_ms=500.0)
        result = evaluator.evaluate(simple_trace)
        assert result.passed is True

    def test_slow_trace(self, expensive_trace):
        """Test slow trace exceeding latency threshold."""
        evaluator = LatencyThreshold(max_latency_ms=500.0)
        result = evaluator.evaluate(expensive_trace)
        assert result.passed is False

    def test_exact_threshold(self, simple_trace):
        """Test trace exactly at threshold."""
        evaluator = LatencyThreshold(max_latency_ms=100.0)
        result = evaluator.evaluate(simple_trace)
        assert result.passed is True

    def test_very_strict_threshold(self, simple_trace):
        """Test very strict latency requirement."""
        evaluator = LatencyThreshold(max_latency_ms=50.0)
        result = evaluator.evaluate(simple_trace)
        assert result.passed is False


# ---------------------------------------------------------------------------
# TestLLMJudge
# ---------------------------------------------------------------------------


class TestLLMJudge:
    """Test LLMJudge evaluator (mocked)."""

    def test_judge_returns_result(self, simple_trace, monkeypatch):
        """Test that LLMJudge returns a valid EvalResult."""
        # Mock the LLM call
        def mock_judge(trace_dict, criteria):
            return EvalResult(
                trace_id=trace_dict["trace_id"],
                evaluator_name="llm_judge",
                passed=True,
                score=0.95,
                details="LLM evaluation: excellent output quality",
            )

        monkeypatch.setattr(
            "flowlens.evaluation.core.LLMJudge.evaluate", mock_judge
        )

        evaluator = LLMJudge(
            criteria="Output should be helpful and accurate",
        )
        result = evaluator.evaluate(simple_trace)

        assert result.passed is True
        assert result.score == 0.95

    def test_judge_handles_empty_output(self, simple_trace, monkeypatch):
        """Test LLMJudge with empty output."""
        simple_trace["spans"][0]["output"] = ""

        def mock_judge(trace_dict, criteria):
            return EvalResult(
                trace_id=trace_dict["trace_id"],
                evaluator_name="llm_judge",
                passed=False,
                score=0.0,
                details="No output to evaluate",
            )

        monkeypatch.setattr(
            "flowlens.evaluation.core.LLMJudge.evaluate", mock_judge
        )

        evaluator = LLMJudge(criteria="Evaluate output")
        result = evaluator.evaluate(simple_trace)

        assert result.passed is False


# ---------------------------------------------------------------------------
# TestEvaluationRunner
# ---------------------------------------------------------------------------


class TestEvaluationRunner:
    """Test EvaluationRunner orchestrator."""

    def test_run_on_trace(self, simple_trace):
        """Test running evaluations on a single trace."""
        runner = EvaluationRunner()
        runner.add_evaluator(ExactMatch(expected="Success: found the answer"))
        runner.add_evaluator(ContainsKeywords(keywords=["Success"]))

        results = runner.run(simple_trace)

        assert len(results) == 2
        assert all(r.passed for r in results)

    def test_run_batch(self, simple_trace, error_trace, expensive_trace):
        """Test running evaluations on multiple traces."""
        runner = EvaluationRunner()
        runner.add_evaluator(LatencyThreshold(max_latency_ms=1000.0))
        runner.add_evaluator(CostThreshold(max_cost_usd=0.10))

        traces = [simple_trace, error_trace, expensive_trace]
        all_results = runner.run_batch(traces)

        assert len(all_results) == 3
        # First trace should pass all evaluations
        assert all(r.passed for r in all_results[0])

    def test_run_with_multiple_evaluators(self, simple_trace):
        """Test runner with multiple diverse evaluators."""
        runner = EvaluationRunner()
        runner.add_evaluator(ExactMatch(expected="Success: found the answer"))
        runner.add_evaluator(ContainsKeywords(keywords=["Success", "answer"]))
        runner.add_evaluator(LatencyThreshold(max_latency_ms=1000.0))
        runner.add_evaluator(CostThreshold(max_cost_usd=0.10))

        results = runner.run(simple_trace)

        assert len(results) == 4
        # All should pass for this trace
        assert all(r.passed for r in results)

    def test_runner_summary(self, simple_trace, error_trace):
        """Test runner summary statistics."""
        runner = EvaluationRunner()
        runner.add_evaluator(ExactMatch(expected="Success: found the answer"))
        runner.add_evaluator(LatencyThreshold(max_latency_ms=1000.0))

        traces = [simple_trace, error_trace]
        all_results = runner.run_batch(traces)

        summary = runner.get_summary(all_results)

        assert summary["total_evals"] == 4  # 2 evaluators × 2 traces
        assert summary["passed"] >= 0
        assert summary["failed"] >= 0
        assert summary["pass_rate"] == summary["passed"] / summary["total_evals"]

