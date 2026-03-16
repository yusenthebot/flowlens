"""
Complete evaluation pipeline example.

This example demonstrates:
1. Running a simulated agent trace
2. Creating evaluations with multiple criteria
3. Running evaluations and printing results
4. Creating a dataset from traces
5. Running dataset-wide evaluations
"""

from __future__ import annotations

import json
from typing import Any

from flowlens.evaluation.core import (
    EvalResult,
    ExactMatch,
    ContainsKeywords,
    JsonSchemaValid,
    CostThreshold,
    LatencyThreshold,
    EvaluationRunner,
)
from flowlens.evaluation.storage import DatasetStorage, EvaluationStorage


# ---------------------------------------------------------------------------
# 1. Define Helper Functions
# ---------------------------------------------------------------------------


def create_mock_trace(
    trace_id: str,
    agent_name: str = "test-agent",
    duration_ms: float = 100.0,
    cost_usd: float = 0.01,
    output: str = "Success",
    has_error: bool = False,
) -> dict[str, Any]:
    """Create a simulated trace for testing."""
    return {
        "trace_id": trace_id,
        "agent_name": agent_name,
        "duration_ms": duration_ms,
        "total_cost_usd": cost_usd,
        "spans": [
            {
                "span_id": f"{trace_id}_s1",
                "name": "agent",
                "status": "error" if has_error else "ok",
                "start_time": 1000.0,
                "end_time": 1000.0 + duration_ms / 1000.0,
                "duration_ms": duration_ms,
                "attributes": {"agent.name": agent_name},
                "output": output,
                "error": {"message": "Something went wrong"} if has_error else None,
            }
        ],
    }


def print_eval_result(result: EvalResult) -> None:
    """Pretty-print an evaluation result."""
    status = "PASS" if result.passed else "FAIL"
    print(f"  [{status}] {result.evaluator_name}: {result.score:.2f}")
    if result.details:
        print(f"       → {result.details}")


# ---------------------------------------------------------------------------
# 2. Run a Simulated Trace
# ---------------------------------------------------------------------------


def example_1_run_trace() -> dict[str, Any]:
    """Example 1: Create and inspect a simulated trace."""
    print("\n" + "=" * 70)
    print("EXAMPLE 1: Simulated Trace")
    print("=" * 70)

    trace = create_mock_trace(
        trace_id="trace-001",
        agent_name="recommendation-engine",
        duration_ms=250.0,
        cost_usd=0.025,
        output='{"recommendations": ["item-1", "item-2", "item-3"], "confidence": 0.95}',
    )

    print(f"\nTrace ID: {trace['trace_id']}")
    print(f"Agent: {trace['agent_name']}")
    print(f"Duration: {trace['duration_ms']}ms")
    print(f"Cost: ${trace['total_cost_usd']:.4f}")
    print(f"Output: {trace['spans'][0]['output'][:80]}...")

    return trace


# ---------------------------------------------------------------------------
# 3. Create and Run Evaluations
# ---------------------------------------------------------------------------


def example_2_run_evaluations(trace: dict[str, Any]) -> list[EvalResult]:
    """Example 2: Create and run multiple evaluations on a trace."""
    print("\n" + "=" * 70)
    print("EXAMPLE 2: Running Evaluations")
    print("=" * 70)

    # Create evaluation runner
    runner = EvaluationRunner()

    # Add diverse evaluators
    runner.add_evaluator(
        ContainsKeywords(keywords=["recommendations", "confidence"], require_all=True)
    )

    runner.add_evaluator(
        JsonSchemaValid(
            schema={
                "type": "object",
                "properties": {
                    "recommendations": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["recommendations", "confidence"],
            }
        )
    )

    runner.add_evaluator(CostThreshold(max_cost_usd=0.05))
    runner.add_evaluator(LatencyThreshold(max_latency_ms=500.0))

    # Run evaluations
    results = runner.run(trace)

    print(f"\nEvaluations for {trace['trace_id']}:")
    for result in results:
        print_eval_result(result)

    # Summary
    passed = sum(1 for r in results if r.passed)
    print(f"\nSummary: {passed}/{len(results)} evaluations passed")

    return results


# ---------------------------------------------------------------------------
# 4. Create a Dataset
# ---------------------------------------------------------------------------


def example_3_create_dataset(db_path: str = "./eval_demo.db") -> str:
    """Example 3: Create a dataset and add traces to it."""
    print("\n" + "=" * 70)
    print("EXAMPLE 3: Creating a Dataset")
    print("=" * 70)

    storage = DatasetStorage(db_path=db_path)

    # Create dataset
    dataset_id = storage.create_dataset(
        name="recommendation-engine-tests",
        description="Evaluation dataset for recommendation engine traces",
    )

    print(f"\nCreated dataset: {dataset_id}")

    # Create and add multiple traces
    traces = [
        create_mock_trace(
            f"trace-{i:03d}",
            agent_name="recommendation-engine",
            duration_ms=100.0 + i * 10,
            cost_usd=0.01 + i * 0.001,
            output=json.dumps({
                "recommendations": [f"item-{j}" for j in range(3)],
                "confidence": 0.8 + (i % 20) * 0.01,
            }),
        )
        for i in range(10)
    ]

    print(f"\nAdding {len(traces)} traces to dataset...")
    for trace in traces:
        storage.add_trace_to_dataset(dataset_id, trace["trace_id"], trace)

    # Verify
    dataset_traces = storage.get_dataset_traces(dataset_id)
    print(f"Dataset now contains {len(dataset_traces)} traces")

    return dataset_id


# ---------------------------------------------------------------------------
# 5. Run Dataset Evaluation
# ---------------------------------------------------------------------------


def example_4_evaluate_dataset(
    dataset_id: str, db_path: str = "./eval_demo.db"
) -> None:
    """Example 4: Run evaluations across all traces in a dataset."""
    print("\n" + "=" * 70)
    print("EXAMPLE 4: Evaluating a Dataset")
    print("=" * 70)

    storage = DatasetStorage(db_path=db_path)
    eval_storage = EvaluationStorage(db_path=db_path)

    # Get all traces in dataset
    traces = storage.get_dataset_traces(dataset_id)
    print(f"\nEvaluating {len(traces)} traces...")

    # Create runner
    runner = EvaluationRunner()
    runner.add_evaluator(
        ContainsKeywords(keywords=["recommendations", "confidence"])
    )
    runner.add_evaluator(CostThreshold(max_cost_usd=0.05))
    runner.add_evaluator(LatencyThreshold(max_latency_ms=500.0))

    # Evaluate all traces
    all_results = runner.run_batch(traces)

    # Save and display results
    for trace, results in zip(traces, all_results):
        for result in results:
            eval_storage.save_evaluation(trace["trace_id"], {
                "trace_id": result.trace_id,
                "evaluator_name": result.evaluator_name,
                "passed": result.passed,
                "score": result.score,
                "details": result.details,
            })

    # Summary statistics
    summary = runner.get_summary(all_results)
    print(f"\nDataset Evaluation Summary:")
    print(f"  Total Evaluations: {summary['total_evals']}")
    print(f"  Passed: {summary['passed']}")
    print(f"  Failed: {summary['failed']}")
    print(f"  Pass Rate: {summary['pass_rate']:.1%}")

    # Per-evaluator breakdown
    print(f"\nPer-Evaluator Breakdown:")
    for evaluator, count in summary.get("by_evaluator", {}).items():
        print(f"  {evaluator}: {count['passed']}/{count['total']} passed")


# ---------------------------------------------------------------------------
# 6. Advanced: Custom Evaluation Criteria
# ---------------------------------------------------------------------------


class ConfidenceThreshold:
    """Custom evaluator: Check if confidence is above threshold."""

    def __init__(self, min_confidence: float = 0.8):
        self.min_confidence = min_confidence

    def evaluate(self, trace: dict[str, Any]) -> EvalResult:
        """Evaluate trace confidence."""
        try:
            output_str = trace["spans"][0].get("output", "")
            output = json.loads(output_str)
            confidence = output.get("confidence", 0.0)

            passed = confidence >= self.min_confidence
            score = min(1.0, confidence / 1.0)

            return EvalResult(
                trace_id=trace["trace_id"],
                evaluator_name="confidence_threshold",
                passed=passed,
                score=score,
                details=f"Confidence: {confidence:.2%} (threshold: {self.min_confidence:.2%})",
            )
        except Exception as e:
            return EvalResult(
                trace_id=trace["trace_id"],
                evaluator_name="confidence_threshold",
                passed=False,
                score=0.0,
                details=f"Error evaluating confidence: {e}",
            )


def example_5_custom_evaluator(trace: dict[str, Any]) -> None:
    """Example 5: Use a custom evaluator."""
    print("\n" + "=" * 70)
    print("EXAMPLE 5: Custom Evaluator")
    print("=" * 70)

    runner = EvaluationRunner()
    runner.add_evaluator(ConfidenceThreshold(min_confidence=0.85))

    results = runner.run(trace)
    print(f"\nCustom evaluator results:")
    for result in results:
        print_eval_result(result)


# ---------------------------------------------------------------------------
# Main Entry Point
# ---------------------------------------------------------------------------


def main() -> None:
    """Run all examples."""
    print("\n" + "#" * 70)
    print("# FLOWLENS EVALUATION ENGINE — COMPLETE PIPELINE DEMO")
    print("#" * 70)

    # Example 1: Create a trace
    trace = example_1_run_trace()

    # Example 2: Run evaluations
    results = example_2_run_evaluations(trace)

    # Example 3: Create a dataset
    dataset_id = example_3_create_dataset()

    # Example 4: Evaluate the dataset
    example_4_evaluate_dataset(dataset_id)

    # Example 5: Custom evaluator
    example_5_custom_evaluator(trace)

    print("\n" + "#" * 70)
    print("# EVALUATION PIPELINE COMPLETE")
    print("#" * 70 + "\n")


if __name__ == "__main__":
    main()
