"""
Velocity API router.

Endpoints
---------
GET /api/teams/{team_id}/velocity
    Per-developer velocity profiles for the team.

GET /api/teams/{team_id}/velocity/{developer_id}
    Single developer velocity profile.

GET /api/teams/{team_id}/capacity
    Current sprint capacity for all developers.
"""
import uuid
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_org_id
from src.database import get_db
from src.models.developer import Developer
from src.models.organization import Organization
from src.models.sprint import Sprint, SprintStatus
from src.models.team import Team
from src.models.velocity import DeveloperVelocityProfile
from src.services.velocity import CapacityModel
from src.services.velocity.schemas import MeetingOverhead, PtoEntry, SprintMeta

router = APIRouter(prefix="/api/teams", tags=["velocity"])

_SUFFICIENT_SPRINT_THRESHOLD = 3


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class VelocityProfileResponse(BaseModel):
    developer_id: str
    name: str
    mean_completion_days: dict[str, float]  # ticket_type → avg days
    confidence_score: float | None
    sprint_count: int
    is_sufficient_data: bool


class TeamVelocityResponse(BaseModel):
    team_id: str
    profiles: list[VelocityProfileResponse]


class DeveloperCapacityItem(BaseModel):
    developer_id: str
    name: str
    available_days: float
    availability_ratio: float


class TeamCapacityResponse(BaseModel):
    team_id: str
    sprint_length_days: int
    capacity: list[DeveloperCapacityItem]


# ---------------------------------------------------------------------------
# Shared dependency — resolve team and enforce org scope
# ---------------------------------------------------------------------------


async def _resolve_team(
    team_id: uuid.UUID,
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
) -> Team:
    """Return the Team if it belongs to the authenticated organisation; 404 otherwise."""
    org = await db.scalar(
        select(Organization).where(Organization.clerk_org_id == clerk_org_id)
    )
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organisation not found")

    team = await db.scalar(
        select(Team).where(Team.id == team_id, Team.organization_id == org.id)
    )
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

    return team


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _confidence_score(
    sprint_count: int, mean_days: float | None, std_dev: float | None
) -> float | None:
    """
    Scalar confidence (0.0–1.0) based on velocity consistency.
    Uses coefficient of variation: lower spread relative to mean = higher confidence.
    Returns None when sprint_count < threshold (insufficient data).
    """
    if sprint_count < _SUFFICIENT_SPRINT_THRESHOLD or not mean_days or mean_days <= 0:
        return None
    if not std_dev or std_dev == 0:
        return 1.0
    return round(max(0.0, 1.0 - std_dev / mean_days), 4)


def _build_profile_response(
    developer: Developer,
    rows: list[DeveloperVelocityProfile],
) -> VelocityProfileResponse:
    """
    Aggregate DeveloperVelocityProfile rows for one developer.
    mean_completion_days is averaged across domains within each ticket_type.
    sprint_count uses the maximum across all rows.
    """
    by_type: dict[str, list[DeveloperVelocityProfile]] = defaultdict(list)
    for row in rows:
        by_type[row.ticket_type or "unknown"].append(row)

    mean_by_type: dict[str, float] = {}
    for ttype, type_rows in by_type.items():
        valid = [r.mean_completion_days for r in type_rows if r.mean_completion_days is not None]
        if valid:
            mean_by_type[ttype] = round(sum(valid) / len(valid), 2)

    sprint_count = max((r.sprint_count for r in rows), default=0)
    is_sufficient = sprint_count >= _SUFFICIENT_SPRINT_THRESHOLD

    anchor = max(rows, key=lambda r: r.sprint_count, default=None)
    conf = _confidence_score(
        sprint_count,
        anchor.mean_completion_days if anchor else None,
        anchor.std_dev if anchor else None,
    )

    return VelocityProfileResponse(
        developer_id=str(developer.id),
        name=developer.name,
        mean_completion_days=mean_by_type,
        confidence_score=conf if is_sufficient else None,
        sprint_count=sprint_count,
        is_sufficient_data=is_sufficient,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/{team_id}/velocity", response_model=TeamVelocityResponse)
async def get_team_velocity(
    team: Team = Depends(_resolve_team),
    db: AsyncSession = Depends(get_db),
):
    """Per-developer velocity profiles for the team."""
    developers = (
        await db.scalars(
            select(Developer).where(
                Developer.team_id == team.id, Developer.is_active == True
            )
        )
    ).all()

    if not developers:
        return TeamVelocityResponse(team_id=str(team.id), profiles=[])

    dev_ids = [d.id for d in developers]
    profile_rows = (
        await db.scalars(
            select(DeveloperVelocityProfile).where(
                DeveloperVelocityProfile.team_id == team.id,
                DeveloperVelocityProfile.developer_id.in_(dev_ids),
            )
        )
    ).all()

    rows_by_dev: dict[uuid.UUID, list[DeveloperVelocityProfile]] = defaultdict(list)
    for row in profile_rows:
        rows_by_dev[row.developer_id].append(row)

    dev_map = {d.id: d for d in developers}
    profiles = [
        _build_profile_response(dev_map[dev_id], rows)
        for dev_id, rows in rows_by_dev.items()
        if dev_id in dev_map
    ]

    return TeamVelocityResponse(team_id=str(team.id), profiles=profiles)


@router.get("/{team_id}/velocity/{developer_id}", response_model=VelocityProfileResponse)
async def get_developer_velocity(
    developer_id: uuid.UUID,
    team: Team = Depends(_resolve_team),
    db: AsyncSession = Depends(get_db),
):
    """Velocity profile for a single developer."""
    developer = await db.scalar(
        select(Developer).where(
            Developer.id == developer_id,
            Developer.team_id == team.id,
            Developer.is_active == True,
        )
    )
    if not developer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Developer not found")

    rows = (
        await db.scalars(
            select(DeveloperVelocityProfile).where(
                DeveloperVelocityProfile.developer_id == developer_id,
                DeveloperVelocityProfile.team_id == team.id,
            )
        )
    ).all()

    if not rows:
        return VelocityProfileResponse(
            developer_id=str(developer_id),
            name=developer.name,
            mean_completion_days={},
            confidence_score=None,
            sprint_count=0,
            is_sufficient_data=False,
        )

    return _build_profile_response(developer, list(rows))


@router.get("/{team_id}/capacity", response_model=TeamCapacityResponse)
async def get_team_capacity(
    team: Team = Depends(_resolve_team),
    db: AsyncSession = Depends(get_db),
):
    """Current sprint capacity for all active developers."""
    developers = (
        await db.scalars(
            select(Developer).where(
                Developer.team_id == team.id, Developer.is_active == True
            )
        )
    ).all()

    if not developers:
        return TeamCapacityResponse(
            team_id=str(team.id),
            sprint_length_days=team.sprint_length_days,
            capacity=[],
        )

    # Use active sprint dates if available; fall back to team default
    active_sprint = await db.scalar(
        select(Sprint)
        .where(Sprint.team_id == team.id, Sprint.status == SprintStatus.ACTIVE)
        .order_by(Sprint.start_date.desc())
    )
    total_days = (
        (active_sprint.end_date - active_sprint.start_date).days
        if active_sprint and active_sprint.start_date and active_sprint.end_date
        else team.sprint_length_days
    )

    sprint_meta = SprintMeta(
        total_working_days=max(1, total_days),
        team_members=[str(d.id) for d in developers],
    )

    # PTO and meeting data not yet stored in DB — MVP placeholder (empty lists = full availability)
    capacity_rows = CapacityModel().model(sprint=sprint_meta, pto=[], meetings=[])

    dev_map = {str(d.id): d for d in developers}
    items = [
        DeveloperCapacityItem(
            developer_id=row.developer_id,
            name=dev_map[row.developer_id].name,
            available_days=row.available_days,
            availability_ratio=row.availability_ratio,
        )
        for row in capacity_rows
        if row.developer_id in dev_map
    ]

    return TeamCapacityResponse(
        team_id=str(team.id),
        sprint_length_days=total_days,
        capacity=items,
    )
