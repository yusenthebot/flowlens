"""
FlowLens Evaluation — EvaluationRunner.

EvaluationRunner orchestrates running one or more :class:`Evaluator` instances
against traces and spans fetched from the FlowLens data model.

Typical usage::

    from flowlens.evaluation import (
        EvaluationRunner,
        ExactMatch,
        CostThreshold,
        LatencyThreshold,
    )

    runner = EvaluationRunner(evaluators=[
        ExactMatch(expected="Paris"),
        CostThreshold(max_cost_usd=0.05),
        LatencyThreshold(max_ms=3000),
    ])

    # Run against a single trace dict
    results = runner.run_on_trace(trace_data)
    for r in results:
        print(r.evaluator, r.label, r.score)

    # Run against a batch of traces
    batch_results = runner.run_batch(traces)
    for trace_id, results in batch_results.items():
        print(trace_id, [r.label for r in results])
"""

from __future__ import annotations

import logging
from typing import Any

from .evaluators import EvalResult, Evaluator

logger = logging.getLogger(__name__)


class EvaluationRunner:
    """Runs a list of evaluators against traces and spans.

    Args:
        evaluators: List of :class:`Evaluator` instances to run.
                    Each evaluator is called for every matching span (or
                    once for trace-level evaluators).

    Thread safety:
        ``EvaluationRunner`` is stateless between calls; the same instance
        can safely be used from multiple threads concurrently.
    """

    def __init__(self, evaluators: list[Evaluator]) -> None:
        if not evaluators:
            raise ValueError("EvaluationRunner requires at least one evaluator.")
        self.evaluators = evaluators

    # ------------------------------------------------------------------
    # run_on_trace
    # ------------------------------------------------------------------

    def run_on_trace(self, trace_data: dict[str, Any]) -> list[EvalResult]:
        """Run all evaluators against the trace as a whole.

        Each evaluator is called with ``span_data={}`` and the full
        ``trace_data``.  This is appropriate for trace-level evaluators such
        as :class:`CostThreshold` and :class:`LatencyThreshold`.

        Args:
            trace_data: A trace dict (as returned by the FlowLens ingest API).

        Returns:
            A flat list of :class:`EvalResult` — one per evaluator.
        """
        results: list[EvalResult] = []
        for ev in self.evaluators:
            try:
                result = ev.evaluate(span_data={}, trace_data=trace_data)
                results.append(result)
            except Exception as exc:
                logger.warning(
                    "Evaluator %r raised an exception on trace %r: %s",
                    ev.name,
                    trace_data.get("trace_id", "unknown"),
                    exc,
                )
                # Return a fail result so the runner always produces N results
                results.append(
                    EvalResult(
                        score=0.0,
                        label="fail",
                        reason=f"Evaluator raised an unexpected exception: {exc}",
                        evaluator=ev.name,
                        metadata={"exception": str(exc)},
                    )
                )
        return results

    # ------------------------------------------------------------------
    # run_on_spans
    # ------------------------------------------------------------------

    def run_on_spans(
        self,
        trace_data: dict[str, Any],
        span_filter: str = "llm",
    ) -> list[EvalResult]:
        """Run all evaluators against spans of a given type within the trace.

        Each matching span is evaluated independently.  If no spans match the
        filter an empty list is returned.

        Args:
            trace_data:   A trace dict containing a ``"spans"`` list.
            span_filter:  Span kind to target.  Common values:
                          ``"llm"`` — LLM generation spans (default)
                          ``"tool"`` — tool-call spans
                          ``"agent"`` — agent-level spans
                          ``""`` or ``None`` — all spans

        Returns:
            A flat list of :class:`EvalResult` entries.  Results are ordered by
            (span_index, evaluator_index) so batch processing is predictable.
        """
        spans: list[dict[str, Any]] = trace_data.get("spans") or []

        if span_filter:
            needle = span_filter.lower()
            matching_spans = [s for s in spans if self._span_matches_filter(s, needle)]
        else:
            matching_spans = list(spans)

        if not matching_spans:
            logger.debug(
                "run_on_spans: no spans matched filter %r in trace %r",
                span_filter,
                trace_data.get("trace_id", "unknown"),
            )
            return []

        results: list[EvalResult] = []
        for span in matching_spans:
            for ev in self.evaluators:
                try:
                    result = ev.evaluate(span_data=span, trace_data=trace_data)
                    results.append(result)
                except Exception as exc:
                    logger.warning(
                        "Evaluator %r raised on span %r: %s",
                        ev.name,
                        span.get("span_id", "unknown"),
                        exc,
                    )
                    results.append(
                        EvalResult(
                            score=0.0,
                            label="fail",
                            reason=f"Evaluator raised an unexpected exception: {exc}",
                            evaluator=ev.name,
                            metadata={
                                "exception": str(exc),
                                "span_id": span.get("span_id"),
                            },
                        )
                    )
        return results

    # ------------------------------------------------------------------
    # run_batch
    # ------------------------------------------------------------------

    def run_batch(
        self,
        traces: list[dict[str, Any]],
    ) -> dict[str, list[EvalResult]]:
        """Run all evaluators against multiple traces.

        Each trace is evaluated independently via :meth:`run_on_trace`.

        Args:
            traces: List of trace dicts.

        Returns:
            A mapping of ``{trace_id: [EvalResult, ...]}`` where ``trace_id``
            falls back to the list index (as a string) when the trace has no
            ``trace_id`` key.
        """
        output: dict[str, list[EvalResult]] = {}
        for idx, trace_data in enumerate(traces):
            trace_id = str(trace_data.get("trace_id") or idx)
            output[trace_id] = self.run_on_trace(trace_data)
        return output

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _span_matches_filter(span: dict[str, Any], needle: str) -> bool:
        """Return True if the span kind or name matches the filter string.

        Checks (in order):
        1. ``span["kind"]`` (e.g. "llm", "tool", "agent")
        2. ``span["name"]`` (substring match)
        3. ``span["attributes"]["gen_ai.operation.name"]``
        """
        kind = str(span.get("kind") or "").lower()
        if kind == needle:
            return True

        name = str(span.get("name") or "").lower()
        if needle in name:
            return True

        attrs = span.get("attributes") or {}
        op_name = str(attrs.get("gen_ai.operation.name") or "").lower()
        return needle in op_name

    # ------------------------------------------------------------------
    # Aggregate helpers
    # ------------------------------------------------------------------

    @staticmethod
    def summary(results: list[EvalResult]) -> dict[str, Any]:
        """Compute a high-level summary dict from a list of results.

        Returns a dict with keys:
        - ``total``: total number of results
        - ``passed``: count of "pass" labels
        - ``failed``: count of "fail" labels
        - ``partial``: count of "partial" labels
        - ``avg_score``: mean score across all results (0.0 if empty)
        - ``pass_rate``: fraction of passing results (0.0 if empty)
        """
        if not results:
            return {
                "total": 0,
                "passed": 0,
                "failed": 0,
                "partial": 0,
                "avg_score": 0.0,
                "pass_rate": 0.0,
            }

        passed = sum(1 for r in results if r.label == "pass")
        failed = sum(1 for r in results if r.label == "fail")
        partial = sum(1 for r in results if r.label == "partial")
        avg_score = sum(r.score for r in results) / len(results)
        pass_rate = passed / len(results)

        return {
            "total": len(results),
            "passed": passed,
            "failed": failed,
            "partial": partial,
            "avg_score": round(avg_score, 4),
            "pass_rate": round(pass_rate, 4),
        }


__all__ = ["EvaluationRunner"]
