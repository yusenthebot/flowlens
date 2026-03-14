"""Tests for TraceDiff — single-trace diff and experiment diff."""

from __future__ import annotations

import time

import pytest

from flowlens.sdk.models import Span, SpanKind, SpanStatus, Trace, TokenUsage
from flowlens.analysis.trace_diff import (
    DiffResult,
    ExperimentDiffResult,
    SpanComparison,
    TraceDiff,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_span(
    name: str,
    duration_ms: float = 100.0,
    tokens: int = 0,
    status: SpanStatus = SpanStatus.OK,
    model: str = "",
) -> Span:
    now = time.time()
    s = Span(
        name=name,
        kind=SpanKind.TOOL,
        status=status,
        start_time=now,
        end_time=now + duration_ms / 1000.0,
    )
    if tokens:
        s.token_usage = TokenUsage(
            input_tokens=tokens,
            output_tokens=10,
            total_tokens=tokens + 10,
            total_cost_usd=(tokens + 10) * 0.000003,
        )
    return s


def _make_trace(trace_id: str, *spans: Span, service: str = "svc") -> Trace:
    trace = Trace(trace_id=trace_id, service_name=service)
    start = time.time()
    trace.start_time = start
    trace.end_time = start + sum(s.duration_ms for s in spans) / 1000.0
    for s in spans:
        s.trace_id = trace_id
    trace.spans = list(spans)
    return trace


# ---------------------------------------------------------------------------
# Single-trace diff
# ---------------------------------------------------------------------------


class TestTraceDiff:
    def test_identical_traces_have_zero_deltas(self):
        s = _make_span("search", duration_ms=200, tokens=100)
        trace_a = _make_trace("a", s)

        s2 = _make_span("search", duration_ms=200, tokens=100)
        trace_b = _make_trace("b", s2)

        differ = TraceDiff()
        result = differ.diff(trace_a, trace_b)

        assert isinstance(result, DiffResult)
        assert result.token_diff == 0
        assert result.cost_diff_usd == pytest.approx(0.0, abs=1e-9)
        assert result.duration_diff_ms == pytest.approx(0.0, abs=1.0)

    def test_faster_trace_b(self):
        """Trace B faster → negative duration_diff_ms."""
        s_a = _make_span("llm", duration_ms=500)
        trace_a = _make_trace("a", s_a)

        s_b = _make_span("llm", duration_ms=100)
        trace_b = _make_trace("b", s_b)

        differ = TraceDiff()
        result = differ.diff(trace_a, trace_b)

        assert result.duration_diff_ms < 0, "B should be faster (negative diff)"

    def test_slower_trace_b(self):
        """Trace B slower → positive duration_diff_ms."""
        s_a = _make_span("llm", duration_ms=100)
        trace_a = _make_trace("a", s_a)

        s_b = _make_span("llm", duration_ms=600)
        trace_b = _make_trace("b", s_b)

        differ = TraceDiff()
        result = differ.diff(trace_a, trace_b)

        assert result.duration_diff_ms > 0, "B should be slower (positive diff)"

    def test_cheaper_trace_b(self):
        """Trace B cheaper → negative cost_diff_usd."""
        s_a = _make_span("llm", tokens=1000)
        trace_a = _make_trace("a", s_a)

        s_b = _make_span("llm", tokens=100)
        trace_b = _make_trace("b", s_b)

        differ = TraceDiff()
        result = differ.diff(trace_a, trace_b)

        assert result.cost_diff_usd < 0
        assert result.token_diff < 0

    def test_span_matching_by_name(self):
        """Spans with matching names land in span_diffs."""
        s_a = _make_span("search", duration_ms=300)
        trace_a = _make_trace("a", s_a)

        s_b = _make_span("search", duration_ms=150)
        trace_b = _make_trace("b", s_b)

        differ = TraceDiff()
        result = differ.diff(trace_a, trace_b)

        assert len(result.span_diffs) == 1
        cmp: SpanComparison = result.span_diffs[0]
        assert cmp.name == "search"
        assert cmp.a_duration_ms == pytest.approx(300, abs=10)
        assert cmp.b_duration_ms == pytest.approx(150, abs=10)

    def test_only_in_a_and_only_in_b(self):
        """Spans exclusive to each side are categorised correctly."""
        s_a1 = _make_span("validate")
        s_a2 = _make_span("search")
        trace_a = _make_trace("a", s_a1, s_a2)

        s_b1 = _make_span("search")
        s_b2 = _make_span("generate")
        trace_b = _make_trace("b", s_b1, s_b2)

        differ = TraceDiff()
        result = differ.diff(trace_a, trace_b)

        assert "validate" in result.only_in_a
        assert "generate" in result.only_in_b
        assert "search" not in result.only_in_a
        assert "search" not in result.only_in_b

    def test_span_status_captured(self):
        """Status fields in SpanComparison reflect the actual span status."""
        s_a = _make_span("search", status=SpanStatus.OK)
        trace_a = _make_trace("a", s_a)

        s_b = _make_span("search", status=SpanStatus.ERROR)
        s_b.error_message = "timeout"
        trace_b = _make_trace("b", s_b)

        differ = TraceDiff()
        result = differ.diff(trace_a, trace_b)

        assert len(result.span_diffs) == 1
        cmp = result.span_diffs[0]
        assert cmp.a_status == "ok"
        assert cmp.b_status == "error"

    def test_summary_is_non_empty_string(self):
        """diff() always returns a non-empty summary string."""
        s_a = _make_span("agent", duration_ms=200, tokens=500)
        trace_a = _make_trace("a", s_a)

        s_b = _make_span("agent", duration_ms=100, tokens=200)
        trace_b = _make_trace("b", s_b)

        differ = TraceDiff()
        result = differ.diff(trace_a, trace_b)

        assert isinstance(result.summary, str)
        assert len(result.summary) > 0

    def test_to_dict_structure(self):
        """DiffResult.to_dict() has the expected top-level keys."""
        s_a = _make_span("x")
        s_b = _make_span("x")
        trace_a = _make_trace("a", s_a)
        trace_b = _make_trace("b", s_b)

        result = TraceDiff().diff(trace_a, trace_b)
        d = result.to_dict()

        assert "trace_a_id" in d
        assert "trace_b_id" in d
        assert "duration_diff_ms" in d
        assert "cost_diff_usd" in d
        assert "token_diff" in d
        assert "span_diffs" in d
        assert "only_in_a" in d
        assert "only_in_b" in d
        assert "pattern_diffs" in d
        assert "summary" in d

    def test_pattern_diff_fields(self):
        """pattern_diffs keys exist even when both traces are clean."""
        s_a = _make_span("x")
        s_b = _make_span("x")
        trace_a = _make_trace("a", s_a)
        trace_b = _make_trace("b", s_b)

        result = TraceDiff().diff(trace_a, trace_b)
        d = result.to_dict()

        pd = d["pattern_diffs"]
        assert "resolved_in_b" in pd
        assert "new_in_b" in pd
        assert isinstance(pd["resolved_in_b"], list)
        assert isinstance(pd["new_in_b"], list)


# ---------------------------------------------------------------------------
# Experiment diff
# ---------------------------------------------------------------------------


class TestExperimentDiff:
    def _make_group(
        self,
        name: str,
        n: int,
        duration_ms: float,
        cost: float,
        error_fraction: float = 0.0,
    ) -> list[Trace]:
        traces = []
        n_errors = int(n * error_fraction)
        now = time.time()
        for i in range(n):
            t = Trace(trace_id=f"{name}-{i}", service_name=name)
            t.start_time = now - 3600  # in the past
            t.end_time = t.start_time + duration_ms / 1000.0
            s = Span(
                name="work",
                kind=SpanKind.TOOL,
                status=SpanStatus.ERROR if i < n_errors else SpanStatus.OK,
                start_time=t.start_time,
                end_time=t.end_time,
            )
            s.token_usage = TokenUsage(
                input_tokens=100,
                output_tokens=10,
                total_tokens=110,
                total_cost_usd=cost,
            )
            s.trace_id = t.trace_id
            t.spans = [s]
            traces.append(t)
        return traces

    def test_aggregate_diff_averages(self):
        group_a = self._make_group("exp-a", n=5, duration_ms=500, cost=0.01)
        group_b = self._make_group("exp-b", n=5, duration_ms=250, cost=0.005)

        differ = TraceDiff()
        result = differ.diff_experiments(group_a, group_b, name_a="exp-a", name_b="exp-b")

        assert isinstance(result, ExperimentDiffResult)
        # B is faster → negative avg_duration_diff
        assert result.avg_duration_diff_ms < 0
        # B is cheaper → negative avg_cost_diff
        assert result.avg_cost_diff_usd < 0

    def test_error_rate_comparison(self):
        """Experiment with errors has higher error rate reflected in diff."""
        group_a = self._make_group("a", n=10, duration_ms=200, cost=0.01, error_fraction=0.1)
        group_b = self._make_group("b", n=10, duration_ms=200, cost=0.01, error_fraction=0.5)

        differ = TraceDiff()
        result = differ.diff_experiments(group_a, group_b, name_a="a", name_b="b")

        assert result.error_rate_a == pytest.approx(0.1, abs=0.01)
        assert result.error_rate_b == pytest.approx(0.5, abs=0.01)
        assert result.error_rate_diff > 0

    def test_p95_latency_computed(self):
        """p95 fields are populated."""
        group_a = self._make_group("a", n=20, duration_ms=100, cost=0.0)
        group_b = self._make_group("b", n=20, duration_ms=300, cost=0.0)

        result = TraceDiff().diff_experiments(group_a, group_b, name_a="a", name_b="b")

        assert result.p95_duration_a_ms > 0
        assert result.p95_duration_b_ms > 0
        assert result.p95_duration_diff_ms > 0

    def test_experiment_summary_non_empty(self):
        group_a = self._make_group("a", n=5, duration_ms=200, cost=0.02)
        group_b = self._make_group("b", n=5, duration_ms=100, cost=0.01)

        result = TraceDiff().diff_experiments(group_a, group_b)
        assert isinstance(result.summary, str)
        assert len(result.summary) > 0

    def test_to_dict_keys(self):
        group_a = self._make_group("a", n=3, duration_ms=100, cost=0.0)
        group_b = self._make_group("b", n=3, duration_ms=200, cost=0.0)

        d = TraceDiff().diff_experiments(group_a, group_b).to_dict()
        required_keys = [
            "experiment_a", "experiment_b",
            "avg_duration_diff_ms", "avg_cost_diff_usd", "avg_token_diff",
            "p95_duration_a_ms", "p95_duration_b_ms", "p95_duration_diff_ms",
            "error_rate_a", "error_rate_b", "error_rate_diff",
            "summary",
        ]
        for key in required_keys:
            assert key in d, f"Missing key: {key}"
