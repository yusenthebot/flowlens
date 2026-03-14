"""
Tests for the FlowLens Alerting subsystem.

Covers:
- AlertRule / Alert model creation and serialisation
- AlertEngine condition evaluation (error_rate, cost, latency, tokens, pattern)
- Cooldown logic
- Webhook payload format (generic and Slack)
- Slack format detection
- Storage CRUD (alert_rules, alert_history)
- API endpoints via TestClient
"""

from __future__ import annotations

import asyncio
import json
import time
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from flowlens.alerting import AlertRule, Alert
from flowlens.alerting.engine import AlertEngine, _eval_threshold, _extract_metric, _check_pattern
from flowlens.alerting.webhooks import build_payload, _build_generic_payload, _build_slack_payload


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_trace(
    trace_id: str = "trace-1",
    duration_ms: float = 1000.0,
    total_cost_usd: float = 0.05,
    total_tokens: int = 5000,
    span_count: int = 10,
    error_count: int = 0,
    has_errors: bool = False,
    service_name: str = "test-svc",
    patterns: list | None = None,
) -> dict:
    return {
        "trace_id": trace_id,
        "service_name": service_name,
        "start_time": time.time() - duration_ms / 1000,
        "end_time": time.time(),
        "duration_ms": duration_ms,
        "span_count": span_count,
        "total_tokens": total_tokens,
        "total_cost_usd": total_cost_usd,
        "has_errors": has_errors,
        "error_count": error_count,
        "metadata": {},
        "spans": [],
        "patterns": patterns or [],
    }


def _run(coro):
    """Helper to run async code in tests."""
    return asyncio.run(coro)


# ===========================================================================
# AlertRule model tests
# ===========================================================================

class TestAlertRuleModel:
    def test_defaults(self):
        rule = AlertRule(name="r1", condition="error_rate > 0.1")
        assert rule.severity == "warning"
        assert rule.webhook_url is None
        assert rule.cooldown_seconds == 300
        assert rule.enabled is True

    def test_to_dict_roundtrip(self):
        rule = AlertRule(
            name="test-rule",
            condition="cost_per_trace > 1.0",
            severity="critical",
            webhook_url="https://example.com/hook",
            cooldown_seconds=60,
            enabled=False,
        )
        d = rule.to_dict()
        assert d["name"] == "test-rule"
        assert d["condition"] == "cost_per_trace > 1.0"
        assert d["severity"] == "critical"
        assert d["webhook_url"] == "https://example.com/hook"
        assert d["cooldown_seconds"] == 60
        assert d["enabled"] is False

        rule2 = AlertRule.from_dict(d)
        assert rule2.name == rule.name
        assert rule2.condition == rule.condition
        assert rule2.enabled is False


# ===========================================================================
# Alert model tests
# ===========================================================================

class TestAlertModel:
    def test_defaults(self):
        alert = Alert(rule_name="r1", severity="warning", message="test")
        assert alert.trace_id is None
        assert isinstance(alert.metrics, dict)
        assert alert.fired_at > 0

    def test_to_dict(self):
        alert = Alert(
            rule_name="high-cost",
            severity="critical",
            message="Cost exceeded",
            trace_id="t-123",
            metrics={"value": 2.5},
            fired_at=1234567890.0,
        )
        d = alert.to_dict()
        assert d["rule_name"] == "high-cost"
        assert d["trace_id"] == "t-123"
        assert d["metrics"] == {"value": 2.5}
        assert d["fired_at"] == 1234567890.0

    def test_from_dict_roundtrip(self):
        d = {
            "rule_name": "r",
            "severity": "info",
            "message": "msg",
            "trace_id": "t1",
            "metrics": {"x": 1},
            "fired_at": 9999.9,
        }
        alert = Alert.from_dict(d)
        assert alert.rule_name == "r"
        assert alert.metrics == {"x": 1}
        assert alert.fired_at == 9999.9


# ===========================================================================
# Condition evaluation helpers
# ===========================================================================

class TestEvalThreshold:
    def test_gt(self):
        assert _eval_threshold(0.2, ">", 0.1) is True
        assert _eval_threshold(0.05, ">", 0.1) is False

    def test_gte(self):
        assert _eval_threshold(0.1, ">=", 0.1) is True
        assert _eval_threshold(0.09, ">=", 0.1) is False

    def test_lt(self):
        assert _eval_threshold(50.0, "<", 100.0) is True
        assert _eval_threshold(150.0, "<", 100.0) is False

    def test_eq(self):
        assert _eval_threshold(5.0, "==", 5.0) is True
        assert _eval_threshold(5.1, "==", 5.0) is False

    def test_ne(self):
        assert _eval_threshold(5.1, "!=", 5.0) is True

    def test_unknown_op_raises(self):
        with pytest.raises(ValueError):
            _eval_threshold(1.0, "??", 0.5)


class TestExtractMetric:
    def test_error_rate_normal(self):
        trace = _make_trace(span_count=10, error_count=2)
        assert _extract_metric(trace, "error_rate") == pytest.approx(0.2)

    def test_error_rate_zero_spans(self):
        trace = _make_trace(span_count=0, error_count=0)
        assert _extract_metric(trace, "error_rate") == 0.0

    def test_cost_per_trace(self):
        trace = _make_trace(total_cost_usd=1.23)
        assert _extract_metric(trace, "cost_per_trace") == pytest.approx(1.23)

    def test_latency(self):
        trace = _make_trace(duration_ms=7500.0)
        assert _extract_metric(trace, "latency") == pytest.approx(7500.0)

    def test_tokens(self):
        trace = _make_trace(total_tokens=99999)
        assert _extract_metric(trace, "tokens") == pytest.approx(99999.0)

    def test_unknown_metric(self):
        trace = _make_trace()
        assert _extract_metric(trace, "unknown_metric") is None


class TestCheckPattern:
    def test_pattern_as_string(self):
        trace = _make_trace(patterns=["retry_storm", "context_overflow"])
        assert _check_pattern(trace, "retry_storm") is True
        assert _check_pattern(trace, "empty_response") is False

    def test_pattern_as_dict(self):
        trace = _make_trace(patterns=[{"pattern": "retry_storm", "severity": "critical"}])
        assert _check_pattern(trace, "retry_storm") is True
        assert _check_pattern(trace, "infinite_loop") is False

    def test_no_patterns(self):
        trace = _make_trace(patterns=[])
        assert _check_pattern(trace, "retry_storm") is False


# ===========================================================================
# AlertEngine — condition evaluation
# ===========================================================================

class TestAlertEngineConditions:
    def setup_method(self):
        self.engine = AlertEngine()

    def test_error_rate_fires(self):
        self.engine.add_rule(AlertRule(
            name="err-rate",
            condition="error_rate > 0.1",
            severity="critical",
        ))
        trace = _make_trace(span_count=10, error_count=5)  # 0.5 error rate
        alerts = _run(self.engine.check_trace(trace))
        assert len(alerts) == 1
        assert alerts[0].rule_name == "err-rate"
        assert alerts[0].severity == "critical"

    def test_error_rate_no_fire(self):
        self.engine.add_rule(AlertRule(
            name="err-rate",
            condition="error_rate > 0.5",
            severity="warning",
        ))
        trace = _make_trace(span_count=10, error_count=2)  # 0.2 error rate
        alerts = _run(self.engine.check_trace(trace))
        assert alerts == []

    def test_cost_fires(self):
        self.engine.add_rule(AlertRule(
            name="high-cost",
            condition="cost_per_trace > 0.5",
            severity="warning",
        ))
        trace = _make_trace(total_cost_usd=1.0)
        alerts = _run(self.engine.check_trace(trace))
        assert len(alerts) == 1
        assert alerts[0].rule_name == "high-cost"

    def test_latency_fires(self):
        self.engine.add_rule(AlertRule(
            name="slow",
            condition="latency > 5000",
            severity="warning",
        ))
        trace = _make_trace(duration_ms=10000.0)
        alerts = _run(self.engine.check_trace(trace))
        assert len(alerts) == 1

    def test_latency_no_fire(self):
        self.engine.add_rule(AlertRule(
            name="slow",
            condition="latency > 5000",
            severity="warning",
        ))
        trace = _make_trace(duration_ms=1000.0)
        alerts = _run(self.engine.check_trace(trace))
        assert alerts == []

    def test_tokens_fires(self):
        self.engine.add_rule(AlertRule(
            name="many-tokens",
            condition="tokens > 10000",
            severity="info",
        ))
        trace = _make_trace(total_tokens=50000)
        alerts = _run(self.engine.check_trace(trace))
        assert len(alerts) == 1

    def test_pattern_fires(self):
        self.engine.add_rule(AlertRule(
            name="retry-storm-alert",
            condition="pattern:retry_storm",
            severity="critical",
        ))
        trace = _make_trace(patterns=[{"pattern": "retry_storm"}])
        alerts = _run(self.engine.check_trace(trace))
        assert len(alerts) == 1
        assert "retry_storm" in alerts[0].message

    def test_pattern_no_fire(self):
        self.engine.add_rule(AlertRule(
            name="retry-storm-alert",
            condition="pattern:retry_storm",
            severity="critical",
        ))
        trace = _make_trace(patterns=[])
        alerts = _run(self.engine.check_trace(trace))
        assert alerts == []

    def test_disabled_rule_skipped(self):
        self.engine.add_rule(AlertRule(
            name="disabled-rule",
            condition="error_rate > 0.0",
            severity="critical",
            enabled=False,
        ))
        trace = _make_trace(span_count=5, error_count=5)
        alerts = _run(self.engine.check_trace(trace))
        assert alerts == []

    def test_multiple_rules_multiple_fires(self):
        self.engine.add_rule(AlertRule(name="r1", condition="error_rate > 0.1", severity="warning"))
        self.engine.add_rule(AlertRule(name="r2", condition="cost_per_trace > 0.1", severity="info"))
        trace = _make_trace(span_count=10, error_count=5, total_cost_usd=1.0)
        alerts = _run(self.engine.check_trace(trace))
        assert len(alerts) == 2
        names = {a.rule_name for a in alerts}
        assert names == {"r1", "r2"}

    def test_alert_contains_trace_id(self):
        self.engine.add_rule(AlertRule(
            name="r1",
            condition="error_rate > 0.1",
            severity="warning",
        ))
        trace = _make_trace(trace_id="trace-xyz", span_count=5, error_count=5)
        alerts = _run(self.engine.check_trace(trace))
        assert alerts[0].trace_id == "trace-xyz"

    def test_alert_metrics_populated(self):
        self.engine.add_rule(AlertRule(name="r1", condition="latency > 100", severity="warning"))
        trace = _make_trace(duration_ms=9999.0)
        alerts = _run(self.engine.check_trace(trace))
        assert "value" in alerts[0].metrics
        assert alerts[0].metrics["metric"] == "latency"


# ===========================================================================
# AlertEngine — cooldown
# ===========================================================================

class TestAlertEngineCooldown:
    def test_cooldown_suppresses_repeat(self):
        engine = AlertEngine()
        engine.add_rule(AlertRule(
            name="err-rate",
            condition="error_rate > 0.1",
            severity="warning",
            cooldown_seconds=300,
        ))
        trace = _make_trace(span_count=10, error_count=5)

        # First check — should fire
        alerts1 = _run(engine.check_trace(trace))
        assert len(alerts1) == 1

        # Second check immediately — should be suppressed (cooldown active)
        alerts2 = _run(engine.check_trace(trace))
        assert len(alerts2) == 0

    def test_cooldown_zero_always_fires(self):
        engine = AlertEngine()
        engine.add_rule(AlertRule(
            name="always-fire",
            condition="error_rate > 0.0",
            severity="info",
            cooldown_seconds=0,
        ))
        trace = _make_trace(span_count=1, error_count=1)

        alerts1 = _run(engine.check_trace(trace))
        assert len(alerts1) == 1

        # Manually set last_fired to now - 1 second (0 cooldown means always fires)
        # With cooldown=0, _is_on_cooldown returns False since (now - last) >= 0
        alerts2 = _run(engine.check_trace(trace))
        assert len(alerts2) == 1

    def test_cooldown_expires(self):
        engine = AlertEngine()
        engine.add_rule(AlertRule(
            name="short-cooldown",
            condition="error_rate > 0.1",
            severity="warning",
            cooldown_seconds=1,
        ))
        trace = _make_trace(span_count=10, error_count=5)

        # First fire
        alerts1 = _run(engine.check_trace(trace))
        assert len(alerts1) == 1

        # Manually backdate the last_fired to expire the cooldown
        engine._last_fired["short-cooldown"] = time.time() - 2

        # Should fire again
        alerts2 = _run(engine.check_trace(trace))
        assert len(alerts2) == 1


# ===========================================================================
# Rule management
# ===========================================================================

class TestAlertEngineRuleManagement:
    def test_add_and_list(self):
        engine = AlertEngine()
        engine.add_rule(AlertRule(name="a", condition="latency > 1"))
        engine.add_rule(AlertRule(name="b", condition="tokens > 100"))
        rules = engine.list_rules()
        assert len(rules) == 2
        assert {r.name for r in rules} == {"a", "b"}

    def test_remove_rule(self):
        engine = AlertEngine()
        engine.add_rule(AlertRule(name="r1", condition="latency > 1"))
        removed = engine.remove_rule("r1")
        assert removed is True
        assert engine.list_rules() == []

    def test_remove_nonexistent(self):
        engine = AlertEngine()
        assert engine.remove_rule("does-not-exist") is False

    def test_get_rule(self):
        engine = AlertEngine()
        engine.add_rule(AlertRule(name="x", condition="tokens > 1000"))
        rule = engine.get_rule("x")
        assert rule is not None
        assert rule.name == "x"

    def test_get_rule_not_found(self):
        engine = AlertEngine()
        assert engine.get_rule("nope") is None

    def test_replace_rule(self):
        engine = AlertEngine()
        engine.add_rule(AlertRule(name="r", condition="latency > 100"))
        engine.add_rule(AlertRule(name="r", condition="latency > 9999"))
        rules = engine.list_rules()
        assert len(rules) == 1
        assert rules[0].condition == "latency > 9999"


# ===========================================================================
# Webhook payload format
# ===========================================================================

class TestWebhookPayload:
    def _alert_dict(self, **kwargs):
        d = {
            "rule_name": "test-rule",
            "severity": "critical",
            "message": "Something went wrong",
            "trace_id": "t-abc",
            "metrics": {"value": 0.9},
            "fired_at": 1234567890.0,
        }
        d.update(kwargs)
        return d

    def _trace_ctx(self):
        return {
            "trace_id": "t-abc",
            "service_name": "my-service",
            "duration_ms": 3500.0,
        }

    def test_generic_payload_structure(self):
        payload = _build_generic_payload(self._alert_dict(), self._trace_ctx())
        assert payload["source"] == "flowlens"
        assert payload["alert"]["rule"] == "test-rule"
        assert payload["alert"]["severity"] == "critical"
        assert payload["alert"]["message"] == "Something went wrong"
        assert payload["trace"]["trace_id"] == "t-abc"
        assert payload["trace"]["service"] == "my-service"
        assert payload["trace"]["duration_ms"] == 3500.0
        assert "timestamp" in payload

    def test_generic_payload_no_trace_context(self):
        payload = _build_generic_payload(self._alert_dict(), None)
        assert payload["trace"] == {}
        assert payload["source"] == "flowlens"

    def test_slack_payload_structure(self):
        payload = _build_slack_payload(self._alert_dict(), self._trace_ctx())
        assert "text" in payload
        assert "blocks" in payload
        assert len(payload["blocks"]) > 0
        # Header block
        header = payload["blocks"][0]
        assert header["type"] == "header"
        assert "test-rule" in header["text"]["text"]

    def test_slack_payload_no_trace(self):
        payload = _build_slack_payload(self._alert_dict(), None)
        assert "blocks" in payload
        # Should not raise even without trace context

    def test_build_payload_detects_slack(self):
        url = "https://hooks.slack.com/services/T123/B456/abcdef"
        payload = build_payload(self._alert_dict(), self._trace_ctx(), url)
        # Slack payload has "blocks" key
        assert "blocks" in payload

    def test_build_payload_generic_for_non_slack(self):
        url = "https://my-webhook.example.com/hook"
        payload = build_payload(self._alert_dict(), self._trace_ctx(), url)
        assert "source" in payload
        assert payload["source"] == "flowlens"


# ===========================================================================
# Storage — alert_rules CRUD
# ===========================================================================

class TestAlertStorageCrud:
    @pytest.fixture
    def store(self, tmp_path):
        from flowlens.server.storage import TraceStore
        return TraceStore(db_path=str(tmp_path / "test_alert.db"))

    def test_save_and_get_rule(self, store):
        rule = AlertRule(
            name="test",
            condition="latency > 1000",
            severity="warning",
            webhook_url="https://example.com",
            cooldown_seconds=60,
        )
        store.save_alert_rule(rule.to_dict())
        loaded = store.get_alert_rule("test")
        assert loaded is not None
        assert loaded["name"] == "test"
        assert loaded["condition"] == "latency > 1000"
        assert loaded["enabled"] is True

    def test_list_rules_empty(self, store):
        assert store.list_alert_rules() == []

    def test_list_rules(self, store):
        store.save_alert_rule(AlertRule(name="a", condition="c > 1").to_dict())
        store.save_alert_rule(AlertRule(name="b", condition="c > 2").to_dict())
        rules = store.list_alert_rules()
        assert len(rules) == 2
        names = {r["name"] for r in rules}
        assert names == {"a", "b"}

    def test_delete_rule(self, store):
        store.save_alert_rule(AlertRule(name="del-me", condition="x > 1").to_dict())
        deleted = store.delete_alert_rule("del-me")
        assert deleted is True
        assert store.get_alert_rule("del-me") is None

    def test_delete_nonexistent(self, store):
        assert store.delete_alert_rule("ghost") is False

    def test_upsert_rule(self, store):
        store.save_alert_rule(AlertRule(name="r", condition="c > 1").to_dict())
        store.save_alert_rule(AlertRule(name="r", condition="c > 99").to_dict())
        rules = store.list_alert_rules()
        assert len(rules) == 1
        assert rules[0]["condition"] == "c > 99"

    def test_save_and_get_alert_history(self, store):
        alert = Alert(
            rule_name="r1",
            severity="critical",
            message="Test alert",
            trace_id="t-42",
            metrics={"value": 0.5},
            fired_at=1234567890.0,
        )
        store.save_alert(alert.to_dict())
        history = store.get_alert_history(limit=10)
        assert len(history) == 1
        h = history[0]
        assert h["rule_name"] == "r1"
        assert h["trace_id"] == "t-42"
        assert h["metrics"] == {"value": 0.5}

    def test_alert_history_limit(self, store):
        for i in range(20):
            a = Alert(
                rule_name="r",
                severity="info",
                message=f"alert {i}",
                fired_at=float(i),
            )
            store.save_alert(a.to_dict())
        history = store.get_alert_history(limit=5)
        assert len(history) == 5

    def test_alert_history_order(self, store):
        for fired_at in [100.0, 300.0, 200.0]:
            store.save_alert(Alert(
                rule_name="r",
                severity="info",
                message="m",
                fired_at=fired_at,
            ).to_dict())
        history = store.get_alert_history(limit=10)
        # newest first
        fired_times = [h["fired_at"] for h in history]
        assert fired_times == sorted(fired_times, reverse=True)


# ===========================================================================
# API endpoints
# ===========================================================================

class TestAlertingAPI:
    @pytest.fixture
    def client(self, tmp_path):
        from fastapi.testclient import TestClient
        from flowlens.server.app import create_app
        app = create_app(db_path=str(tmp_path / "test_api.db"))
        return TestClient(app, raise_server_exceptions=True)

    def test_create_rule(self, client):
        resp = client.post("/v1/alerts/rules", json={
            "name": "err-rate",
            "condition": "error_rate > 0.1",
            "severity": "critical",
        })
        assert resp.status_code == 201
        assert resp.json()["name"] == "err-rate"

    def test_list_rules_empty(self, client):
        resp = client.get("/v1/alerts/rules")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_rules_after_create(self, client):
        client.post("/v1/alerts/rules", json={"name": "r1", "condition": "latency > 1"})
        client.post("/v1/alerts/rules", json={"name": "r2", "condition": "tokens > 100"})
        resp = client.get("/v1/alerts/rules")
        assert resp.status_code == 200
        names = {r["name"] for r in resp.json()}
        assert names == {"r1", "r2"}

    def test_delete_rule(self, client):
        client.post("/v1/alerts/rules", json={"name": "to-delete", "condition": "latency > 1"})
        resp = client.delete("/v1/alerts/rules/to-delete")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

        # Should be gone
        resp2 = client.get("/v1/alerts/rules")
        assert all(r["name"] != "to-delete" for r in resp2.json())

    def test_delete_rule_not_found(self, client):
        resp = client.delete("/v1/alerts/rules/ghost-rule")
        assert resp.status_code == 404

    def test_alert_history_empty(self, client):
        resp = client.get("/v1/alerts/history")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_alert_history_after_ingest(self, client):
        # Create a rule that will fire
        client.post("/v1/alerts/rules", json={
            "name": "err-rate",
            "condition": "error_rate > 0.0",
            "severity": "critical",
            "cooldown_seconds": 0,
        })
        # Ingest a trace with errors
        client.post("/v1/traces/ingest", json={
            "trace_id": "test-alert-trace",
            "service_name": "svc",
            "start_time": 1000.0,
            "end_time": 1001.0,
            "duration_ms": 1000.0,
            "total_tokens": 100,
            "total_cost_usd": 0.01,
            "has_errors": True,
            "error_count": 1,
            "span_count": 1,
            "metadata": {},
            "spans": [],
        })
        resp = client.get("/v1/alerts/history")
        assert resp.status_code == 200
        history = resp.json()
        assert len(history) >= 1
        assert history[0]["rule_name"] == "err-rate"

    def test_test_webhook_invalid_url(self, client):
        """Posting to a non-reachable URL should return delivered=False, not crash."""
        resp = client.post("/v1/alerts/test", json={
            "webhook_url": "http://localhost:1/nonexistent"
        })
        assert resp.status_code == 200
        assert resp.json()["delivered"] is False

    def test_create_rule_invalid_severity(self, client):
        resp = client.post("/v1/alerts/rules", json={
            "name": "bad",
            "condition": "latency > 1",
            "severity": "extreme",
        })
        assert resp.status_code == 422  # Pydantic validation error

    def test_create_rule_with_webhook(self, client):
        resp = client.post("/v1/alerts/rules", json={
            "name": "hook-rule",
            "condition": "latency > 1000",
            "severity": "warning",
            "webhook_url": "https://hooks.slack.com/services/test",
            "cooldown_seconds": 600,
        })
        assert resp.status_code == 201
        rules = client.get("/v1/alerts/rules").json()
        rule = next(r for r in rules if r["name"] == "hook-rule")
        assert rule["webhook_url"] == "https://hooks.slack.com/services/test"
        assert rule["cooldown_seconds"] == 600
