"""Tests for SmartAdvisor — fleet analysis, regression detection, pipeline reorder."""

from __future__ import annotations

import time

from flowlens.analysis.smart_advisor import SmartAdvisor
from flowlens.sdk.models import Span, SpanKind, SpanStatus, TokenUsage, Trace

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _span(
    name: str,
    duration_ms: float = 100.0,
    kind: SpanKind = SpanKind.TOOL,
    status: SpanStatus = SpanStatus.OK,
    error_msg: str | None = None,
    tokens: int = 0,
    cost: float = 0.0,
    model: str = "",
) -> Span:
    now = time.time()
    s = Span(
        name=name,
        kind=kind,
        status=status,
        start_time=now,
        end_time=now + duration_ms / 1000.0,
    )
    if error_msg:
        s.error_message = error_msg
        s.status = SpanStatus.ERROR
    if tokens or cost:
        s.token_usage = TokenUsage(
            input_tokens=tokens,
            output_tokens=max(1, tokens // 10),
            total_tokens=tokens + max(1, tokens // 10),
            total_cost_usd=cost,
        )
    if model:
        s.attributes["gen_ai.request.model"] = model
    return s


def _trace(
    trace_id: str,
    *spans: Span,
    service: str = "svc",
    has_errors: bool = False,
    start_offset_secs: float = 0.0,
) -> Trace:
    now = time.time() - start_offset_secs
    t = Trace(trace_id=trace_id, service_name=service)
    t.start_time = now
    t.end_time = now + sum(s.duration_ms for s in spans) / 1000.0
    for s in spans:
        s.trace_id = trace_id
    t.spans = list(spans)
    return t


# ---------------------------------------------------------------------------
# Fleet analysis
# ---------------------------------------------------------------------------


class TestFleetAnalysis:
    def test_empty_traces_returns_safe_response(self):
        advisor = SmartAdvisor()
        result = advisor.analyze_fleet([])
        assert "recommendations" in result
        assert "summary" in result
        assert result["recommendations"] == []

    def test_top_expensive_spans_identified(self):
        """The most costly span should appear in top_expensive_spans."""
        cheap = _span("cheap_tool", cost=0.001)
        expensive = _span("expensive_llm", tokens=10000, cost=0.50)

        traces = [
            _trace("t1", cheap, expensive),
            _trace("t2", cheap, expensive),
        ]
        advisor = SmartAdvisor()
        result = advisor.analyze_fleet(traces)

        top = result["top_expensive_spans"]
        assert len(top) > 0
        top_names = [s["name"] for s in top]
        assert "expensive_llm" in top_names

    def test_most_common_failure_detected(self):
        """Recurring error message is identified as most common failure."""
        err_span = _span("api_call", error_msg="connection refused")
        ok_span = _span("agent")

        traces = [
            _trace("t1", _span("api_call", error_msg="connection refused")),
            _trace("t2", _span("api_call", error_msg="connection refused")),
            _trace("t3", ok_span),
        ]
        advisor = SmartAdvisor()
        result = advisor.analyze_fleet(traces)

        failure = result["most_common_failure"]
        assert failure is not None
        assert "connection refused" in failure["error_message"]
        assert failure["affected_traces"] >= 2

    def test_no_failures_returns_none_for_most_common_failure(self):
        traces = [_trace("t1", _span("ok"))]
        advisor = SmartAdvisor()
        result = advisor.analyze_fleet(traces)
        assert result["most_common_failure"] is None

    def test_recommendations_are_dicts_with_required_fields(self):
        s = _span("llm", cost=0.10)
        traces = [_trace("t1", s)]
        result = SmartAdvisor().analyze_fleet(traces)

        for rec in result["recommendations"]:
            assert "category" in rec
            assert "title" in rec
            assert "description" in rec
            assert "severity" in rec
            assert "estimated_savings_usd" in rec

    def test_model_downgrade_suggestion_for_opus_low_output(self):
        """
        Spans using an 'opus' model with very low output/input ratio should
        trigger a model downgrade recommendation.
        """
        s = _span("opus_call", model="claude-opus-4", tokens=10000, cost=0.15)
        # Manually set low output tokens
        s.token_usage.output_tokens = 50  # ratio = 50/10000 = 0.005
        s.token_usage.total_tokens = 10050

        traces = [_trace("t1", s), _trace("t2", s)]
        result = SmartAdvisor().analyze_fleet(traces)

        recs = result["recommendations"]
        model_recs = [r for r in recs if r["category"] == "model"]
        assert len(model_recs) >= 1
        assert any("opus" in r["title"].lower() for r in model_recs)

    def test_summary_string_non_empty(self):
        s = _span("x", cost=0.05)
        result = SmartAdvisor().analyze_fleet([_trace("t1", s)])
        assert isinstance(result["summary"], str)
        assert len(result["summary"]) > 0


# ---------------------------------------------------------------------------
# Regression detection
# ---------------------------------------------------------------------------


class TestRegressionDetection:
    def _make_traces(
        self,
        n: int,
        error_fraction: float = 0.0,
        duration_ms: float = 200.0,
        cost: float = 0.01,
        start_offset_secs: float = 0.0,
    ) -> list[Trace]:
        n_err = int(n * error_fraction)
        traces = []
        for i in range(n):
            err_msg = "failure" if i < n_err else None
            s = _span("work", duration_ms=duration_ms, cost=cost, error_msg=err_msg)
            t = _trace(f"t-{i}", s, start_offset_secs=start_offset_secs)
            traces.append(t)
        return traces

    def test_error_rate_regression_flagged(self):
        baseline = self._make_traces(20, error_fraction=0.05)
        recent = self._make_traces(10, error_fraction=0.50)

        reports = SmartAdvisor().detect_regression(recent, baseline, service_name="my-svc")
        err_reports = [r for r in reports if r.metric == "error_rate"]
        assert len(err_reports) >= 1
        assert err_reports[0].change_pct > 0

    def test_latency_regression_flagged(self):
        baseline = self._make_traces(10, duration_ms=100)
        recent = self._make_traces(10, duration_ms=500)

        reports = SmartAdvisor().detect_regression(recent, baseline)
        lat_reports = [r for r in reports if r.metric == "latency"]
        assert len(lat_reports) >= 1
        assert lat_reports[0].recent_value > lat_reports[0].baseline_value

    def test_no_regression_when_metrics_stable(self):
        baseline = self._make_traces(10, error_fraction=0.0, duration_ms=200, cost=0.01)
        recent = self._make_traces(10, error_fraction=0.0, duration_ms=210, cost=0.011)

        reports = SmartAdvisor().detect_regression(recent, baseline)
        # Small changes (<20%) should not trigger regressions
        assert len(reports) == 0

    def test_empty_recent_returns_no_reports(self):
        baseline = self._make_traces(5)
        reports = SmartAdvisor().detect_regression([], baseline)
        assert reports == []

    def test_empty_baseline_returns_no_reports(self):
        recent = self._make_traces(5)
        reports = SmartAdvisor().detect_regression(recent, [])
        assert reports == []

    def test_regression_report_to_dict(self):
        baseline = self._make_traces(10, error_fraction=0.01)
        recent = self._make_traces(10, error_fraction=0.80)

        reports = SmartAdvisor().detect_regression(recent, baseline)
        assert len(reports) > 0

        d = reports[0].to_dict()
        required = ["metric", "service_name", "baseline_value", "recent_value",
                    "change_pct", "description", "severity"]
        for key in required:
            assert key in d, f"Missing key: {key}"

    def test_cost_regression_flagged(self):
        baseline = self._make_traces(10, cost=0.01)
        recent = self._make_traces(10, cost=0.05)

        reports = SmartAdvisor().detect_regression(recent, baseline)
        cost_reports = [r for r in reports if r.metric == "cost"]
        assert len(cost_reports) >= 1

    def test_critical_severity_for_large_error_rate_increase(self):
        """Error rate going from 0% to 100% should be 'critical'."""
        baseline = self._make_traces(10, error_fraction=0.0)
        recent = self._make_traces(10, error_fraction=1.0)

        reports = SmartAdvisor().detect_regression(recent, baseline)
        err_reports = [r for r in reports if r.metric == "error_rate"]
        assert len(err_reports) >= 1
        assert err_reports[0].severity == "critical"


# ---------------------------------------------------------------------------
# Pipeline reorder suggestions
# ---------------------------------------------------------------------------


class TestPipelineReorder:
    def _make_ordered_trace(
        self,
        trace_id: str,
        sequence: list[str],
        success: bool = True,
    ) -> Trace:
        spans = []
        t0 = time.time()
        for i, name in enumerate(sequence):
            s = Span(
                name=name,
                kind=SpanKind.TOOL,
                status=SpanStatus.OK if success else SpanStatus.ERROR,
                start_time=t0 + i * 0.1,
                end_time=t0 + i * 0.1 + 0.05,
            )
            s.trace_id = trace_id
            spans.append(s)
        t = Trace(trace_id=trace_id, service_name="svc")
        t.start_time = t0
        t.end_time = t0 + len(sequence) * 0.1
        t.spans = spans
        return t

    def test_returns_list(self):
        traces = [self._make_ordered_trace("t1", ["search", "generate"], success=True)]
        result = SmartAdvisor().suggest_pipeline_reorder(traces)
        assert isinstance(result, list)

    def test_empty_traces_returns_empty(self):
        result = SmartAdvisor().suggest_pipeline_reorder([])
        assert result == []

    def test_single_trace_returns_empty(self):
        t = self._make_ordered_trace("t1", ["a", "b"])
        result = SmartAdvisor().suggest_pipeline_reorder([t])
        assert result == []

    def test_better_order_suggested(self):
        """
        If A→B succeeds 90% of the time but B→A only 10%, a reorder suggestion
        should be returned.
        """
        traces = []
        # 9 traces with search → generate (success)
        for i in range(9):
            traces.append(
                self._make_ordered_trace(f"ab-{i}", ["search", "generate"], success=True)
            )
        # 1 trace with search → generate (fail)
        traces.append(
            self._make_ordered_trace("ab-fail", ["search", "generate"], success=False)
        )
        # 1 trace with generate → search (success)
        traces.append(
            self._make_ordered_trace("ba-ok", ["generate", "search"], success=True)
        )
        # 9 traces with generate → search (fail)
        for i in range(9):
            traces.append(
                self._make_ordered_trace(f"ba-fail-{i}", ["generate", "search"], success=False)
            )

        suggestions = SmartAdvisor().suggest_pipeline_reorder(traces)
        assert len(suggestions) >= 1
        s = suggestions[0]
        assert "search" in s.current_sequence or "search" in s.suggested_sequence

    def test_suggestion_to_dict(self):
        traces = []
        for i in range(5):
            traces.append(self._make_ordered_trace(f"ab-{i}", ["a", "b"], success=True))
        for i in range(5):
            traces.append(self._make_ordered_trace(f"ba-{i}", ["b", "a"], success=False))

        suggestions = SmartAdvisor().suggest_pipeline_reorder(traces)
        if suggestions:
            d = suggestions[0].to_dict()
            for key in ["current_sequence", "suggested_sequence",
                        "success_rate_current", "success_rate_suggested", "description"]:
                assert key in d
