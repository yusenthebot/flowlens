"""FlowLens Evaluation Engine — Comprehensive testing and assessment framework.

Provides:
- Core evaluators (exact match, keywords, JSON schema, cost, latency, LLM judge)
- Batch evaluation runner
- Dataset management and evaluation
- Storage layer for results
"""

from __future__ import annotations

__version__ = "1.0.0"
__all__ = [
    "EvalResult",
    "ExactMatch",
    "ContainsKeywords",
    "JsonSchemaValid",
    "CostThreshold",
    "LatencyThreshold",
    "LLMJudge",
    "EvaluationRunner",
    "DatasetStorage",
    "EvaluationStorage",
]
