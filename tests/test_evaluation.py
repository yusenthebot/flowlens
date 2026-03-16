"""
Tests for the FlowLens Evaluation subsystem.

Covers:
- EvalResult dataclass (construction, to_dict, from_dict, repr)
- Evaluator ABC (abstract method enforcement)
- ExactMatch (pass, fail, case sensitivity, whitespace stripping)
- ContainsKeywords (require_all, require_any, case sensitivity, partial scoring)
- JsonSchemaValid (valid JSON, invalid JSON, schema mismatch, empty output)
- CostThreshold (pass, fail, missing data, span-level cost, edge cases)
- LatencyThreshold (pass, fail, missing data, span-level duration)
- LLMJudge (mock mode, custom call_fn, empty output, score normalisation)
- EvaluationRunner (run_on_trace, run_on_spans, run_batch, summary, errors)
- Top-level flowlens.__init__ exports
"""

from __future__ import annotations

import pytest

from flowlens.evaluation import (
    ContainsKeywords,
    CostThreshold,
    EvalResult,
    EvaluationRunner,
    Evaluator,
    ExactMatch,
    JsonSchemaValid,
    LatencyThreshold,
    LLMJudge,
)
from flowlens.evaluation.evaluators import (
    ContainsKeywords,
    CostThreshold,
    EvalResult,
    Evaluator,
    ExactMatch,
    JsonSchemaValid,
    LatencyThreshold,
)
from flowlens.evaluation.llm_judge import LLMJudge, _mock_score, _parse_judge_response
from flowlens.evaluation.runner import EvaluationRunner

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_trace(
    trace_id: str = "t-1",
    duration_ms: float = 1000.0,
    total_cost_usd: float = 0.05,
    output: str | None = None,
    spans: list | None = None,
) -> dict:
    t: dict = {
        "trace_id": trace_id,
        "service_name": "test-svc",
        "duration_ms": duration_ms,
        "total_cost_usd": total_cost_usd,
        "span_count": len(spans or []),
        "spans": spans or [],
    }
    if output is not None:
        t["output"] = output
    return t


def _make_span(
    span_id: str = "s-1",
    kind: str = "llm",
    name: str = "generate",
    output: str | None = None,
    duration_ms: float | None = None,
    cost_usd: float | None = None,
    attributes: dict | None = None,
) -> dict:
    s: dict = {
        "span_id": span_id,
        "kind": kind,
        "name": name,
        "attributes": attributes or {},
    }
    if output is not None:
        s["output"] = output
    if duration_ms is not None:
        s["duration_ms"] = duration_ms
    if cost_usd is not None:
        s["cost_usd"] = cost_usd
    return s


# ===========================================================================
# EvalResult
# ===========================================================================


class TestEvalResult:
    def test_construction(self):
        r = EvalResult(score=0.8, label="pass", reason="looks good", evaluator="test_ev")
        assert r.score == 0.8
        assert r.label == "pass"
        assert r.reason == "looks good"
        assert r.evaluator == "test_ev"
        assert r.metadata == {}

    def test_metadata_default_is_new_dict(self):
        r1 = EvalResult(score=1.0, label="pass", reason="ok", evaluator="ev")
        r2 = EvalResult(score=0.0, label="fail", reason="bad", evaluator="ev")
        r1.metadata["x"] = 1
        assert "x" not in r2.metadata

    def test_to_dict(self):
        r = EvalResult(
            score=0.5,
            label="partial",
            reason="halfway",
            evaluator="kw",
            metadata={"found": ["a"]},
        )
        d = r.to_dict()
        assert d["score"] == 0.5
        assert d["label"] == "partial"
        assert d["reason"] == "halfway"
        assert d["evaluator"] == "kw"
        assert d["metadata"] == {"found": ["a"]}

    def test_from_dict_roundtrip(self):
        original = EvalResult(
            score=1.0,
            label="pass",
            reason="perfect",
            evaluator="exact_match",
            metadata={"expected": "foo", "got": "foo"},
        )
        restored = EvalResult.from_dict(original.to_dict())
        assert restored.score == original.score
        assert restored.label == original.label
        assert restored.evaluator == original.evaluator
        assert restored.metadata == original.metadata

    def test_from_dict_missing_metadata_defaults(self):
        d = {"score": 0.0, "label": "fail", "reason": "nope", "evaluator": "ev"}
        r = EvalResult.from_dict(d)
        assert r.metadata == {}

    def test_repr(self):
        r = EvalResult(score=0.75, label="pass", reason="ok", evaluator="my_ev")
        assert "my_ev" in repr(r)
        assert "pass" in repr(r)
        assert "0.75" in repr(r)


# ===========================================================================
# Evaluator ABC
# ===========================================================================


class TestEvaluatorABC:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            Evaluator()  # type: ignore[abstract]

    def test_subclass_must_implement_evaluate(self):
        class Broken(Evaluator):
            name = "broken"

        with pytest.raises(TypeError):
            Broken()

    def test_valid_subclass(self):
        class AlwaysPass(Evaluator):
            name = "always_pass"

            def evaluate(self, span_data, trace_data) -> EvalResult:
                return self._pass("always passes")

        ev = AlwaysPass()
        result = ev.evaluate({}, {})
        assert result.label == "pass"
        assert result.score == 1.0
        assert result.evaluator == "always_pass"

    def test_helper_pass(self):
        class Ev(Evaluator):
            name = "ev"

            def evaluate(self, s, t):
                return self._pass("ok", {"k": "v"})

        r = Ev().evaluate({}, {})
        assert r.score == 1.0
        assert r.label == "pass"
        assert r.metadata == {"k": "v"}

    def test_helper_fail(self):
        class Ev(Evaluator):
            name = "ev"

            def evaluate(self, s, t):
                return self._fail("bad")

        r = Ev().evaluate({}, {})
        assert r.score == 0.0
        assert r.label == "fail"

    def test_helper_partial_clamps_score(self):
        class Ev(Evaluator):
            name = "ev"

            def evaluate(self, s, t):
                return self._partial(1.5, "over 1.0 should clamp")

        r = Ev().evaluate({}, {})
        assert r.score == 1.0

    def test_get_output_from_span_output_key(self):
        class Ev(Evaluator):
            name = "ev"

            def evaluate(self, s, t):
                return self._pass(self._get_output(s, t))

        span = {"output": "hello from span"}
        r = Ev().evaluate(span, {})
        assert "hello from span" in r.reason

    def test_get_output_from_trace_output_key(self):
        class Ev(Evaluator):
            name = "ev"

            def evaluate(self, s, t):
                return self._pass(self._get_output(s, t))

        r = Ev().evaluate({}, {"output": "hello from trace"})
        assert "hello from trace" in r.reason

    def test_get_output_from_gen_ai_completion_string(self):
        class Ev(Evaluator):
            name = "ev"

            def evaluate(self, s, t):
                return self._pass(self._get_output(s, t))

        span = {"attributes": {"gen_ai.completion": "llm said hi"}}
        r = Ev().evaluate(span, {})
        assert "llm said hi" in r.reason

    def test_get_output_from_gen_ai_completion_list(self):
        class Ev(Evaluator):
            name = "ev"

            def evaluate(self, s, t):
                return self._pass(self._get_output(s, t))

        span = {"attributes": {"gen_ai.completion": [{"text": "hi from list"}]}}
        r = Ev().evaluate(span, {})
        assert "hi from list" in r.reason

    def test_get_output_empty_fallback(self):
        class Ev(Evaluator):
            name = "ev"

            def evaluate(self, s, t):
                out = self._get_output(s, t)
                return self._pass(f"got:{out!r}")

        r = Ev().evaluate({}, {})
        assert "got:''" in r.reason


# ===========================================================================
# ExactMatch
# ===========================================================================


class TestExactMatch:
    def test_pass_on_exact_match(self):
        ev = ExactMatch(expected="Paris")
        r = ev.evaluate({"output": "Paris"}, {})
        assert r.label == "pass"
        assert r.score == 1.0

    def test_fail_on_mismatch(self):
        ev = ExactMatch(expected="Paris")
        r = ev.evaluate({"output": "London"}, {})
        assert r.label == "fail"
        assert r.score == 0.0

    def test_strip_whitespace_by_default(self):
        ev = ExactMatch(expected="Paris")
        r = ev.evaluate({"output": "  Paris  "}, {})
        assert r.label == "pass"

    def test_strip_disabled(self):
        ev = ExactMatch(expected="Paris", strip=False)
        r = ev.evaluate({"output": "  Paris  "}, {})
        assert r.label == "fail"

    def test_case_sensitive_by_default(self):
        ev = ExactMatch(expected="Paris")
        r = ev.evaluate({"output": "paris"}, {})
        assert r.label == "fail"

    def test_case_insensitive(self):
        ev = ExactMatch(expected="Paris", case_sensitive=False)
        r = ev.evaluate({"output": "paris"}, {})
        assert r.label == "pass"

    def test_empty_output_fails(self):
        ev = ExactMatch(expected="Paris")
        r = ev.evaluate({"output": ""}, {})
        assert r.label == "fail"

    def test_empty_expected_and_output(self):
        ev = ExactMatch(expected="")
        r = ev.evaluate({"output": ""}, {})
        assert r.label == "pass"

    def test_metadata_populated(self):
        ev = ExactMatch(expected="Paris")
        r = ev.evaluate({"output": "Lyon"}, {})
        assert r.metadata["expected"] == "Paris"
        assert r.metadata["got"] == "Lyon"

    def test_evaluator_name(self):
        ev = ExactMatch(expected="x")
        assert ev.name == "exact_match"
        r = ev.evaluate({"output": "x"}, {})
        assert r.evaluator == "exact_match"

    def test_long_output_truncated_in_reason(self):
        ev = ExactMatch(expected="short")
        long_output = "x" * 300
        r = ev.evaluate({"output": long_output}, {})
        assert "..." in r.reason

    def test_uses_trace_output_fallback(self):
        ev = ExactMatch(expected="TraceOutput")
        r = ev.evaluate({}, {"output": "TraceOutput"})
        assert r.label == "pass"


# ===========================================================================
# ContainsKeywords
# ===========================================================================


class TestContainsKeywords:
    def test_all_keywords_present(self):
        ev = ContainsKeywords(["Python", "async"])
        r = ev.evaluate({"output": "Python supports async programming"}, {})
        assert r.label == "pass"
        assert r.score == 1.0

    def test_some_keywords_missing_partial(self):
        ev = ContainsKeywords(["Python", "async", "MISSING"], require_all=True)
        r = ev.evaluate({"output": "Python supports async programming"}, {})
        assert r.label == "partial"
        assert r.score == pytest.approx(2 / 3)

    def test_no_keywords_found_fail(self):
        ev = ContainsKeywords(["Rust", "cargo"], require_all=True)
        r = ev.evaluate({"output": "Python supports async programming"}, {})
        assert r.label == "fail"
        assert r.score == 0.0

    def test_require_any_pass(self):
        ev = ContainsKeywords(["Rust", "Python"], require_all=False)
        r = ev.evaluate({"output": "Python is great"}, {})
        assert r.label == "pass"
        assert r.score == 1.0

    def test_require_any_fail(self):
        ev = ContainsKeywords(["Rust", "Go"], require_all=False)
        r = ev.evaluate({"output": "Python is great"}, {})
        assert r.label == "fail"

    def test_case_insensitive_by_default(self):
        ev = ContainsKeywords(["python"])
        r = ev.evaluate({"output": "PYTHON is cool"}, {})
        assert r.label == "pass"

    def test_case_sensitive_mode(self):
        ev = ContainsKeywords(["python"], case_sensitive=True)
        r = ev.evaluate({"output": "PYTHON is cool"}, {})
        assert r.label == "fail"

    def test_empty_keywords_raises(self):
        with pytest.raises(ValueError):
            ContainsKeywords([])

    def test_single_keyword_pass(self):
        ev = ContainsKeywords(["hello"])
        r = ev.evaluate({"output": "hello world"}, {})
        assert r.label == "pass"
        assert r.score == 1.0

    def test_metadata_found_and_missing(self):
        ev = ContainsKeywords(["found", "missing"])
        r = ev.evaluate({"output": "found it"}, {})
        assert "found" in r.metadata["found"]
        assert "missing" in r.metadata["missing"]

    def test_evaluator_name(self):
        ev = ContainsKeywords(["x"])
        assert ev.name == "contains_keywords"

    def test_uses_trace_output_fallback(self):
        ev = ContainsKeywords(["hello"])
        r = ev.evaluate({}, {"output": "hello world"})
        assert r.label == "pass"


# ===========================================================================
# JsonSchemaValid
# ===========================================================================


class TestJsonSchemaValid:
    _simple_schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
        "required": ["name"],
    }

    def test_valid_json_matching_schema(self):
        ev = JsonSchemaValid(schema=self._simple_schema)
        r = ev.evaluate({"output": '{"name": "Alice", "age": 30}'}, {})
        # May be "pass" if jsonschema installed, "partial" if not
        assert r.label in ("pass", "partial")
        assert r.score > 0.0

    def test_invalid_json_fails(self):
        ev = JsonSchemaValid(schema=self._simple_schema)
        r = ev.evaluate({"output": "not json at all"}, {})
        assert r.label == "fail"
        assert "not valid JSON" in r.reason

    def test_empty_output_fails(self):
        ev = JsonSchemaValid(schema=self._simple_schema)
        r = ev.evaluate({"output": ""}, {})
        assert r.label == "fail"
        assert "empty" in r.reason.lower()

    def test_schema_must_be_dict(self):
        with pytest.raises(TypeError):
            JsonSchemaValid(schema=[])  # type: ignore[arg-type]

    def test_evaluator_name(self):
        ev = JsonSchemaValid(schema={"type": "string"})
        assert ev.name == "json_schema"

    def test_json_valid_but_schema_mismatch(self):
        """Schema requires 'name' field but output lacks it."""
        ev = JsonSchemaValid(schema=self._simple_schema)
        try:
            import jsonschema  # noqa: F401

            r = ev.evaluate({"output": '{"age": 30}'}, {})
            assert r.label == "fail"
            assert "validation failed" in r.reason.lower()
        except ImportError:
            pytest.skip("jsonschema not installed")

    def test_string_schema(self):
        ev = JsonSchemaValid(schema={"type": "string"})
        try:
            import jsonschema  # noqa: F401

            r = ev.evaluate({"output": '"hello"'}, {})
            assert r.label == "pass"
        except ImportError:
            pytest.skip("jsonschema not installed")

    def test_uses_trace_output_fallback(self):
        ev = JsonSchemaValid(schema={"type": "string"})
        r = ev.evaluate({}, {"output": "not json"})
        assert r.label == "fail"


# ===========================================================================
# CostThreshold
# ===========================================================================


class TestCostThreshold:
    def test_pass_when_cost_below_threshold(self):
        ev = CostThreshold(max_cost_usd=0.10)
        r = ev.evaluate({}, _make_trace(total_cost_usd=0.05))
        assert r.label == "pass"
        assert r.score == 1.0

    def test_pass_when_cost_equals_threshold(self):
        ev = CostThreshold(max_cost_usd=0.10)
        r = ev.evaluate({}, _make_trace(total_cost_usd=0.10))
        assert r.label == "pass"

    def test_fail_when_cost_exceeds_threshold(self):
        ev = CostThreshold(max_cost_usd=0.10)
        r = ev.evaluate({}, _make_trace(total_cost_usd=0.20))
        assert r.label == "fail"
        assert r.score == 0.0

    def test_metadata_includes_overage(self):
        ev = CostThreshold(max_cost_usd=0.10)
        r = ev.evaluate({}, _make_trace(total_cost_usd=0.15))
        assert r.metadata["overage_usd"] == pytest.approx(0.05)

    def test_span_level_cost_takes_priority(self):
        ev = CostThreshold(max_cost_usd=0.10)
        span = _make_span(cost_usd=0.20)  # span cost exceeds threshold
        trace = _make_trace(total_cost_usd=0.01)  # trace cost is fine
        r = ev.evaluate(span, trace)
        assert r.label == "fail"

    def test_missing_cost_returns_partial(self):
        ev = CostThreshold(max_cost_usd=0.10)
        r = ev.evaluate({}, {"trace_id": "t"})  # no cost field
        assert r.label == "partial"
        assert r.score == 0.5

    def test_negative_max_cost_raises(self):
        with pytest.raises(ValueError):
            CostThreshold(max_cost_usd=-0.01)

    def test_zero_threshold_fails_any_cost(self):
        ev = CostThreshold(max_cost_usd=0.0)
        r = ev.evaluate({}, _make_trace(total_cost_usd=0.001))
        assert r.label == "fail"

    def test_zero_cost_zero_threshold_passes(self):
        ev = CostThreshold(max_cost_usd=0.0)
        r = ev.evaluate({}, _make_trace(total_cost_usd=0.0))
        assert r.label == "pass"

    def test_evaluator_name(self):
        ev = CostThreshold(max_cost_usd=1.0)
        assert ev.name == "cost_threshold"

    def test_span_gen_ai_attribute(self):
        ev = CostThreshold(max_cost_usd=0.10)
        span = {"attributes": {"gen_ai.usage.cost_usd": 0.20}}
        r = ev.evaluate(span, _make_trace(total_cost_usd=0.01))
        assert r.label == "fail"


# ===========================================================================
# LatencyThreshold
# ===========================================================================


class TestLatencyThreshold:
    def test_pass_when_under_threshold(self):
        ev = LatencyThreshold(max_ms=5000)
        r = ev.evaluate({}, _make_trace(duration_ms=3000))
        assert r.label == "pass"

    def test_pass_when_equal_threshold(self):
        ev = LatencyThreshold(max_ms=5000)
        r = ev.evaluate({}, _make_trace(duration_ms=5000))
        assert r.label == "pass"

    def test_fail_when_over_threshold(self):
        ev = LatencyThreshold(max_ms=5000)
        r = ev.evaluate({}, _make_trace(duration_ms=7000))
        assert r.label == "fail"

    def test_overage_in_metadata(self):
        ev = LatencyThreshold(max_ms=5000)
        r = ev.evaluate({}, _make_trace(duration_ms=7000))
        assert r.metadata["overage_ms"] == pytest.approx(2000)

    def test_span_level_duration_takes_priority(self):
        ev = LatencyThreshold(max_ms=5000)
        span = _make_span(duration_ms=9000)
        r = ev.evaluate(span, _make_trace(duration_ms=100))
        assert r.label == "fail"

    def test_missing_duration_returns_partial(self):
        ev = LatencyThreshold(max_ms=5000)
        r = ev.evaluate({}, {"trace_id": "t"})
        assert r.label == "partial"
        assert r.score == 0.5

    def test_negative_max_ms_raises(self):
        with pytest.raises(ValueError):
            LatencyThreshold(max_ms=-1)

    def test_evaluator_name(self):
        ev = LatencyThreshold(max_ms=1000)
        assert ev.name == "latency_threshold"

    def test_zero_threshold(self):
        ev = LatencyThreshold(max_ms=0)
        r = ev.evaluate({}, _make_trace(duration_ms=1))
        assert r.label == "fail"


# ===========================================================================
# LLMJudge — helpers
# ===========================================================================


class TestParseJudgeResponse:
    def test_parse_valid_response(self):
        raw = "SCORE: 4\nREASON: The answer is clear and accurate."
        score, reason = _parse_judge_response(raw, scale=5)
        assert score == 4
        assert "clear and accurate" in reason

    def test_parse_no_score(self):
        raw = "REASON: Good response."
        score, reason = _parse_judge_response(raw, scale=5)
        assert score is None

    def test_parse_score_clamped_to_scale(self):
        raw = "SCORE: 99\nREASON: Over the top."
        score, _ = _parse_judge_response(raw, scale=5)
        assert score == 5

    def test_parse_score_clamped_to_1(self):
        raw = "SCORE: 0\nREASON: Zero score."
        score, _ = _parse_judge_response(raw, scale=5)
        assert score == 1

    def test_parse_case_insensitive(self):
        raw = "score: 3\nreason: average"
        score, reason = _parse_judge_response(raw, scale=5)
        assert score == 3
        assert "average" in reason


class TestMockScore:
    def test_empty_output_scores_1(self):
        score, reason = _mock_score("", "Is this good?", 5)
        assert score == 1
        assert "empty" in reason.lower()

    def test_very_short_output_scores_low(self):
        score, reason = _mock_score("hi", "Is this good?", 5)
        assert score <= 3

    def test_deterministic(self):
        s1, _ = _mock_score("hello world this is a test", "quality accuracy", 5)
        s2, _ = _mock_score("hello world this is a test", "quality accuracy", 5)
        assert s1 == s2

    def test_score_in_range(self):
        for text in ["short answer", "a" * 50, "Python asyncio coroutine await"]:
            score, _ = _mock_score(text, "Is this about Python?", 5)
            assert 1 <= score <= 5

    def test_scale_10(self):
        score, _ = _mock_score("this is a great response to your question", "helpful", 10)
        assert 1 <= score <= 10


# ===========================================================================
# LLMJudge — evaluator
# ===========================================================================


class TestLLMJudge:
    def _make_judge(self, scale: int = 5, mock_score: int = 4) -> LLMJudge:
        """Build a LLMJudge with an injected call_fn returning a fixed score."""

        def _call_fn(output, criteria, model, scale):
            return mock_score, f"Mock: score={mock_score}"

        return LLMJudge(
            criteria="Is the response helpful and accurate?",
            model="claude-haiku-4",
            scale=scale,
            _call_fn=_call_fn,
        )

    def test_pass_on_high_score(self):
        judge = self._make_judge(scale=5, mock_score=5)
        r = judge.evaluate({"output": "Great answer"}, {})
        assert r.label == "pass"
        assert r.score == 1.0

    def test_fail_on_low_score(self):
        judge = self._make_judge(scale=5, mock_score=1)
        r = judge.evaluate({"output": "Bad answer"}, {})
        assert r.label == "fail"
        assert r.score == 0.0

    def test_partial_on_mid_score(self):
        judge = self._make_judge(scale=5, mock_score=3)
        r = judge.evaluate({"output": "Okay answer"}, {})
        # normalised = (3-1)/(5-1) = 0.5 → partial
        assert r.label == "partial"
        assert r.score == pytest.approx(0.5)

    def test_empty_output_fails(self):
        judge = self._make_judge()
        r = judge.evaluate({"output": ""}, {})
        assert r.label == "fail"
        assert "empty" in r.reason.lower()

    def test_evaluator_name(self):
        judge = self._make_judge()
        assert judge.name == "llm_judge"

    def test_result_evaluator_field(self):
        judge = self._make_judge()
        r = judge.evaluate({"output": "Some answer"}, {})
        assert r.evaluator == "llm_judge"

    def test_metadata_includes_criteria(self):
        judge = self._make_judge()
        r = judge.evaluate({"output": "Some answer"}, {})
        assert "criteria" in r.metadata
        assert "scale" in r.metadata
        assert "raw_score" in r.metadata

    def test_none_score_from_call_fn_returns_partial(self):
        def fail_fn(output, criteria, model, scale):
            return None, "API error"

        judge = LLMJudge(
            criteria="Is this good?",
            _call_fn=fail_fn,
        )
        r = judge.evaluate({"output": "answer"}, {})
        assert r.label == "partial"
        assert r.score == 0.5

    def test_criteria_empty_raises(self):
        with pytest.raises(ValueError):
            LLMJudge(criteria="")

    def test_scale_below_2_raises(self):
        with pytest.raises(ValueError):
            LLMJudge(criteria="x", scale=1)

    def test_scale_10(self):
        def fn(output, criteria, model, scale):
            return 7, "score 7"

        judge = LLMJudge(criteria="helpful", scale=10, _call_fn=fn)
        r = judge.evaluate({"output": "decent"}, {})
        # normalised = (7-1)/(10-1) = 6/9 ≈ 0.667 → pass
        assert r.score == pytest.approx(6 / 9, rel=1e-3)
        assert r.label == "pass"

    def test_mock_mode_deterministic(self):
        """Default mock mode produces consistent results without a call_fn."""
        judge = LLMJudge(criteria="Is this about Python?")
        output = "Python supports asyncio for concurrent programming."
        r1 = judge.evaluate({"output": output}, {})
        r2 = judge.evaluate({"output": output}, {})
        assert r1.score == r2.score
        assert r1.label == r2.label

    def test_uses_trace_output_fallback(self):
        def fn(output, criteria, model, scale):
            return 5, "great"

        judge = LLMJudge(criteria="good?", scale=5, _call_fn=fn)
        r = judge.evaluate({}, {"output": "trace level answer"})
        assert r.label == "pass"


# ===========================================================================
# EvaluationRunner
# ===========================================================================


class TestEvaluationRunner:
    def test_requires_at_least_one_evaluator(self):
        with pytest.raises(ValueError):
            EvaluationRunner(evaluators=[])

    def test_run_on_trace_returns_one_result_per_evaluator(self):
        runner = EvaluationRunner(
            evaluators=[
                CostThreshold(max_cost_usd=0.10),
                LatencyThreshold(max_ms=5000),
            ]
        )
        results = runner.run_on_trace(_make_trace(total_cost_usd=0.05, duration_ms=3000))
        assert len(results) == 2

    def test_run_on_trace_all_pass(self):
        runner = EvaluationRunner(
            evaluators=[
                CostThreshold(max_cost_usd=1.0),
                LatencyThreshold(max_ms=10000),
            ]
        )
        results = runner.run_on_trace(_make_trace())
        assert all(r.label == "pass" for r in results)

    def test_run_on_trace_handles_evaluator_exception(self):
        class BrokenEv(Evaluator):
            name = "broken"

            def evaluate(self, span_data, trace_data) -> EvalResult:
                raise RuntimeError("oops")

        runner = EvaluationRunner(evaluators=[BrokenEv()])
        results = runner.run_on_trace({})
        assert len(results) == 1
        assert results[0].label == "fail"
        assert "oops" in results[0].reason

    def test_run_on_spans_filters_by_kind(self):
        spans = [
            _make_span(span_id="s1", kind="llm", output="llm output"),
            _make_span(span_id="s2", kind="tool", output="tool output"),
            _make_span(span_id="s3", kind="llm", output="another llm"),
        ]
        trace = _make_trace(spans=spans)
        runner = EvaluationRunner(evaluators=[ContainsKeywords(["llm"])])
        results = runner.run_on_spans(trace, span_filter="llm")
        # 2 LLM spans × 1 evaluator = 2 results
        assert len(results) == 2

    def test_run_on_spans_empty_returns_empty_list(self):
        trace = _make_trace(spans=[])
        runner = EvaluationRunner(evaluators=[CostThreshold(max_cost_usd=1.0)])
        results = runner.run_on_spans(trace, span_filter="llm")
        assert results == []

    def test_run_on_spans_no_filter(self):
        spans = [
            _make_span(span_id="s1", kind="llm"),
            _make_span(span_id="s2", kind="tool"),
        ]
        trace = _make_trace(spans=spans)
        runner = EvaluationRunner(evaluators=[CostThreshold(max_cost_usd=1.0)])
        results = runner.run_on_spans(trace, span_filter="")
        # 2 spans × 1 evaluator
        assert len(results) == 2

    def test_run_batch_returns_dict_keyed_by_trace_id(self):
        runner = EvaluationRunner(evaluators=[CostThreshold(max_cost_usd=1.0)])
        traces = [
            _make_trace(trace_id="t1"),
            _make_trace(trace_id="t2"),
        ]
        result = runner.run_batch(traces)
        assert set(result.keys()) == {"t1", "t2"}
        assert len(result["t1"]) == 1
        assert len(result["t2"]) == 1

    def test_run_batch_fallback_to_index_when_no_trace_id(self):
        runner = EvaluationRunner(evaluators=[CostThreshold(max_cost_usd=1.0)])
        traces = [{"duration_ms": 500}, {"duration_ms": 300}]
        result = runner.run_batch(traces)
        assert "0" in result
        assert "1" in result

    def test_run_batch_empty_traces(self):
        runner = EvaluationRunner(evaluators=[CostThreshold(max_cost_usd=1.0)])
        result = runner.run_batch([])
        assert result == {}

    def test_span_filter_matches_by_name_substring(self):
        spans = [
            _make_span(span_id="s1", kind="agent", name="llm_call"),
            _make_span(span_id="s2", kind="agent", name="tool_invoke"),
        ]
        trace = _make_trace(spans=spans)
        runner = EvaluationRunner(evaluators=[CostThreshold(max_cost_usd=1.0)])
        results = runner.run_on_spans(trace, span_filter="llm")
        assert len(results) == 1  # only s1 matches

    def test_span_filter_matches_gen_ai_operation(self):
        spans = [
            {
                "span_id": "s1",
                "kind": "agent",
                "name": "unknown",
                "attributes": {"gen_ai.operation.name": "llm_generation"},
            }
        ]
        trace = _make_trace(spans=spans)
        runner = EvaluationRunner(evaluators=[CostThreshold(max_cost_usd=1.0)])
        results = runner.run_on_spans(trace, span_filter="llm")
        assert len(results) == 1


# ===========================================================================
# EvaluationRunner.summary
# ===========================================================================


class TestEvaluationRunnerSummary:
    def test_summary_all_pass(self):
        results = [
            EvalResult(score=1.0, label="pass", reason="ok", evaluator="ev"),
            EvalResult(score=1.0, label="pass", reason="ok", evaluator="ev"),
        ]
        s = EvaluationRunner.summary(results)
        assert s["total"] == 2
        assert s["passed"] == 2
        assert s["failed"] == 0
        assert s["partial"] == 0
        assert s["avg_score"] == 1.0
        assert s["pass_rate"] == 1.0

    def test_summary_mixed(self):
        results = [
            EvalResult(score=1.0, label="pass", reason="ok", evaluator="ev"),
            EvalResult(score=0.0, label="fail", reason="bad", evaluator="ev"),
            EvalResult(score=0.5, label="partial", reason="half", evaluator="ev"),
        ]
        s = EvaluationRunner.summary(results)
        assert s["total"] == 3
        assert s["passed"] == 1
        assert s["failed"] == 1
        assert s["partial"] == 1
        assert s["avg_score"] == pytest.approx(0.5)
        assert s["pass_rate"] == pytest.approx(1 / 3, abs=1e-4)

    def test_summary_empty(self):
        s = EvaluationRunner.summary([])
        assert s["total"] == 0
        assert s["avg_score"] == 0.0
        assert s["pass_rate"] == 0.0


# ===========================================================================
# Top-level flowlens package exports
# ===========================================================================


class TestFlowlensExports:
    def test_eval_result_importable(self):
        from flowlens import EvalResult as ER

        assert ER is EvalResult

    def test_evaluator_importable(self):
        from flowlens import Evaluator as Ev

        assert Ev is Evaluator

    def test_exact_match_importable(self):
        from flowlens import ExactMatch as EM

        assert EM is ExactMatch

    def test_contains_keywords_importable(self):
        from flowlens import ContainsKeywords as CK

        assert CK is ContainsKeywords

    def test_json_schema_valid_importable(self):
        from flowlens import JsonSchemaValid as JSV

        assert JSV is JsonSchemaValid

    def test_cost_threshold_importable(self):
        from flowlens import CostThreshold as CT

        assert CT is CostThreshold

    def test_latency_threshold_importable(self):
        from flowlens import LatencyThreshold as LT

        assert LT is LatencyThreshold

    def test_llm_judge_importable(self):
        from flowlens import LLMJudge as LJ

        assert LJ is LLMJudge

    def test_evaluation_runner_importable(self):
        from flowlens import EvaluationRunner as ER

        assert ER is EvaluationRunner
