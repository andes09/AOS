"""
Slack configuration API router.

Endpoints (nested under /api/teams prefix)
---------
GET    /api/teams/{team_id}/slack
PUT    /api/teams/{team_id}/slack
DELETE /api/teams/{team_id}/slack
POST   /api/teams/{team_id}/slack/test
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_org_id, get_current_user_id
from src.auth_roles import require_role
from src.database import get_db
from src.models.organization import Organization
from src.models.slack_config import SlackConfig
from src.models.team import Team
from src.services.slack import send_test_message

slack_router = APIRouter(tags=["slack"])


# ---------------------------------------------------------------------------
# Response / Request models
# ---------------------------------------------------------------------------

class SlackConfigResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    configured: bool
    channel: str | None
    alert_types: list[str]
    is_active: bool


class SlackConfigRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    webhook_url: str
    channel: str | None = None
    alert_types: list[str]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _resolve_team(team_id: str | uuid.UUID, clerk_org_id: str, db: AsyncSession) -> Team:
    org_result = await db.execute(
        select(Organization).where(Organization.clerk_org_id == clerk_org_id)
    )
    org = org_result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    if str(team_id) == "default":
        team_result = await db.execute(
            select(Team).where(Team.organization_id == org.id).limit(1)
        )
    else:
        try:
            tid = uuid.UUID(str(team_id))
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid team_id")
        team_result = await db.execute(
            select(Team).where(Team.id == tid, Team.organization_id == org.id)
        )

    team = team_result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    return team


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@slack_router.get("/{team_id}/slack", response_model=SlackConfigResponse)
async def get_slack_config(
    team_id: str,
    _user_id: str = Depends(get_current_user_id),
    clerk_org_id: str = Depends(get_current_org_id),
    _role: str = Depends(require_role("lead")),
    db: AsyncSession = Depends(get_db),
):
    try:
        team = await _resolve_team(team_id, clerk_org_id, db)
    except HTTPException:
        return SlackConfigResponse(configured=False, channel=None, alert_types=[], is_active=False)
    result = await db.execute(
        select(SlackConfig).where(SlackConfig.team_id == team.id, SlackConfig.is_active == True)
    )
    config = result.scalar_one_or_none()
    if not config:
        return SlackConfigResponse(configured=False, channel=None, alert_types=[], is_active=False)
    return SlackConfigResponse(
        configured=True,
        channel=config.channel,
        alert_types=config.alert_types or [],
        is_active=config.is_active,
    )


@slack_router.put("/{team_id}/slack", response_model=SlackConfigResponse)
async def put_slack_config(
    team_id: str,
    body: SlackConfigRequest,
    _user_id: str = Depends(get_current_user_id),
    clerk_org_id: str = Depends(get_current_org_id),
    _role: str = Depends(require_role("lead")),
    db: AsyncSession = Depends(get_db),
):
    if not body.webhook_url.startswith("https://hooks.slack.com/"):
        raise HTTPException(status_code=422, detail="webhookUrl must start with https://hooks.slack.com/")

    team = await _resolve_team(team_id, clerk_org_id, db)

    result = await db.execute(
        select(SlackConfig).where(SlackConfig.team_id == team.id, SlackConfig.is_active == True)
    )
    config = result.scalar_one_or_none()

    if config:
        config.webhook_url = body.webhook_url
        config.channel = body.channel
        config.alert_types = body.alert_types
    else:
        config = SlackConfig(
            id=uuid.uuid4(),
            team_id=team.id,
            webhook_url=body.webhook_url,
            channel=body.channel,
            alert_types=body.alert_types,
            is_active=True,
        )
        db.add(config)

    await db.commit()
    return SlackConfigResponse(
        configured=True,
        channel=config.channel,
        alert_types=config.alert_types or [],
        is_active=config.is_active,
    )


@slack_router.delete("/{team_id}/slack")
async def delete_slack_config(
    team_id: str,
    _user_id: str = Depends(get_current_user_id),
    clerk_org_id: str = Depends(get_current_org_id),
    _role: str = Depends(require_role("lead")),
    db: AsyncSession = Depends(get_db),
):
    team = await _resolve_team(team_id, clerk_org_id, db)
    result = await db.execute(
        select(SlackConfig).where(SlackConfig.team_id == team.id, SlackConfig.is_active == True)
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="No Slack config found")

    await db.delete(config)
    await db.commit()
    return {"deleted": True}


@slack_router.post("/{team_id}/slack/test")
async def test_slack(
    team_id: str,
    _user_id: str = Depends(get_current_user_id),
    clerk_org_id: str = Depends(get_current_org_id),
    _role: str = Depends(require_role("lead")),
    db: AsyncSession = Depends(get_db),
):
    team = await _resolve_team(team_id, clerk_org_id, db)
    result = await db.execute(
        select(SlackConfig).where(SlackConfig.team_id == team.id, SlackConfig.is_active == True)
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=402, detail="No active Slack config")

    sent = await send_test_message(config.webhook_url, team.name)
    if not sent:
        raise HTTPException(status_code=502, detail="Slack webhook returned non-200")
    return {"sent": True}
