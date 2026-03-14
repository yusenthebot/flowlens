"""
FlowLens Alerting — Alert evaluation engine.

AlertEngine evaluates all enabled AlertRules against an incoming trace dict
and fires webhooks for any rules that match.

Supported condition syntax:
    "error_rate > X"       — checks trace error_rate (0.0–1.0)
    "cost_per_trace > X"   — checks trace total_cost_usd
    "latency > X"          — checks trace duration_ms
    "tokens > X"           — checks trace total_tokens
    "pattern:NAME"         — checks if the named pattern was detected

Cooldown:
    A per-rule, per-trace-service cooldown prevents alert storms.  After a
    rule fires it will not fire again for ``cooldown_seconds``.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any, Optional

from . import Alert, AlertRule
from .webhooks import send_webhook

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Condition parsing helpers
# ---------------------------------------------------------------------------

# Matches "metric_name operator value"
# e.g. "error_rate > 0.1", "latency >= 5000"
_THRESHOLD_RE = re.compile(
    r"^(?P<metric>[\w_]+)\s*(?P<op>[><=!]+)\s*(?P<value>[\d.]+)$"
)

# Matches "pattern:name"  e.g. "pattern:retry_storm"
_PATTERN_RE = re.compile(r"^pattern:(?P<name>[\w_]+)$")


def _eval_threshold(
    metric_value: float,
    op: str,
    threshold: float,
) -> bool:
    """Evaluate a comparison operator."""
    ops = {
        ">": lambda a, b: a > b,
        ">=": lambda a, b: a >= b,
        "<": lambda a, b: a < b,
        "<=": lambda a, b: a <= b,
        "==": lambda a, b: a == b,
        "!=": lambda a, b: a != b,
    }
    fn = ops.get(op)
    if fn is None:
        raise ValueError(f"Unknown operator: {op!r}")
    return fn(metric_value, threshold)


def _extract_metric(trace: dict[str, Any], metric: str) -> Optional[float]:
    """
    Extract a numeric metric from a trace dict.

    Supported metrics:
        error_rate      — error_count / span_count (0.0–1.0)
        cost_per_trace  — total_cost_usd
        latency         — duration_ms
        tokens          — total_tokens
    """
    if metric == "error_rate":
        span_count = trace.get("span_count", 0)
        error_count = trace.get("error_count", 0)
        if span_count == 0:
            return 0.0
        return error_count / span_count
    if metric == "cost_per_trace":
        return float(trace.get("total_cost_usd", 0.0))
    if metric == "latency":
        return float(trace.get("duration_ms", 0.0))
    if metric == "tokens":
        return float(trace.get("total_tokens", 0))
    return None


def _check_pattern(trace: dict[str, Any], pattern_name: str) -> bool:
    """
    Return True if *pattern_name* is present in the trace's detected patterns.

    The trace dict may carry a "patterns" list (from analysis) where each item
    is either a string or a dict with a "pattern" key (from DAG analysis).
    """
    patterns_raw = trace.get("patterns", [])
    for p in patterns_raw:
        if isinstance(p, str):
            if p == pattern_name:
                return True
        elif isinstance(p, dict):
            # {"pattern": "retry_storm", ...}
            if p.get("pattern") == pattern_name:
                return True
    return False


# ---------------------------------------------------------------------------
# AlertEngine
# ---------------------------------------------------------------------------


class AlertEngine:
    """
    Evaluates alert rules against incoming traces and fires webhooks.

    Usage::

        engine = AlertEngine()
        engine.add_rule(AlertRule(
            name="high-error-rate",
            condition="error_rate > 0.1",
            severity="critical",
            webhook_url="https://hooks.slack.com/...",
        ))
        fired = await engine.check_trace(trace_dict)

    Thread safety:
        Rule management methods (add_rule, remove_rule, list_rules) are safe to
        call from multiple threads.  ``check_trace`` is async and must be
        awaited.
    """

    def __init__(self) -> None:
        self._rules: dict[str, AlertRule] = {}
        # cooldown tracking: rule_name -> last_fired timestamp
        self._last_fired: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Rule management
    # ------------------------------------------------------------------

    def add_rule(self, rule: AlertRule) -> None:
        """Register (or replace) an alert rule."""
        self._rules[rule.name] = rule
        logger.debug("Alert rule registered: %s", rule.name)

    def remove_rule(self, name: str) -> bool:
        """Remove a rule by name.  Returns True if it existed."""
        existed = name in self._rules
        self._rules.pop(name, None)
        self._last_fired.pop(name, None)
        return existed

    def list_rules(self) -> list[AlertRule]:
        """Return all registered rules (in insertion order)."""
        return list(self._rules.values())

    def get_rule(self, name: str) -> Optional[AlertRule]:
        """Return a rule by name or None."""
        return self._rules.get(name)

    # ------------------------------------------------------------------
    # Condition evaluation
    # ------------------------------------------------------------------

    def _evaluate_condition(
        self, rule: AlertRule, trace: dict[str, Any]
    ) -> tuple[bool, str, dict[str, Any]]:
        """
        Evaluate a single rule condition against a trace dict.

        Returns:
            (matched, message, metrics)
        """
        condition = rule.condition.strip()

        # --- pattern:NAME ---
        m = _PATTERN_RE.match(condition)
        if m:
            pattern_name = m.group("name")
            matched = _check_pattern(trace, pattern_name)
            message = (
                f"Pattern '{pattern_name}' detected in trace "
                f"{trace.get('trace_id', 'unknown')}"
            )
            metrics = {"pattern": pattern_name}
            return matched, message, metrics

        # --- metric OP threshold ---
        m = _THRESHOLD_RE.match(condition)
        if m:
            metric = m.group("metric")
            op = m.group("op")
            threshold = float(m.group("value"))

            value = _extract_metric(trace, metric)
            if value is None:
                logger.debug(
                    "Rule %s: unknown metric %r in trace, skipping",
                    rule.name,
                    metric,
                )
                return False, "", {}

            matched = _eval_threshold(value, op, threshold)
            message = (
                f"{metric} is {value:.4g} (threshold: {op} {threshold}) "
                f"in trace {trace.get('trace_id', 'unknown')}"
            )
            metrics = {
                "metric": metric,
                "value": value,
                "operator": op,
                "threshold": threshold,
            }
            return matched, message, metrics

        logger.warning(
            "Rule %s: unrecognised condition %r — skipping", rule.name, condition
        )
        return False, "", {}

    # ------------------------------------------------------------------
    # Cooldown tracking
    # ------------------------------------------------------------------

    def _is_on_cooldown(self, rule: AlertRule) -> bool:
        last = self._last_fired.get(rule.name)
        if last is None:
            return False
        return (time.time() - last) < rule.cooldown_seconds

    def _record_fired(self, rule: AlertRule) -> None:
        self._last_fired[rule.name] = time.time()

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def check_trace(
        self, trace: dict[str, Any]
    ) -> list[Alert]:
        """
        Evaluate all enabled rules against *trace* and fire webhooks.

        Args:
            trace: Trace dict as returned by TraceStore or the ingest payload.

        Returns:
            List of Alert objects that were fired (may be empty).
        """
        fired: list[Alert] = []

        for rule in self._rules.values():
            if not rule.enabled:
                continue

            if self._is_on_cooldown(rule):
                logger.debug(
                    "Rule %s is on cooldown, skipping", rule.name
                )
                continue

            try:
                matched, message, metrics = self._evaluate_condition(rule, trace)
            except Exception as exc:
                logger.warning(
                    "Rule %s condition evaluation failed: %s", rule.name, exc
                )
                continue

            if not matched:
                continue

            alert = Alert(
                rule_name=rule.name,
                severity=rule.severity,
                message=message,
                trace_id=trace.get("trace_id"),
                metrics=metrics,
            )
            fired.append(alert)
            self._record_fired(rule)

            logger.info(
                "Alert fired: rule=%s severity=%s trace=%s",
                rule.name,
                rule.severity,
                trace.get("trace_id", ""),
            )

            # Fire webhook asynchronously (non-blocking, best-effort)
            if rule.webhook_url:
                asyncio.ensure_future(
                    _fire_webhook_safe(rule.webhook_url, alert, trace)
                )

        return fired


async def _fire_webhook_safe(
    url: str, alert: Alert, trace: dict[str, Any]
) -> None:
    """Wrapper that catches all exceptions so webhook errors never crash ingest."""
    try:
        await send_webhook(url=url, alert_dict=alert.to_dict(), trace_context=trace)
    except Exception as exc:
        logger.error("Webhook delivery failed for rule %s: %s", alert.rule_name, exc)


__all__ = ["AlertEngine"]
