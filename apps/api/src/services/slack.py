import uuid

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.slack_config import SlackConfig


ALERT_TEMPLATES: dict[str, str] = {
    "high_risk_dependency": "⛔ *{team_name}*: High-risk dependency on `{ticket_key}` — {description}",
    "sprint_at_risk":       "⚠️ *{team_name}*: Sprint `{sprint_name}` is at risk — {reason}",
    "retro_action_overdue": "📋 *{team_name}*: Retro action overdue — {action}",
}


async def send_slack_alert(
    webhook_url: str,
    alert_type: str,
    payload: dict,
) -> bool:
    """
    Formats message from ALERT_TEMPLATES[alert_type] using payload.
    POSTs to webhook_url. Returns True on 200, False otherwise.
    Never raises — caller should log failures.
    """
    template = ALERT_TEMPLATES.get(alert_type, "{team_name}: {alert_type}")
    try:
        message = template.format(**payload)
    except KeyError:
        message = f"{payload.get('team_name', 'AgileOS')}: {alert_type}"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                webhook_url,
                json={"text": message},
            )
            return r.status_code == 200
    except Exception:
        return False


async def send_test_message(webhook_url: str, team_name: str) -> bool:
    """Sends a simple "✅ AgileOS Slack connection verified for {team_name}" message."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                webhook_url,
                json={"text": f"✅ AgileOS Slack connection verified for {team_name}"},
            )
            return r.status_code == 200
    except Exception:
        return False


async def dispatch_alerts_for_team(
    team_id: uuid.UUID,
    alert_type: str,
    payload: dict,
    db: AsyncSession,
) -> bool:
    """
    Looks up active SlackConfig for team. If found and alert_type in config.alert_types,
    calls send_slack_alert(). Returns True if message sent, False if no config or disabled.
    """
    result = await db.execute(
        select(SlackConfig).where(
            SlackConfig.team_id == team_id,
            SlackConfig.is_active == True,
        )
    )
    config = result.scalar_one_or_none()
    if not config:
        return False

    alert_types = config.alert_types or []
    if alert_type not in alert_types:
        return False

    return await send_slack_alert(config.webhook_url, alert_type, payload)
