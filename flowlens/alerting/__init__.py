"""
FlowLens Alerting — threshold-based alert rules with webhook delivery.

Models:
    AlertRule  — defines when to fire an alert
    Alert      — a fired alert instance

Condition syntax:
    "error_rate > 0.1"       — trace error_rate exceeds threshold
    "cost_per_trace > 0.5"   — total_cost_usd exceeds threshold
    "latency > 5000"         — duration_ms exceeds threshold (in ms)
    "tokens > 100000"        — total_tokens exceeds threshold
    "pattern:retry_storm"    — a specific pattern was detected in the trace
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class AlertRule:
    """Defines a threshold-based alerting rule.

    Attributes:
        name:             Unique rule name (used as identifier).
        condition:        Condition expression, e.g. "error_rate > 0.1",
                          "cost_per_trace > 0.5", "pattern:retry_storm".
        severity:         One of "critical", "warning", "info".
        webhook_url:      Optional URL to POST alert payloads to.
        cooldown_seconds: Minimum seconds between repeated firings of this rule
                          for the same trace.  Defaults to 300 (5 minutes).
        enabled:          When False the rule is skipped during evaluation.
    """

    name: str
    condition: str
    severity: str = "warning"
    webhook_url: Optional[str] = None
    cooldown_seconds: int = 300
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "condition": self.condition,
            "severity": self.severity,
            "webhook_url": self.webhook_url,
            "cooldown_seconds": self.cooldown_seconds,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AlertRule":
        return cls(
            name=data["name"],
            condition=data["condition"],
            severity=data.get("severity", "warning"),
            webhook_url=data.get("webhook_url"),
            cooldown_seconds=data.get("cooldown_seconds", 300),
            enabled=data.get("enabled", True),
        )


@dataclass
class Alert:
    """A single fired alert instance.

    Attributes:
        rule_name:  Name of the ``AlertRule`` that fired.
        severity:   Severity level copied from the rule.
        message:    Human-readable description of what triggered the alert.
        trace_id:   Optional trace ID that caused the alert to fire.
        metrics:    Snapshot of the metric values at the time of firing.
        fired_at:   Unix timestamp when the alert fired.
    """

    rule_name: str
    severity: str
    message: str
    trace_id: Optional[str] = None
    metrics: dict[str, Any] = field(default_factory=dict)
    fired_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_name": self.rule_name,
            "severity": self.severity,
            "message": self.message,
            "trace_id": self.trace_id,
            "metrics": self.metrics,
            "fired_at": self.fired_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Alert":
        return cls(
            rule_name=data["rule_name"],
            severity=data["severity"],
            message=data["message"],
            trace_id=data.get("trace_id"),
            metrics=data.get("metrics", {}),
            fired_at=data.get("fired_at", time.time()),
        )


__all__ = ["AlertRule", "Alert"]
