"""
Tests for Cost Intelligence: forecasting, budget management, breakdown, and API endpoints.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from flowlens.analysis.cost_breakdown import CostBreakdown
from flowlens.analysis.cost_forecast import CostForecaster, _linear_regression
from flowlens.server.app import create_app
from flowlens.server.storage import TraceStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_trace(
    trace_id: str,
    service: str = "svc-a",
    cost: float = 0.01,
    tokens: int = 500,
    start_time: float | None = None,
    has_errors: bool = False,
    spans: list | None = None,
) -> dict:
    ts = start_time if start_time is not None else time.time()
    default_spans = [
        {
            "span_id": f"{trace_id}_s1",
            "trace_id": trace_id,
            "parent_span_id": None,
            "name": "llm_call",
            "kind": "llm",
            "status": "ok",
            "start_time": ts,
            "end_time": ts + 1.0,
            "duration_ms": 1000.0,
            "attributes": {"model": "gpt-4"},
            "events": [],
            "token_usage": {
                "input_tokens": tokens,
                "output_tokens": 50,
                "total_cost_usd": cost,
            },
        }
    ]
    return {
        "trace_id": trace_id,
        "service_name": service,
        "start_time": ts,
        "end_time": ts + 1.0,
        "duration_ms": 1000.0,
        "span_count": len(spans or default_spans),
        "total_tokens": tokens,
        "total_cost_usd": cost,
        "has_errors": has_errors,
        "error_count": 1 if has_errors else 0,
        "metadata": {},
        "spans": spans if spans is not None else default_spans,
    }


def _daily_records(days_costs: list[float]) -> list[dict]:
    """
    Build pre-aggregated daily records from a list of costs.

    Index 0 = oldest day, last index = most recent day.
    Timestamps are spaced 86400 s apart, ending yesterday.
    """
    now = time.time()
    records = []
    for i, cost in enumerate(days_costs):
        offset = (len(days_costs) - 1 - i) * 86400
        ts = now - offset
        records.append(
            {
                "start_time": ts,
                "total_cost_usd": cost,
            }
        )
    return records


# ===========================================================================
# CostForecaster
# ===========================================================================


class TestLinearRegression:
    def test_perfect_line(self):
        x = [0.0, 1.0, 2.0, 3.0]
        y = [1.0, 2.0, 3.0, 4.0]
        slope, intercept, r2 = _linear_regression(x, y)
        assert abs(slope - 1.0) < 1e-9
        assert abs(intercept - 1.0) < 1e-9
        assert abs(r2 - 1.0) < 1e-9

    def test_flat_line(self):
        x = [0.0, 1.0, 2.0]
        y = [5.0, 5.0, 5.0]
        slope, intercept, r2 = _linear_regression(x, y)
        assert abs(slope) < 1e-9
        assert abs(intercept - 5.0) < 1e-9

    def test_single_point(self):
        slope, intercept, r2 = _linear_regression([0.0], [3.0])
        assert slope == 0.0
        assert intercept == 3.0
        assert r2 == 0.0


class TestCostForecaster:
    def setup_method(self):
        self.fc = CostForecaster()

    def test_empty_traces(self):
        result = self.fc.forecast([])
        assert result.projected_daily_cost == 0.0
        assert result.projected_monthly_cost == 0.0
        assert result.trend == "stable"
        assert result.confidence_interval == (0.0, 0.0)

    def test_increasing_trend(self):
        # Costs clearly increasing: 1, 2, 3, 4, 5 dollars/day
        records = _daily_records([1.0, 2.0, 3.0, 4.0, 5.0])
        result = self.fc.forecast(records)
        assert result.trend == "increasing"
        assert result.projected_daily_cost > 5.0
        assert result.slope > 0

    def test_decreasing_trend(self):
        records = _daily_records([5.0, 4.0, 3.0, 2.0, 1.0])
        result = self.fc.forecast(records)
        assert result.trend == "decreasing"
        assert result.slope < 0

    def test_stable_trend(self):
        records = _daily_records([3.0, 3.01, 2.99, 3.0, 3.0])
        result = self.fc.forecast(records)
        assert result.trend == "stable"

    def test_projected_monthly_is_daily_times_30(self):
        records = _daily_records([2.0, 2.0, 2.0, 2.0, 2.0])
        result = self.fc.forecast(records)
        assert abs(result.projected_monthly_cost - result.projected_daily_cost * 30) < 1e-4

    def test_confidence_interval_ordered(self):
        records = _daily_records([1.0, 2.0, 3.0, 4.0, 5.0])
        result = self.fc.forecast(records)
        lo, hi = result.confidence_interval
        assert lo <= result.projected_daily_cost <= hi

    def test_to_dict_keys(self):
        records = _daily_records([1.0, 2.0])
        d = self.fc.forecast(records).to_dict()
        for key in ("projected_daily_cost", "projected_monthly_cost", "trend",
                    "confidence_interval", "days_of_data", "slope", "r_squared"):
            assert key in d

    def test_linear_forecast_accuracy(self):
        """With a perfect linear cost series, forecast should be close to expected."""
        # Cost increases by $1/day; after 5 days the next day should be ~$6
        records = _daily_records([1.0, 2.0, 3.0, 4.0, 5.0])
        result = self.fc.forecast(records)
        # Expected next-day cost = 6.0; allow some tolerance
        assert abs(result.projected_daily_cost - 6.0) < 0.5


class TestDaysUntilBudget:
    def setup_method(self):
        self.fc = CostForecaster()

    def test_budget_already_exceeded(self):
        records = _daily_records([10.0, 10.0, 10.0])
        result = self.fc.days_until_budget(records, budget_usd=5.0)
        assert result == 0.0

    def test_returns_positive_days(self):
        records = _daily_records([1.0, 1.0, 1.0])
        # Spent 3, budget is 100 → still 97 left, ~97 days at $1/day
        result = self.fc.days_until_budget(records, budget_usd=100.0)
        assert result is not None
        assert result > 0

    def test_empty_traces_returns_none(self):
        result = self.fc.days_until_budget([], budget_usd=100.0)
        assert result is None

    def test_zero_budget(self):
        records = _daily_records([1.0, 2.0])
        result = self.fc.days_until_budget(records, budget_usd=0.0)
        assert result == 0.0


class TestAnomalyDetection:
    def setup_method(self):
        self.fc = CostForecaster()

    def test_no_anomaly_uniform(self):
        # All same cost → no anomaly
        now = time.time()
        traces = [
            {"start_time": now - i * 3600, "total_cost_usd": 1.0}
            for i in range(5)
        ]
        result = self.fc.detect_cost_anomaly_window(traces, window_hours=1)
        assert result == []

    def test_detects_spike(self):
        now = time.time()
        # 10 normal hours, 1 spike hour
        traces = [
            {"start_time": now - i * 3600, "total_cost_usd": 1.0}
            for i in range(10)
        ]
        # Add a spike in a distinct window
        traces.append({"start_time": now - 11 * 3600, "total_cost_usd": 100.0})
        result = self.fc.detect_cost_anomaly_window(traces, window_hours=1)
        assert len(result) > 0
        # The spike window should have highest z_score
        z_scores = [r["z_score"] for r in result]
        assert max(z_scores) > 2.0

    def test_empty_traces(self):
        result = self.fc.detect_cost_anomaly_window([], window_hours=24)
        assert result == []

    def test_anomaly_dict_keys(self):
        now = time.time()
        traces = [{"start_time": now - i * 3600, "total_cost_usd": 1.0} for i in range(3)]
        traces.append({"start_time": now - 4 * 3600, "total_cost_usd": 50.0})
        result = self.fc.detect_cost_anomaly_window(traces, window_hours=1)
        if result:
            for key in ("window_start", "window_end", "total_cost", "z_score"):
                assert key in result[0]


# ===========================================================================
# CostBreakdown
# ===========================================================================


class TestCostBreakdownByModel:
    def setup_method(self):
        self.cb = CostBreakdown()

    def _traces_with_model(self) -> list[dict]:
        return [
            _make_trace(
                "t1",
                cost=0.01,
                tokens=100,
                spans=[
                    {
                        "span_id": "s1",
                        "trace_id": "t1",
                        "parent_span_id": None,
                        "name": "gpt4_call",
                        "kind": "llm",
                        "status": "ok",
                        "start_time": time.time(),
                        "end_time": time.time() + 1,
                        "duration_ms": 1000,
                        "attributes": {"model": "gpt-4"},
                        "events": [],
                        "token_usage": {"input_tokens": 80, "output_tokens": 20, "total_cost_usd": 0.01},
                    }
                ],
            ),
            _make_trace(
                "t2",
                cost=0.002,
                tokens=50,
                spans=[
                    {
                        "span_id": "s2",
                        "trace_id": "t2",
                        "parent_span_id": None,
                        "name": "haiku_call",
                        "kind": "llm",
                        "status": "ok",
                        "start_time": time.time(),
                        "end_time": time.time() + 0.5,
                        "duration_ms": 500,
                        "attributes": {"model": "claude-haiku"},
                        "events": [],
                        "token_usage": {"input_tokens": 40, "output_tokens": 10, "total_cost_usd": 0.002},
                    }
                ],
            ),
        ]

    def test_by_model_keys(self):
        result = self.cb.by_model(self._traces_with_model())
        assert "gpt-4" in result
        assert "claude-haiku" in result

    def test_by_model_fields(self):
        result = self.cb.by_model(self._traces_with_model())
        gpt = result["gpt-4"]
        for field in ("cost", "tokens", "count", "avg_cost_per_call"):
            assert field in gpt

    def test_by_model_counts(self):
        result = self.cb.by_model(self._traces_with_model())
        assert result["gpt-4"]["count"] == 1
        assert abs(result["gpt-4"]["cost"] - 0.01) < 1e-6

    def test_by_model_avg_cost(self):
        result = self.cb.by_model(self._traces_with_model())
        gpt = result["gpt-4"]
        assert abs(gpt["avg_cost_per_call"] - gpt["cost"] / gpt["count"]) < 1e-8

    def test_no_model_spans_excluded(self):
        trace = _make_trace(
            "t3",
            spans=[
                {
                    "span_id": "s3",
                    "trace_id": "t3",
                    "parent_span_id": None,
                    "name": "no_model",
                    "kind": "tool",
                    "status": "ok",
                    "start_time": time.time(),
                    "end_time": time.time() + 1,
                    "duration_ms": 1000,
                    "attributes": {},
                    "events": [],
                }
            ],
        )
        result = self.cb.by_model([trace])
        assert result == {}


class TestCostBreakdownByService:
    def setup_method(self):
        self.cb = CostBreakdown()

    def test_by_service_basic(self):
        traces = [
            _make_trace("t1", service="alpha", cost=0.01),
            _make_trace("t2", service="beta", cost=0.02),
            _make_trace("t3", service="alpha", cost=0.03),
        ]
        result = self.cb.by_service(traces)
        assert "alpha" in result
        assert "beta" in result
        assert abs(result["alpha"]["cost"] - 0.04) < 1e-6
        assert result["alpha"]["traces"] == 2

    def test_error_rate_calculation(self):
        traces = [
            _make_trace("t1", service="svc", has_errors=True),
            _make_trace("t2", service="svc", has_errors=False),
        ]
        result = self.cb.by_service(traces)
        assert abs(result["svc"]["error_rate"] - 0.5) < 1e-4

    def test_by_service_fields(self):
        traces = [_make_trace("t1")]
        result = self.cb.by_service(traces)
        svc = list(result.values())[0]
        for field in ("cost", "tokens", "traces", "error_rate"):
            assert field in svc


class TestCostBreakdownBySpanKind:
    def setup_method(self):
        self.cb = CostBreakdown()

    def test_by_kind_basic(self):
        traces = [
            _make_trace(
                "t1",
                spans=[
                    {
                        "span_id": "s1",
                        "trace_id": "t1",
                        "parent_span_id": None,
                        "name": "llm",
                        "kind": "llm",
                        "status": "ok",
                        "start_time": time.time(),
                        "end_time": time.time() + 1,
                        "duration_ms": 1000,
                        "attributes": {},
                        "events": [],
                        "token_usage": {"input_tokens": 100, "output_tokens": 50, "total_cost_usd": 0.01},
                    },
                    {
                        "span_id": "s2",
                        "trace_id": "t1",
                        "parent_span_id": "s1",
                        "name": "tool_call",
                        "kind": "tool",
                        "status": "ok",
                        "start_time": time.time(),
                        "end_time": time.time() + 0.5,
                        "duration_ms": 500,
                        "attributes": {},
                        "events": [],
                    },
                ],
            )
        ]
        result = self.cb.by_span_kind(traces)
        assert "llm" in result
        assert "tool" in result
        assert result["llm"]["cost"] == pytest.approx(0.01, abs=1e-6)
        assert result["llm"]["count"] == 1

    def test_by_kind_fields(self):
        traces = [_make_trace("t1")]
        result = self.cb.by_span_kind(traces)
        for kind_data in result.values():
            for field in ("cost", "tokens", "count"):
                assert field in kind_data


class TestOptimizationSuggestions:
    def setup_method(self):
        self.cb = CostBreakdown()

    def _make_expensive_trace(self) -> dict:
        return _make_trace(
            "expensive",
            cost=1.0,
            tokens=5000,
            spans=[
                {
                    "span_id": "exp_s1",
                    "trace_id": "expensive",
                    "parent_span_id": None,
                    "name": "opus_call",
                    "kind": "llm",
                    "status": "ok",
                    "start_time": time.time(),
                    "end_time": time.time() + 2,
                    "duration_ms": 2000,
                    "attributes": {"model": "claude-3-opus"},
                    "events": [],
                    "token_usage": {"input_tokens": 4800, "output_tokens": 50, "total_cost_usd": 1.0},
                }
            ],
        )

    def test_returns_list(self):
        traces = [self._make_expensive_trace()]
        result = self.cb.optimization_suggestions(traces)
        assert isinstance(result, list)

    def test_model_switch_suggestion(self):
        traces = [self._make_expensive_trace()]
        result = self.cb.optimization_suggestions(traces)
        types = [s["type"] for s in result]
        assert "model_switch" in types

    def test_context_reduction_suggestion(self):
        # Very high input:output ratio (4800:50 = 96:1)
        traces = [self._make_expensive_trace()]
        result = self.cb.optimization_suggestions(traces)
        types = [s["type"] for s in result]
        assert "context_reduction" in types

    def test_caching_suggestion(self):
        # Same span name called 3+ times within a single trace
        now = time.time()
        spans = [
            {
                "span_id": f"s{i}",
                "trace_id": "t_cache",
                "parent_span_id": None,
                "name": "repeated_tool",
                "kind": "tool",
                "status": "ok",
                "start_time": now + i,
                "end_time": now + i + 0.1,
                "duration_ms": 100,
                "attributes": {},
                "events": [],
                "token_usage": {"input_tokens": 10, "output_tokens": 10, "total_cost_usd": 0.001},
            }
            for i in range(4)
        ]
        trace = _make_trace("t_cache", spans=spans, cost=0.004)
        result = self.cb.optimization_suggestions([trace])
        types = [s["type"] for s in result]
        assert "caching" in types

    def test_suggestions_sorted_by_savings(self):
        traces = [self._make_expensive_trace()]
        result = self.cb.optimization_suggestions(traces)
        savings = [s.get("estimated_monthly_savings_usd", 0.0) for s in result]
        assert savings == sorted(savings, reverse=True)

    def test_suggestion_fields(self):
        traces = [self._make_expensive_trace()]
        result = self.cb.optimization_suggestions(traces)
        for s in result:
            assert "type" in s
            assert "description" in s
            assert "estimated_monthly_savings_usd" in s

    def test_empty_traces(self):
        result = self.cb.optimization_suggestions([])
        assert result == []


# ===========================================================================
# Storage new methods
# ===========================================================================


class TestStorageCostMethods:
    @pytest.fixture
    def store(self, tmp_path):
        s = TraceStore(db_path=tmp_path / "test.db")
        yield s
        s.close()

    def _populate(self, store: TraceStore, n: int = 5) -> None:
        now = time.time()
        for i in range(n):
            trace = _make_trace(
                f"trace_{i}",
                cost=float(i + 1) * 0.01,
                tokens=(i + 1) * 100,
                start_time=now - i * 86400,
            )
            store.save_trace(trace)

    def test_get_daily_costs_empty(self, store):
        result = store.get_daily_costs(days=30)
        assert result == []

    def test_get_daily_costs_returns_list(self, store):
        self._populate(store)
        result = store.get_daily_costs(days=30)
        assert isinstance(result, list)
        assert len(result) > 0

    def test_get_daily_costs_fields(self, store):
        self._populate(store)
        result = store.get_daily_costs(days=30)
        for row in result:
            for key in ("date", "total_cost_usd", "total_tokens", "trace_count"):
                assert key in row

    def test_get_daily_costs_ordering(self, store):
        self._populate(store)
        result = store.get_daily_costs(days=30)
        dates = [r["date"] for r in result]
        assert dates == sorted(dates)

    def test_get_cost_by_model_empty(self, store):
        result = store.get_cost_by_model(days=30)
        assert result == []

    def test_get_cost_by_model_with_data(self, store):
        trace = _make_trace("tm1")
        store.save_trace(trace)
        result = store.get_cost_by_model(days=30)
        assert isinstance(result, list)
        # May be empty if no token_usage recorded (depends on span data)

    def test_get_cost_by_model_fields(self, store):
        trace = _make_trace("tm2", spans=[
            {
                "span_id": "sm1",
                "trace_id": "tm2",
                "parent_span_id": None,
                "name": "llm_call",
                "kind": "llm",
                "status": "ok",
                "start_time": time.time(),
                "end_time": time.time() + 1,
                "duration_ms": 1000,
                "attributes": {"model": "gpt-4"},
                "events": [],
                "token_usage": {"input_tokens": 100, "output_tokens": 50, "total_cost_usd": 0.01},
            }
        ])
        store.save_trace(trace)
        result = store.get_cost_by_model(days=30)
        if result:
            for row in result:
                for key in ("model", "total_cost_usd", "total_tokens", "call_count", "avg_cost_per_call"):
                    assert key in row


# ===========================================================================
# API Endpoints
# ===========================================================================


@pytest.fixture
def client(tmp_path):
    app = create_app(db_path=str(tmp_path / "test.db"))
    return TestClient(app)


@pytest.fixture
def populated_client(tmp_path):
    app = create_app(db_path=str(tmp_path / "test.db"))
    client = TestClient(app)
    # Ingest several traces spread over multiple "days" (same day in test, but enough data)
    now = time.time()
    for i in range(5):
        trace = _make_trace(f"api_trace_{i}", cost=0.01 * (i + 1), start_time=now - i * 3600)
        client.post("/v1/traces/ingest", json=trace)
    return client


class TestCostForecastEndpoint:
    def test_forecast_returns_200(self, client):
        resp = client.get("/v1/cost/forecast")
        assert resp.status_code == 200

    def test_forecast_with_data(self, populated_client):
        resp = populated_client.get("/v1/cost/forecast?days=30")
        assert resp.status_code == 200
        data = resp.json()
        assert "projected_daily_cost" in data
        assert "projected_monthly_cost" in data
        assert "trend" in data
        assert "confidence_interval" in data

    def test_forecast_empty_db(self, client):
        resp = client.get("/v1/cost/forecast")
        assert resp.status_code == 200
        data = resp.json()
        assert data["projected_daily_cost"] == 0.0
        assert data["trend"] == "stable"

    def test_forecast_invalid_days(self, client):
        resp = client.get("/v1/cost/forecast?days=0")
        assert resp.status_code == 422  # Pydantic validation

    def test_forecast_confidence_interval_structure(self, populated_client):
        data = populated_client.get("/v1/cost/forecast").json()
        ci = data["confidence_interval"]
        assert "lower" in ci
        assert "upper" in ci
        assert ci["lower"] <= data["projected_daily_cost"] <= ci["upper"]

    def test_forecast_returns_daily_costs_field(self, populated_client):
        data = populated_client.get("/v1/cost/forecast").json()
        assert "daily_costs" in data
        assert isinstance(data["daily_costs"], list)

    def test_forecast_daily_costs_have_date_and_cost(self, populated_client):
        data = populated_client.get("/v1/cost/forecast").json()
        for item in data["daily_costs"]:
            assert "date" in item
            assert "cost" in item
            assert item["cost"] >= 0

    def test_forecast_returns_forecast_field(self, populated_client):
        data = populated_client.get("/v1/cost/forecast?forecast_days=3").json()
        assert "forecast" in data
        assert isinstance(data["forecast"], list)

    def test_forecast_field_has_ci_bounds(self, populated_client):
        data = populated_client.get("/v1/cost/forecast?forecast_days=3").json()
        if data["forecast"]:
            item = data["forecast"][0]
            assert "date" in item
            assert "cost" in item
            assert "ci_lower" in item
            assert "ci_upper" in item
            assert item["ci_lower"] <= item["cost"] <= item["ci_upper"] + 1e-9

    def test_forecast_forecast_days_count(self, populated_client):
        data = populated_client.get("/v1/cost/forecast?forecast_days=5").json()
        assert len(data["forecast"]) == 5

    def test_forecast_has_daily_avg_and_monthly_projection(self, populated_client):
        data = populated_client.get("/v1/cost/forecast").json()
        assert "daily_avg_usd" in data
        assert "monthly_projection_usd" in data
        assert data["daily_avg_usd"] >= 0
        assert data["monthly_projection_usd"] >= 0

    def test_forecast_empty_db_returns_empty_arrays(self, client):
        data = client.get("/v1/cost/forecast?forecast_days=3").json()
        assert "daily_costs" in data
        assert "forecast" in data

    def test_forecast_invalid_forecast_days(self, client):
        resp = client.get("/v1/cost/forecast?forecast_days=0")
        assert resp.status_code == 422

    def test_forecast_forecast_days_max(self, client):
        resp = client.get("/v1/cost/forecast?forecast_days=30")
        assert resp.status_code == 200


class TestCostBudgetEndpoint:
    def test_budget_returns_200(self, client):
        resp = client.get("/v1/cost/budget?budget=1000")
        assert resp.status_code == 200

    def test_budget_missing_param(self, client):
        resp = client.get("/v1/cost/budget")
        assert resp.status_code == 422

    def test_budget_zero_not_allowed(self, client):
        resp = client.get("/v1/cost/budget?budget=0")
        assert resp.status_code == 422

    def test_budget_fields(self, populated_client):
        resp = populated_client.get("/v1/cost/budget?budget=100")
        assert resp.status_code == 200
        data = resp.json()
        for key in ("budget_usd", "total_spent_usd", "remaining_usd", "burn_rate_daily_usd", "trend"):
            assert key in data

    def test_budget_remaining_calculation(self, client):
        resp = client.get("/v1/cost/budget?budget=50.0")
        data = resp.json()
        assert abs(data["budget_usd"] - 50.0) < 1e-6
        # With empty DB, nothing is spent
        assert data["total_spent_usd"] == 0.0
        assert data["remaining_usd"] == 50.0

    def test_budget_with_data(self, populated_client):
        resp = populated_client.get("/v1/cost/budget?budget=1000")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_spent_usd"] >= 0.0
        assert data["remaining_usd"] <= 1000.0


class TestCostOptimizationEndpoint:
    def test_optimization_returns_200(self, client):
        resp = client.get("/v1/cost/optimization")
        assert resp.status_code == 200

    def test_optimization_fields(self, client):
        data = client.get("/v1/cost/optimization").json()
        for key in ("suggestions", "total_estimated_monthly_savings_usd",
                    "by_model", "by_service", "by_span_kind"):
            assert key in data

    def test_optimization_suggestions_is_list(self, client):
        data = client.get("/v1/cost/optimization").json()
        assert isinstance(data["suggestions"], list)

    def test_optimization_with_data(self, populated_client):
        resp = populated_client.get("/v1/cost/optimization")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["suggestions"], list)
        assert data["total_estimated_monthly_savings_usd"] >= 0.0

    def test_optimization_by_model_is_dict(self, populated_client):
        data = populated_client.get("/v1/cost/optimization").json()
        assert isinstance(data["by_model"], dict)

    def test_optimization_by_service_is_dict(self, populated_client):
        data = populated_client.get("/v1/cost/optimization").json()
        assert isinstance(data["by_service"], dict)

    def test_optimization_by_span_kind_is_dict(self, populated_client):
        data = populated_client.get("/v1/cost/optimization").json()
        assert isinstance(data["by_span_kind"], dict)


# ===========================================================================
# Existing cost endpoints still work (regression guard)
# ===========================================================================


class TestExistingCostEndpoints:
    def test_cost_breakdown_still_works(self, client):
        resp = client.get("/v1/cost/breakdown")
        assert resp.status_code == 200

    def test_cost_trends_still_works(self, client):
        resp = client.get("/v1/cost/trends")
        assert resp.status_code == 200
