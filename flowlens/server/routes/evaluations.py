"""
Evaluation engine route handlers.

Endpoints:
- POST   /v1/evaluations/run                      — run evaluator(s) against trace(s)
- GET    /v1/evaluations/results                  — list evaluation results
- GET    /v1/traces/{trace_id}/evaluations        — evaluations for a specific trace
- POST   /v1/datasets                             — create dataset
- GET    /v1/datasets                             — list datasets
- GET    /v1/datasets/{dataset_id}                — get dataset with traces
- POST   /v1/datasets/{dataset_id}/evaluate       — run evaluators against dataset
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..storage import TraceStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Built-in evaluators
# ---------------------------------------------------------------------------

_EVALUATORS: dict[str, Any] = {}


def _register(name: str):  # type: ignore[return]
    """Decorator that registers an evaluator function by name."""

    def decorator(fn):  # type: ignore[return]
        _EVALUATORS[name] = fn
        return fn

    return decorator


@_register("cost_threshold")
def _eval_cost_threshold(
    trace: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Pass if trace total_cost_usd <= max_cost_usd, else fail."""
    max_cost = float(config.get("max_cost_usd", 0.10))
    cost = float(trace.get("total_cost_usd") or 0.0)
    passed = cost <= max_cost
    score = 1.0 if passed else max(0.0, 1.0 - (cost - max_cost) / max(max_cost, 1e-9))
    return {
        "score": round(score, 4),
        "label": "pass" if passed else "fail",
        "reason": (f"Cost ${cost:.6f} {'<=' if passed else '>'} threshold ${max_cost:.6f}"),
    }


@_register("latency_threshold")
def _eval_latency_threshold(
    trace: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Pass if trace duration_ms <= max_latency_ms, else fail."""
    max_ms = float(config.get("max_latency_ms", 30_000))
    duration = float(trace.get("duration_ms") or 0.0)
    passed = duration <= max_ms
    score = 1.0 if passed else max(0.0, 1.0 - (duration - max_ms) / max(max_ms, 1e-9))
    return {
        "score": round(score, 4),
        "label": "pass" if passed else "fail",
        "reason": (f"Latency {duration:.1f}ms {'<=' if passed else '>'} threshold {max_ms:.1f}ms"),
    }


@_register("no_errors")
def _eval_no_errors(
    trace: dict[str, Any],
    config: dict[str, Any],  # noqa: ARG001
) -> dict[str, Any]:
    """Pass if the trace has no error spans."""
    has_errors = bool(trace.get("has_errors"))
    error_count = int(trace.get("error_count") or 0)
    return {
        "score": 0.0 if has_errors else 1.0,
        "label": "fail" if has_errors else "pass",
        "reason": (f"{error_count} error(s) found" if has_errors else "No errors detected"),
    }


@_register("token_budget")
def _eval_token_budget(
    trace: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Pass if trace total_tokens <= max_tokens, else fail."""
    max_tokens = int(config.get("max_tokens", 100_000))
    tokens = int(trace.get("total_tokens") or 0)
    passed = tokens <= max_tokens
    score = 1.0 if passed else max(0.0, 1.0 - (tokens - max_tokens) / max(max_tokens, 1))
    return {
        "score": round(score, 4),
        "label": "pass" if passed else "fail",
        "reason": f"Tokens {tokens} {'<=' if passed else '>'} budget {max_tokens}",
    }


def _run_single_evaluation(
    trace: dict[str, Any],
    evaluator_name: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Run one evaluator against one trace; return a result dict."""
    fn = _EVALUATORS.get(evaluator_name)
    if fn is None:
        raise ValueError(
            f"Unknown evaluator {evaluator_name!r}. " f"Available: {sorted(_EVALUATORS)}"
        )
    outcome = fn(trace, config)
    return {
        "eval_id": uuid.uuid4().hex,
        "trace_id": trace["trace_id"],
        "evaluator_name": evaluator_name,
        "score": outcome["score"],
        "label": outcome["label"],
        "reason": outcome.get("reason"),
        "metadata": {"config": config},
        "created_at": time.time(),
    }


# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------


class EvalRunRequest(BaseModel):
    """Payload for POST /v1/evaluations/run."""

    evaluator: str = Field(..., min_length=1, max_length=128, description="Evaluator name")
    config: dict[str, Any] = Field(default_factory=dict)
    trace_ids: list[str] = Field(..., min_length=1, max_length=200)


class DatasetCreateRequest(BaseModel):
    """Payload for POST /v1/datasets."""

    name: str = Field(..., min_length=1, max_length=256)
    description: str = Field("", max_length=2048)
    trace_ids: list[str] = Field(default_factory=list, max_length=10_000)


class DatasetEvalRequest(BaseModel):
    """Payload for POST /v1/datasets/{dataset_id}/evaluate."""

    evaluators: list[dict[str, Any]] = Field(
        ...,
        min_length=1,
        max_length=20,
        description="List of {name, config} dicts",
    )


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------


def create_evaluations_router(store: TraceStore) -> APIRouter:
    """Create and return the evaluations router."""
    router = APIRouter()

    # ------------------------------------------------------------------ #
    # POST /v1/evaluations/run
    # ------------------------------------------------------------------ #

    @router.post("/v1/evaluations/run", status_code=201)
    async def run_evaluations(req: EvalRunRequest) -> dict[str, Any]:
        """Run an evaluator against one or more traces.

        Returns results for every trace_id requested.  If a trace is not
        found it is included with ``score=null`` and ``label="error"``.
        """
        results: list[dict[str, Any]] = []
        errors: list[str] = []

        for trace_id in req.trace_ids:
            trace = store.get_trace(trace_id)
            if trace is None:
                results.append(
                    {
                        "eval_id": None,
                        "trace_id": trace_id,
                        "evaluator_name": req.evaluator,
                        "score": None,
                        "label": "error",
                        "reason": f"Trace {trace_id!r} not found",
                    }
                )
                errors.append(trace_id)
                continue

            try:
                eval_result = _run_single_evaluation(trace, req.evaluator, req.config)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
            except Exception:
                logger.exception("Evaluator %s failed on trace %s", req.evaluator, trace_id)
                results.append(
                    {
                        "eval_id": None,
                        "trace_id": trace_id,
                        "evaluator_name": req.evaluator,
                        "score": None,
                        "label": "error",
                        "reason": "Evaluator raised an unexpected error",
                    }
                )
                errors.append(trace_id)
                continue

            try:
                store.save_evaluation(eval_result)
            except Exception:
                logger.exception("Failed to persist evaluation for trace %s", trace_id)

            results.append(eval_result)

        return {"results": results, "error_count": len(errors)}

    # ------------------------------------------------------------------ #
    # GET /v1/evaluations/results
    # ------------------------------------------------------------------ #

    @router.get("/v1/evaluations/results")
    async def list_evaluation_results(
        evaluator: str | None = Query(None, description="Filter by evaluator name"),
        limit: int = Query(50, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        """List recent evaluation results, optionally filtered by evaluator."""
        try:
            return store.list_evaluations(limit=limit, evaluator_name=evaluator)
        except Exception:
            logger.exception("Failed to list evaluations")
            raise HTTPException(500, "Failed to retrieve evaluation results")

    # ------------------------------------------------------------------ #
    # GET /v1/traces/{trace_id}/evaluations
    # ------------------------------------------------------------------ #

    @router.get("/v1/traces/{trace_id}/evaluations")
    async def get_trace_evaluations(trace_id: str) -> list[dict[str, Any]]:
        """Return all evaluation results for a specific trace."""
        try:
            return store.get_evaluations_for_trace(trace_id)
        except Exception:
            logger.exception("Failed to get evaluations for trace %s", trace_id)
            raise HTTPException(500, "Failed to retrieve evaluations")

    # ------------------------------------------------------------------ #
    # POST /v1/datasets
    # ------------------------------------------------------------------ #

    @router.post("/v1/datasets", status_code=201)
    async def create_dataset(req: DatasetCreateRequest) -> dict[str, Any]:
        """Create a new named dataset and optionally populate it with traces."""
        try:
            dataset_id = store.create_dataset(req.name, req.description)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except Exception:
            logger.exception("Failed to create dataset %s", req.name)
            raise HTTPException(500, "Failed to create dataset")

        if req.trace_ids:
            try:
                store.add_to_dataset(dataset_id, req.trace_ids)
            except Exception:
                logger.exception("Failed to add traces to new dataset %s", dataset_id)

        dataset = store.get_dataset(dataset_id)
        return dataset or {"dataset_id": dataset_id, "name": req.name}

    # ------------------------------------------------------------------ #
    # GET /v1/datasets
    # ------------------------------------------------------------------ #

    @router.get("/v1/datasets")
    async def list_datasets() -> list[dict[str, Any]]:
        """List all datasets."""
        try:
            return store.list_datasets()
        except Exception:
            logger.exception("Failed to list datasets")
            raise HTTPException(500, "Failed to retrieve datasets")

    # ------------------------------------------------------------------ #
    # GET /v1/datasets/{dataset_id}
    # ------------------------------------------------------------------ #

    @router.get("/v1/datasets/{dataset_id}")
    async def get_dataset(dataset_id: str) -> dict[str, Any]:
        """Get dataset metadata and its associated traces."""
        dataset = store.get_dataset(dataset_id)
        if dataset is None:
            raise HTTPException(status_code=404, detail=f"Dataset {dataset_id!r} not found")
        try:
            traces = store.get_dataset_traces(dataset_id)
        except Exception:
            logger.exception("Failed to fetch traces for dataset %s", dataset_id)
            traces = []
        return {**dataset, "traces": traces}

    # ------------------------------------------------------------------ #
    # POST /v1/datasets/{dataset_id}/evaluate
    # ------------------------------------------------------------------ #

    @router.post("/v1/datasets/{dataset_id}/evaluate", status_code=201)
    async def evaluate_dataset(
        dataset_id: str,
        req: DatasetEvalRequest,
    ) -> dict[str, Any]:
        """Run one or more evaluators against every trace in a dataset.

        Returns a summary with all individual results.
        """
        dataset = store.get_dataset(dataset_id)
        if dataset is None:
            raise HTTPException(status_code=404, detail=f"Dataset {dataset_id!r} not found")

        traces = store.get_dataset_traces(dataset_id)
        if not traces:
            return {"dataset_id": dataset_id, "results": [], "summary": {}}

        all_results: list[dict[str, Any]] = []
        for ev_spec in req.evaluators:
            ev_name = ev_spec.get("name", "")
            ev_config = ev_spec.get("config", {})
            if not ev_name:
                continue
            for trace in traces:
                try:
                    eval_result = _run_single_evaluation(trace, ev_name, ev_config)
                except ValueError as exc:
                    raise HTTPException(status_code=400, detail=str(exc))
                except Exception:
                    logger.exception(
                        "Evaluator %s failed on trace %s during dataset eval",
                        ev_name,
                        trace["trace_id"],
                    )
                    eval_result = {
                        "eval_id": uuid.uuid4().hex,
                        "trace_id": trace["trace_id"],
                        "evaluator_name": ev_name,
                        "score": None,
                        "label": "error",
                        "reason": "Evaluator raised an unexpected error",
                        "metadata": {"config": ev_config},
                        "created_at": time.time(),
                    }
                try:
                    if eval_result.get("eval_id"):
                        store.save_evaluation(eval_result)
                except Exception:
                    logger.exception(
                        "Failed to persist dataset evaluation for trace %s",
                        trace["trace_id"],
                    )
                all_results.append(eval_result)

        # Build per-evaluator summary
        summary: dict[str, Any] = {}
        for ev_spec in req.evaluators:
            ev_name = ev_spec.get("name", "")
            if not ev_name:
                continue
            ev_results = [r for r in all_results if r["evaluator_name"] == ev_name]
            scored = [r for r in ev_results if r["score"] is not None]
            passes = sum(1 for r in ev_results if r.get("label") == "pass")
            summary[ev_name] = {
                "trace_count": len(ev_results),
                "pass_count": passes,
                "fail_count": len(ev_results) - passes,
                "avg_score": (
                    round(sum(r["score"] for r in scored) / len(scored), 4) if scored else None
                ),
            }

        return {
            "dataset_id": dataset_id,
            "results": all_results,
            "summary": summary,
        }

    # ------------------------------------------------------------------ #
    # GET /v1/evaluators  — list available evaluator names
    # ------------------------------------------------------------------ #

    @router.get("/v1/evaluators")
    async def list_evaluators() -> list[str]:
        """Return the names of all built-in evaluators."""
        return sorted(_EVALUATORS)

    return router
