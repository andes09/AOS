"""
Multi-team management API router.

Endpoints
---------
GET    /api/teams
POST   /api/teams/{team_id}/access
DELETE /api/teams/{team_id}/access/{developer_id}
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
from src.models.developer import Developer
from src.models.team_access import TeamAccessGrant
from src.services.multi_team import get_accessible_teams

teams_router = APIRouter(tags=["teams"])


# ---------------------------------------------------------------------------
# Response / Request models
# ---------------------------------------------------------------------------

class TeamListItem(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    team_id: str
    team_name: str
    is_primary: bool


class TeamsListResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    teams: list[TeamListItem]


class GrantAccessRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    developer_clerk_user_id: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_primary_team_id(clerk_user_id: str, db: AsyncSession) -> uuid.UUID | None:
    result = await db.execute(
        select(Developer.team_id).where(Developer.clerk_user_id == clerk_user_id).limit(1)
    )
    row = result.scalar_one_or_none()
    return row


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@teams_router.get("", response_model=TeamsListResponse)
async def list_teams(
    user_id: str = Depends(get_current_user_id),
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    teams = await get_accessible_teams(user_id, clerk_org_id, db)
    primary_id = await _get_primary_team_id(user_id, db)

    items = [
        TeamListItem(
            team_id=str(t.id),
            team_name=t.name,
            is_primary=(t.id == primary_id),
        )
        for t in teams
    ]
    return TeamsListResponse(teams=items)


@teams_router.post("/{team_id}/access", status_code=201)
async def grant_access(
    team_id: uuid.UUID,
    body: GrantAccessRequest,
    _user_id: str = Depends(get_current_user_id),
    _role: str = Depends(require_role("lead")),
    db: AsyncSession = Depends(get_db),
):
    # Find developer by clerk user id
    dev_result = await db.execute(
        select(Developer).where(Developer.clerk_user_id == body.developer_clerk_user_id)
    )
    developer = dev_result.scalar_one_or_none()
    if not developer:
        raise HTTPException(status_code=404, detail="Developer not found")

    # Check if already granted
    existing = await db.execute(
        select(TeamAccessGrant).where(
            TeamAccessGrant.developer_id == developer.id,
            TeamAccessGrant.team_id == team_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Access already granted")

    grant = TeamAccessGrant(
        id=uuid.uuid4(),
        developer_id=developer.id,
        team_id=team_id,
        granted_by=_user_id,
    )
    db.add(grant)
    await db.commit()
    return {"granted": True, "teamId": str(team_id), "developerId": str(developer.id)}


@teams_router.delete("/{team_id}/access/{developer_id}")
async def revoke_access(
    team_id: uuid.UUID,
    developer_id: uuid.UUID,
    _user_id: str = Depends(get_current_user_id),
    _role: str = Depends(require_role("lead")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(TeamAccessGrant).where(
            TeamAccessGrant.developer_id == developer_id,
            TeamAccessGrant.team_id == team_id,
        )
    )
    grant = result.scalar_one_or_none()
    if not grant:
        raise HTTPException(status_code=404, detail="Access grant not found")

    await db.delete(grant)
    await db.commit()
    return {"revoked": True}
