# FlowLens Evaluation Engine — Complete Guide

The Evaluation Engine is FlowLens' comprehensive framework for testing, assessing, and validating LLM agent traces against multiple criteria. Use it to:

- **Quality Assurance**: Verify agent outputs meet business requirements
- **Regression Testing**: Create datasets and detect model performance degradation
- **Cost Control**: Enforce budget constraints per trace or trace class
- **Latency SLAs**: Monitor and alert on performance violations
- **Qualitative Assessment**: Use LLM judges for nuanced evaluation
- **Trend Analysis**: Track evaluation metrics over time

---

## Quick Start

### 1. Basic Evaluation

```python
from flowlens.evaluation.core import ExactMatch, EvaluationRunner

# Create a trace
trace = {
    "trace_id": "t1",
    "duration_ms": 100.0,
    "total_cost_usd": 0.01,
    "spans": [
        {
            "span_id": "t1_s1",
            "output": "The answer is 42"
        }
    ]
}

# Create evaluator
evaluator = ExactMatch(expected="The answer is 42")

# Run evaluation
runner = EvaluationRunner()
runner.add_evaluator(evaluator)
results = runner.run(trace)

for result in results:
    print(f"{result.evaluator_name}: {result.passed}")
```

### 2. Multi-Criteria Evaluation

```python
from flowlens.evaluation.core import (
    ContainsKeywords,
    CostThreshold,
    LatencyThreshold,
    EvaluationRunner,
)

runner = EvaluationRunner()
runner.add_evaluator(ContainsKeywords(keywords=["answer", "confidence"]))
runner.add_evaluator(CostThreshold(max_cost_usd=0.05))
runner.add_evaluator(LatencyThreshold(max_latency_ms=1000.0))

results = runner.run(trace)
summary = runner.get_summary([results])
print(f"Pass rate: {summary['pass_rate']:.1%}")
```

### 3. Dataset Management

```python
from flowlens.evaluation.storage import DatasetStorage, EvaluationStorage

storage = DatasetStorage()
eval_storage = EvaluationStorage()

# Create dataset
dataset_id = storage.create_dataset(
    name="regression-tests",
    description="Tests for model v2 regression"
)

# Add traces
for i, trace in enumerate(traces):
    storage.add_trace_to_dataset(dataset_id, f"trace-{i}", trace)

# Get traces from dataset
dataset_traces = storage.get_dataset_traces(dataset_id)

# Batch evaluate
all_results = runner.run_batch(dataset_traces)

# Save results
for trace, results in zip(dataset_traces, all_results):
    for result in results:
        eval_storage.save_evaluation(trace["trace_id"], {
            "trace_id": result.trace_id,
            "evaluator_name": result.evaluator_name,
            "passed": result.passed,
            "score": result.score,
            "details": result.details,
        })
```

---

## Evaluator Reference

### ExactMatch

Verify trace output exactly matches an expected value.

```python
from flowlens.evaluation.core import ExactMatch

evaluator = ExactMatch(
    expected="Expected output",
    case_insensitive=False  # optional
)
result = evaluator.evaluate(trace)
```

**Score**: 1.0 if matched, 0.0 otherwise
**Use cases**: Regression testing, deterministic outputs

### ContainsKeywords

Check if trace output contains required keywords.

```python
from flowlens.evaluation.core import ContainsKeywords

evaluator = ContainsKeywords(
    keywords=["key1", "key2", "key3"],
    require_all=True  # require all keywords (or any if False)
)
result = evaluator.evaluate(trace)
```

**Score**: (keywords_found / total_keywords)
**Use cases**: Feature verification, output validation

### JsonSchemaValid

Verify output is valid JSON (and optionally matches a schema).

```python
from flowlens.evaluation.core import JsonSchemaValid

schema = {
    "type": "object",
    "properties": {
        "result": {"type": "string"},
        "confidence": {"type": "number"}
    },
    "required": ["result", "confidence"]
}

evaluator = JsonSchemaValid(schema=schema)
result = evaluator.evaluate(trace)
```

**Score**: 1.0 if valid JSON, 0.0 otherwise
**Use cases**: Structured output validation, API contracts

### CostThreshold

Enforce maximum cost per trace.

```python
from flowlens.evaluation.core import CostThreshold

evaluator = CostThreshold(max_cost_usd=0.05)
result = evaluator.evaluate(trace)
```

**Score**: min(1.0, budget / actual_cost)
**Details**: Shows actual cost vs budget

**Use cases**: Cost control, budget enforcement

### LatencyThreshold

Enforce maximum latency per trace.

```python
from flowlens.evaluation.core import LatencyThreshold

evaluator = LatencyThreshold(max_latency_ms=1000.0)
result = evaluator.evaluate(trace)
```

**Score**: min(1.0, threshold / actual_duration)
**Details**: Shows actual duration vs threshold

**Use cases**: SLA monitoring, performance gates

### LLMJudge

Qualitative evaluation using an LLM.

```python
from flowlens.evaluation.core import LLMJudge

evaluator = LLMJudge(
    criteria="Is the output helpful and accurate?"
)
result = evaluator.evaluate(trace)
```

**Score**: LLM-dependent (0.0-1.0)
**Details**: LLM reasoning and score

**Note**: Implementation pending (Cycle 30)

---

## Custom Evaluators

Implement custom evaluators by extending the `Evaluator` base class:

```python
from flowlens.evaluation.core import Evaluator, EvalResult
from typing import Any

class MyCustomEvaluator(Evaluator):
    def __init__(self, threshold: float):
        self.threshold = threshold

    def evaluate(self, trace: dict[str, Any]) -> EvalResult:
        # Your evaluation logic here
        output = trace.get("spans", [{}])[0].get("output", "")
        
        # Extract metric from output
        value = extract_metric(output)
        passed = value > self.threshold
        
        return EvalResult(
            trace_id=trace["trace_id"],
            evaluator_name="my_custom_evaluator",
            passed=passed,
            score=min(1.0, value / self.threshold),
            details=f"Value: {value:.2f} (threshold: {self.threshold:.2f})"
        )
```

Then use it like any built-in evaluator:

```python
runner = EvaluationRunner()
runner.add_evaluator(MyCustomEvaluator(threshold=0.95))
results = runner.run(trace)
```

---

## API Reference

### EvalResult

```python
@dataclass
class EvalResult:
    trace_id: str          # Trace being evaluated
    evaluator_name: str    # Name of evaluator
    passed: bool           # Pass/fail status
    score: float           # Score (0.0-1.0)
    details: str           # Human-readable details (optional)
```

### EvaluationRunner

```python
runner = EvaluationRunner()

# Register evaluators
runner.add_evaluator(evaluator1)
runner.add_evaluator(evaluator2)

# Run single trace
results: list[EvalResult] = runner.run(trace)

# Run multiple traces
all_results: list[list[EvalResult]] = runner.run_batch(traces)

# Get summary stats
summary: dict = runner.get_summary(all_results)
# Returns:
# {
#     "total_evals": int,
#     "passed": int,
#     "failed": int,
#     "pass_rate": float,
#     "by_evaluator": {
#         "evaluator_name": {"passed": int, "total": int}
#     }
# }
```

### DatasetStorage

```python
storage = DatasetStorage(db_path="./eval_datasets.db")

# Create dataset
dataset_id = storage.create_dataset(
    name="my-dataset",
    description="Optional description"
)

# Add traces
storage.add_trace_to_dataset(dataset_id, trace_id, trace_dict)

# Retrieve
traces = storage.get_dataset_traces(dataset_id)
datasets = storage.list_datasets()
```

### EvaluationStorage

```python
storage = EvaluationStorage(db_path="./eval_results.db")

# Save result
result_id = storage.save_evaluation(trace_id, {
    "trace_id": "t1",
    "evaluator_name": "exact_match",
    "passed": True,
    "score": 1.0,
    "details": "Output matched"
})

# Query results
results = storage.get_evaluations_for_trace(trace_id)
all_results = storage.list_evaluations()
filtered = storage.list_evaluations(evaluator_name="cost_threshold")
```

---

## Usage Patterns

### Pattern 1: Quality Gates

Enforce minimum quality standards before deployment:

```python
runner = EvaluationRunner()
runner.add_evaluator(ExactMatch(expected=baseline_output))
runner.add_evaluator(JsonSchemaValid(schema=contract))
runner.add_evaluator(CostThreshold(max_cost_usd=0.05))

results = runner.run(trace)
if all(r.passed for r in results):
    print("DEPLOYMENT APPROVED")
else:
    print("DEPLOYMENT BLOCKED")
```

### Pattern 2: Regression Testing

Create a dataset baseline and detect degradation:

```python
# Create baseline dataset from current model
baseline = storage.create_dataset(name="baseline-v1")
for trace in baseline_traces:
    storage.add_trace_to_dataset(baseline, trace["trace_id"], trace)

# Test new model against baseline evaluations
results_baseline = runner.run_batch(
    storage.get_dataset_traces(baseline)
)

# Test candidate model
results_candidate = runner.run_batch(
    storage.get_dataset_traces(candidate)
)

# Compare pass rates
baseline_rate = runner.get_summary(results_baseline)["pass_rate"]
candidate_rate = runner.get_summary(results_candidate)["pass_rate"]

if candidate_rate < baseline_rate * 0.95:
    print("REGRESSION DETECTED")
```

### Pattern 3: Cost Optimization

Track cost over time and identify expensive operations:

```python
eval_storage = EvaluationStorage()
cost_evaluator = CostThreshold(max_cost_usd=0.01)

for trace in all_traces:
    result = cost_evaluator.evaluate(trace)
    eval_storage.save_evaluation(trace["trace_id"], {
        "trace_id": result.trace_id,
        "evaluator_name": result.evaluator_name,
        "passed": result.passed,
        "score": result.score,
        "details": result.details,
    })

# Find over-budget traces
over_budget = eval_storage.list_evaluations(evaluator_name="cost_threshold")
failures = [r for r in over_budget if not r["passed"]]
print(f"Over-budget: {len(failures)}/{len(over_budget)}")
```

---

## Testing the Framework

Run the evaluation tests:

```bash
# All evaluation tests
pytest tests/test_evaluation*.py -v

# Specific test class
pytest tests/test_evaluations.py::TestExactMatch -v

# Run example
python examples/evaluation_pipeline.py
```

---

## Integration with FlowLens Server (Cycle 30)

The following REST endpoints will be added:

```
POST /v1/evaluations/run
  Request: {trace_id, evaluators: [{type, config}]}
  Response: {trace_id, results: [EvalResult]}

POST /v1/datasets
  Request: {name, description}
  Response: {id, name, created_at}

GET /v1/datasets
  Response: [{id, name, description, trace_count}]

GET /v1/datasets/{dataset_id}/traces
  Response: [trace_dict]

POST /v1/datasets/{dataset_id}/evaluate
  Request: {evaluators: [{type, config}]}
  Response: {dataset_id, results: [summary]}

GET /v1/traces/{trace_id}/evaluations
  Response: [EvalResult]

GET /v1/evaluations
  Params: ?evaluator_name=X&page=N&limit=M
  Response: [EvalResult]
```

---

## Troubleshooting

### Problem: Evaluation times out
**Solution**: For LLMJudge, use batching and caching in Cycle 30

### Problem: False negatives in ContainsKeywords
**Solution**: Use case_insensitive=True in ExactMatch, or adjust keyword list

### Problem: Can't import evaluation module
**Solution**: Ensure `flowlens/evaluation/` is in sys.path or installed package

### Problem: Database locked
**Solution**: Ensure only one process writes; use connection pooling in production

---

## See Also

- **Architecture**: `docs/architecture.md` — System design
- **API Reference**: `docs/api-reference.md` — Complete endpoint docs
- **Deployment**: `docs/deployment.md` — Production setup
- **Examples**: `examples/evaluation_pipeline.py` — Real-world usage

---

**Version**: 1.0.0
**Status**: Core complete, API integration pending (Cycle 30)
**Last Updated**: 2026-03-16
