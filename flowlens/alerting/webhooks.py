"""
FlowLens Alerting — Webhook delivery.

send_webhook(url, alert, trace_context) — POST JSON payload to a URL.

Payload format:
    {
        "source": "flowlens",
        "alert": {"rule": "...", "severity": "...", "message": "..."},
        "trace": {"trace_id": "...", "service": "...", "duration_ms": N},
        "timestamp": "ISO-8601"
    }

Slack detection: when the URL contains "slack.com" the payload is formatted
as Slack Block Kit blocks instead of the generic JSON shape.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def _iso_now() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(tz=timezone.utc).isoformat()


def _build_generic_payload(
    alert_dict: dict[str, Any],
    trace_context: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build the standard FlowLens webhook payload."""
    trace_section: dict[str, Any] = {}
    if trace_context:
        trace_section = {
            "trace_id": trace_context.get("trace_id", ""),
            "service": trace_context.get("service_name", ""),
            "duration_ms": trace_context.get("duration_ms", 0),
        }

    return {
        "source": "flowlens",
        "alert": {
            "rule": alert_dict.get("rule_name", ""),
            "severity": alert_dict.get("severity", ""),
            "message": alert_dict.get("message", ""),
        },
        "trace": trace_section,
        "timestamp": _iso_now(),
    }


def _build_slack_payload(
    alert_dict: dict[str, Any],
    trace_context: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build a Slack Block Kit payload for Slack Incoming Webhooks."""
    severity = alert_dict.get("severity", "info")
    rule_name = alert_dict.get("rule_name", "unknown")
    message = alert_dict.get("message", "")

    severity_emoji = {
        "critical": ":red_circle:",
        "warning": ":warning:",
        "info": ":information_source:",
    }.get(severity, ":bell:")

    header_text = f"{severity_emoji} FlowLens Alert: `{rule_name}` [{severity.upper()}]"

    fields: list[dict[str, Any]] = []
    if trace_context:
        trace_id = trace_context.get("trace_id", "n/a")
        service = trace_context.get("service_name", "n/a")
        duration_ms = trace_context.get("duration_ms", 0)
        fields = [
            {
                "type": "mrkdwn",
                "text": f"*Trace ID:*\n`{trace_id}`",
            },
            {
                "type": "mrkdwn",
                "text": f"*Service:*\n{service}",
            },
            {
                "type": "mrkdwn",
                "text": f"*Duration:*\n{duration_ms:.1f} ms",
            },
            {
                "type": "mrkdwn",
                "text": f"*Fired At:*\n{_iso_now()}",
            },
        ]

    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": header_text,
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": message,
            },
        },
    ]

    if fields:
        blocks.append({"type": "section", "fields": fields})

    blocks.append({"type": "divider"})

    return {
        "text": f"FlowLens Alert: {rule_name} ({severity})",
        "blocks": blocks,
    }


def build_payload(
    alert_dict: dict[str, Any],
    trace_context: dict[str, Any] | None,
    url: str,
) -> dict[str, Any]:
    """Choose and build the appropriate payload format based on the URL."""
    if "slack.com" in url:
        return _build_slack_payload(alert_dict, trace_context)
    return _build_generic_payload(alert_dict, trace_context)


async def send_webhook(
    url: str,
    alert_dict: dict[str, Any],
    trace_context: dict[str, Any] | None = None,
    timeout: float = 5.0,
) -> bool:
    """
    POST an alert payload to *url* asynchronously.

    Retries once on failure.  Returns True if delivery succeeded.

    Args:
        url:           Webhook destination URL.
        alert_dict:    Alert data (from Alert.to_dict()).
        trace_context: Optional trace metadata to include in the payload.
        timeout:       Per-attempt HTTP timeout in seconds (default 5).

    Returns:
        True if the webhook was delivered successfully, False otherwise.
    """
    try:
        import httpx
    except ImportError:
        logger.error(
            "httpx is not installed; cannot send webhook to %s. "
            "Install it with: pip install httpx",
            url,
        )
        return False

    payload = build_payload(alert_dict, trace_context, url)

    for attempt in range(2):  # try once, retry once on failure
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code < 300:
                    logger.debug("Webhook delivered to %s (status %d)", url, resp.status_code)
                    return True
                logger.warning(
                    "Webhook attempt %d to %s returned HTTP %d",
                    attempt + 1,
                    url,
                    resp.status_code,
                )
        except Exception as exc:
            logger.warning(
                "Webhook attempt %d to %s failed: %s",
                attempt + 1,
                url,
                exc,
            )

    logger.error("Webhook delivery to %s failed after 2 attempts", url)
    return False


__all__ = ["send_webhook", "build_payload"]
