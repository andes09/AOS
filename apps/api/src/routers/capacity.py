"""
Capacity settings API router.

Endpoints
---------
GET    /api/capacity/team/{team_id}
PATCH  /api/capacity/team/{team_id}/overhead
PUT    /api/capacity/team/{team_id}/developers/{developer_id}/override
DELETE /api/capacity/team/{team_id}/developers/{developer_id}/override
"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_org_id, get_current_user_id
from src.auth_roles import require_role
from src.database import get_db
from src.models.capacity import DeveloperCapacityOverride
from src.models.developer import Developer
from src.models.organization import Organization
from src.models.sprint import Sprint
from src.models.team import Team
from src.services.capacity import DeveloperEffectiveCapacity, get_team_capacity

capacity_router = APIRouter(tags=["capacity"])


# ---------------------------------------------------------------------------
# Response / Request models
# ---------------------------------------------------------------------------

class DeveloperCapacityItem(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    developer_id: str
    display_name: str
    base_velocity: float
    effective_capacity_pts: float
    meeting_overhead_pct: float
    pto_days: float
    capacity_pct: float
    is_high_meeting_load: bool
    warning_message: str | None


class TeamCapacityResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    team_id: str
    meeting_overhead_pct: float
    developers: list[DeveloperCapacityItem]


class PatchOverheadRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    meeting_overhead_pct: float


class PatchOverheadResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    team_id: str
    meeting_overhead_pct: float


class CapacityOverrideRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    sprint_id: str | None = None
    capacity_pct: float | None = None
    pto_days: float | None = None
    notes: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _resolve_team(team_id: str, clerk_org_id: str, db: AsyncSession) -> Team:
    org_result = await db.execute(
        select(Organization).where(Organization.clerk_org_id == clerk_org_id)
    )
    org = org_result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    if team_id == "default":
        team_result = await db.execute(
            select(Team).where(Team.organization_id == org.id).limit(1)
        )
    else:
        try:
            tid = uuid.UUID(team_id)
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid team_id")
        team_result = await db.execute(
            select(Team).where(Team.id == tid, Team.organization_id == org.id)
        )

    team = team_result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    return team


def _to_item(d: DeveloperEffectiveCapacity) -> DeveloperCapacityItem:
    return DeveloperCapacityItem(
        developer_id=d.developer_id,
        display_name=d.display_name,
        base_velocity=d.base_velocity,
        effective_capacity_pts=d.effective_capacity_pts,
        meeting_overhead_pct=d.meeting_overhead_pct,
        pto_days=d.pto_days,
        capacity_pct=d.capacity_pct,
        is_high_meeting_load=d.is_high_meeting_load,
        warning_message=d.warning_message,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@capacity_router.get("/team/{team_id}", response_model=TeamCapacityResponse)
async def get_team_capacity_endpoint(
    team_id: str,
    sprint_id: str | None = Query(default=None),
    _user_id: str = Depends(get_current_user_id),
    clerk_org_id: str = Depends(get_current_org_id),
    _role: str = Depends(require_role("lead")),
    db: AsyncSession = Depends(get_db),
):
    team = await _resolve_team(team_id, clerk_org_id, db)
    devs = await get_team_capacity(str(team.id), sprint_id, db)
    return TeamCapacityResponse(
        team_id=str(team.id),
        meeting_overhead_pct=team.meeting_overhead_pct,
        developers=[_to_item(d) for d in devs],
    )


@capacity_router.patch("/team/{team_id}/overhead", response_model=PatchOverheadResponse)
async def patch_overhead(
    team_id: str,
    body: PatchOverheadRequest,
    _user_id: str = Depends(get_current_user_id),
    clerk_org_id: str = Depends(get_current_org_id),
    _role: str = Depends(require_role("lead")),
    db: AsyncSession = Depends(get_db),
):
    if not (0.0 <= body.meeting_overhead_pct <= 1.0):
        raise HTTPException(status_code=422, detail="meetingOverheadPct must be between 0.0 and 1.0")

    team = await _resolve_team(team_id, clerk_org_id, db)
    team.meeting_overhead_pct = body.meeting_overhead_pct
    await db.commit()
    return PatchOverheadResponse(team_id=str(team.id), meeting_overhead_pct=team.meeting_overhead_pct)


@capacity_router.put("/team/{team_id}/developers/{developer_id}/override", response_model=DeveloperCapacityItem)
async def put_capacity_override(
    team_id: str,
    developer_id: uuid.UUID,
    body: CapacityOverrideRequest,
    user_id: str = Depends(get_current_user_id),
    clerk_org_id: str = Depends(get_current_org_id),
    _role: str = Depends(require_role("lead")),
    db: AsyncSession = Depends(get_db),
):
    if body.capacity_pct is not None and not (0.0 <= body.capacity_pct <= 1.0):
        raise HTTPException(status_code=422, detail="capacityPct must be between 0.0 and 1.0")

    team = await _resolve_team(team_id, clerk_org_id, db)

    # Verify developer exists on this team
    dev_result = await db.execute(
        select(Developer).where(Developer.id == developer_id, Developer.team_id == team.id)
    )
    developer = dev_result.scalar_one_or_none()
    if not developer:
        raise HTTPException(status_code=404, detail="Developer not found")

    sprint_uuid = uuid.UUID(body.sprint_id) if body.sprint_id else None

    # Verify sprint if provided
    if sprint_uuid:
        sprint_result = await db.execute(select(Sprint).where(Sprint.id == sprint_uuid))
        if not sprint_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Sprint not found")

    # Upsert override
    existing_result = await db.execute(
        select(DeveloperCapacityOverride).where(
            DeveloperCapacityOverride.developer_id == developer_id,
            DeveloperCapacityOverride.sprint_id == sprint_uuid,
        )
    )
    override = existing_result.scalar_one_or_none()

    if override:
        override.capacity_pct = body.capacity_pct
        override.pto_days = body.pto_days
        override.notes = body.notes
    else:
        override = DeveloperCapacityOverride(
            id=uuid.uuid4(),
            developer_id=developer_id,
            sprint_id=sprint_uuid,
            capacity_pct=body.capacity_pct,
            pto_days=body.pto_days,
            notes=body.notes,
            created_by=user_id,
        )
        db.add(override)

    await db.commit()

    # Re-compute and return
    devs = await get_team_capacity(str(team.id), body.sprint_id, db)
    dev_cap = next((d for d in devs if d.developer_id == str(developer_id)), None)
    if not dev_cap:
        raise HTTPException(status_code=404, detail="Could not recompute capacity")
    return _to_item(dev_cap)


@capacity_router.delete("/team/{team_id}/developers/{developer_id}/override")
async def delete_capacity_override(
    team_id: str,
    developer_id: uuid.UUID,
    sprint_id: str | None = Query(default=None),
    _user_id: str = Depends(get_current_user_id),
    clerk_org_id: str = Depends(get_current_org_id),
    _role: str = Depends(require_role("lead")),
    db: AsyncSession = Depends(get_db),
):
    team = await _resolve_team(team_id, clerk_org_id, db)

    sprint_uuid = uuid.UUID(sprint_id) if sprint_id else None

    result = await db.execute(
        select(DeveloperCapacityOverride).where(
            DeveloperCapacityOverride.developer_id == developer_id,
            DeveloperCapacityOverride.sprint_id == sprint_uuid,
        )
    )
    override = result.scalar_one_or_none()
    if not override:
        raise HTTPException(status_code=404, detail="No capacity override found")

    await db.delete(override)
    await db.commit()
    return {"deleted": True}
