"""
Alert rules and history route handlers.

Endpoints:
- POST   /v1/alerts/rules
- GET    /v1/alerts/rules
- DELETE /v1/alerts/rules/{name}
- GET    /v1/alerts/history
- POST   /v1/alerts/test
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ...alerting import Alert, AlertRule
from ...alerting.engine import AlertEngine
from ...alerting.webhooks import send_webhook as _send_webhook
from ..storage import TraceStore
from ..utils import _sanitize_id

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class AlertRuleCreate(BaseModel):
    """Payload for POST /v1/alerts/rules."""
    name: str = Field(..., min_length=1, max_length=256)
    condition: str = Field(..., min_length=1, max_length=512)
    severity: str = Field("warning", pattern="^(critical|warning|info)$")
    webhook_url: str | None = Field(None, max_length=2048)
    cooldown_seconds: int = Field(300, ge=0)
    enabled: bool = True


class AlertWebhookTest(BaseModel):
    """Payload for POST /v1/alerts/test."""
    webhook_url: str = Field(..., min_length=1, max_length=2048)


def create_alerts_router(store: TraceStore, alert_engine: AlertEngine) -> APIRouter:
    """Create and return the alerts router."""
    router = APIRouter()

    @router.post("/v1/alerts/rules", status_code=201)
    async def create_alert_rule(req: AlertRuleCreate) -> dict[str, Any]:
        """Create or replace an alert rule."""
        rule = AlertRule(
            name=req.name,
            condition=req.condition,
            severity=req.severity,
            webhook_url=req.webhook_url,
            cooldown_seconds=req.cooldown_seconds,
            enabled=req.enabled,
        )
        try:
            store.save_alert_rule(rule.to_dict())
            alert_engine.add_rule(rule)
        except Exception:
            logger.exception("Failed to save alert rule %s", req.name)
            raise HTTPException(500, "Failed to save alert rule")
        return {"status": "created", "name": req.name}

    @router.get("/v1/alerts/rules")
    async def list_alert_rules() -> list[dict[str, Any]]:
        """List all configured alert rules."""
        try:
            return store.list_alert_rules()
        except Exception:
            logger.exception("Failed to list alert rules")
            raise HTTPException(500, "Failed to retrieve alert rules")

    @router.delete("/v1/alerts/rules/{name}", status_code=200)
    async def delete_alert_rule(name: str) -> dict[str, str]:
        """Delete an alert rule by name."""
        _sanitize_id(name, "rule name")
        try:
            deleted = store.delete_alert_rule(name)
            alert_engine.remove_rule(name)
        except Exception:
            logger.exception("Failed to delete alert rule %s", name)
            raise HTTPException(500, "Failed to delete alert rule")
        if not deleted:
            raise HTTPException(404, f"Alert rule '{name}' not found")
        return {"status": "deleted", "name": name}

    @router.get("/v1/alerts/history")
    async def get_alert_history(
        limit: int = Query(100, ge=1, le=1000),
    ) -> list[dict[str, Any]]:
        """Return recent fired alerts (most recent first)."""
        try:
            return store.get_alert_history(limit=limit)
        except Exception:
            logger.exception("Failed to retrieve alert history")
            raise HTTPException(500, "Failed to retrieve alert history")

    @router.post("/v1/alerts/test", status_code=200)
    async def test_webhook(req: AlertWebhookTest) -> dict[str, Any]:
        """Send a test alert to the specified webhook URL."""
        test_alert = Alert(
            rule_name="test",
            severity="info",
            message="This is a test alert from FlowLens.",
            trace_id=None,
            metrics={"test": True},
        )
        try:
            success = await _send_webhook(
                url=req.webhook_url,
                alert_dict=test_alert.to_dict(),
                trace_context=None,
            )
        except Exception as exc:
            logger.warning("Test webhook to %s failed: %s", req.webhook_url, exc)
            success = False
        return {"delivered": success, "webhook_url": req.webhook_url}

    return router
