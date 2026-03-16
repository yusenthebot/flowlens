"""
FlowLens Evaluation — programmatic quality assessment for LLM agent traces.

This module provides a composable evaluation framework for assessing the
quality, correctness, cost, and latency of LLM agent outputs captured by
FlowLens tracing.

Quick start::

    from flowlens.evaluation import (
        EvaluationRunner,
        ExactMatch,
        ContainsKeywords,
        JsonSchemaValid,
        CostThreshold,
        LatencyThreshold,
        LLMJudge,
    )

    runner = EvaluationRunner(evaluators=[
        ContainsKeywords(["Python", "asyncio"]),
        CostThreshold(max_cost_usd=0.10),
        LatencyThreshold(max_ms=5000),
    ])

    results = runner.run_on_trace(trace_dict)
    summary = EvaluationRunner.summary(results)
    print(summary)  # {"total": 3, "passed": 2, "failed": 1, ...}

Evaluators
----------
ExactMatch
    Checks that the LLM output exactly equals an expected string.
ContainsKeywords
    Checks that the LLM output contains required keywords.
JsonSchemaValid
    Validates LLM output as JSON against a provided JSON Schema.
CostThreshold
    Passes when the trace total cost is below a USD threshold.
LatencyThreshold
    Passes when the trace duration is below a millisecond threshold.
LLMJudge
    Uses an LLM to judge another LLM's output quality.

Runner
------
EvaluationRunner
    Orchestrates running evaluators against traces, spans, or batches.

Data classes
------------
EvalResult
    The output of a single evaluator: score, label, reason, metadata.
"""

from __future__ import annotations

from .evaluators import (
    ContainsKeywords,
    CostThreshold,
    EvalResult,
    Evaluator,
    ExactMatch,
    JsonSchemaValid,
    LatencyThreshold,
)
from .llm_judge import LLMJudge
from .runner import EvaluationRunner

__all__ = [
    # Data model
    "EvalResult",
    # ABC
    "Evaluator",
    # Built-in evaluators
    "ExactMatch",
    "ContainsKeywords",
    "JsonSchemaValid",
    "CostThreshold",
    "LatencyThreshold",
    # LLM judge
    "LLMJudge",
    # Runner
    "EvaluationRunner",
]
