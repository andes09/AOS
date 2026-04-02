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
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_org_id
from src.database import get_db
from src.dependencies import resolve_team as resolve_team_query  # query-param version; _resolve_team below is path-param for /api/teams/{team_id}/...
from src.models.developer import Developer
from src.models.organization import Organization
from src.models.sprint import Sprint, SprintStatus, SprintTicket
from src.models.team import Team
from src.models.velocity import DeveloperVelocityProfile
from src.services.velocity import CapacityModel
from src.services.velocity.schemas import SprintMeta
from src.services.velocity.stats import compute_velocity_stats
from src.services.health import compute_health_score

router = APIRouter(prefix="/api/teams", tags=["velocity"])
dashboard_router = APIRouter(prefix="/api/velocity", tags=["velocity-dashboard"])

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
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    developer_id: str
    name: str
    available_days: float
    availability_ratio: float
    committed_points: float = 0.0
    completed_points: float = 0.0
    is_over_capacity: bool = False


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
                Developer.team_id == team.id, Developer.is_active.is_(True)
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

    profiles = []
    for dev in developers:
        rows = rows_by_dev.get(dev.id, [])
        if rows:
            profiles.append(_build_profile_response(dev, rows))
        else:
            profiles.append(
                VelocityProfileResponse(
                    developer_id=str(dev.id),
                    name=dev.name,
                    mean_completion_days={},
                    confidence_score=None,
                    sprint_count=0,
                    is_sufficient_data=False,
                )
            )

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
            Developer.is_active.is_(True),
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
                Developer.team_id == team.id, Developer.is_active.is_(True)
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
        (active_sprint.end_date - active_sprint.start_date).days  # Raw calendar days — does not exclude weekends or holidays (MVP)
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


# ---------------------------------------------------------------------------
# Dashboard response models
# ---------------------------------------------------------------------------


class BurndownDataPoint(BaseModel):
    day: int
    ideal: float
    actual: float | None
    predicted: float | None


class BurndownResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    data: list[BurndownDataPoint]
    sprint_length: int
    predicted_end_day: int


class SprintCapacityResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    sprint_id: str
    sprint_length_days: int
    capacity: list[DeveloperCapacityItem]


class HealthScoreResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    score: int
    trend: str
    reasons: list[str]
    updated_at: datetime


class ConfidenceIntervalRange(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    lower: float
    upper: float


class ForecastRange(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    point: float
    lower: float
    upper: float


class SprintPoint(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    name: str
    velocity: float


class VelocityStatsResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    team_id: str
    window: int
    sprint_count: int
    rolling_avg: float
    weighted_avg: float
    std_dev: float
    trend: float
    confidence_interval: ConfidenceIntervalRange
    outlier_sprints: list[str]
    forecast: ForecastRange
    sprint_window: list[SprintPoint]


# ---------------------------------------------------------------------------
# Dashboard helpers  (touch: force rebuild 2026-03-26)
# ---------------------------------------------------------------------------


def _build_burndown_data(
    start: date, end: date, committed: float, remaining: float, today: date
) -> tuple[list[BurndownDataPoint], int]:
    """Build merged burndown data points indexed by sprint day, plus predicted end day."""
    total_days = max((end - start).days, 1)
    days_elapsed = max((today - start).days, 0)
    burned = committed - remaining
    daily_burn = burned / max(days_elapsed, 1) if days_elapsed > 0 else 0
    days_to_zero = (remaining / daily_burn) if daily_burn > 0 else total_days
    predicted_end_day = min(int(days_elapsed + days_to_zero), total_days * 2)

    points: list[BurndownDataPoint] = []
    for i in range(total_days + 1):
        ideal = round(committed * (1 - i / total_days), 2)
        actual: float | None = None
        if i <= days_elapsed:
            actual = max(0.0, round(committed - (burned * i / max(days_elapsed, 1)), 2))
        predicted: float | None = None
        if i >= days_elapsed:
            pred_val = remaining - daily_burn * (i - days_elapsed)
            predicted = round(max(0.0, pred_val), 2)
        points.append(BurndownDataPoint(day=i, ideal=ideal, actual=actual, predicted=predicted))

    return points, predicted_end_day


# ---------------------------------------------------------------------------
# Dashboard endpoints
# ---------------------------------------------------------------------------


@dashboard_router.get("/burndown", response_model=BurndownResponse)
async def get_burndown(
    team: Team = Depends(resolve_team_query),
    db: AsyncSession = Depends(get_db),
):
    """Burndown data for the active sprint."""
    sprint = await db.scalar(
        select(Sprint).where(Sprint.team_id == team.id, Sprint.status == SprintStatus.ACTIVE)
        .order_by(Sprint.start_date.desc())
    )
    if not sprint:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active sprint")

    tickets = (await db.scalars(select(SprintTicket).where(SprintTicket.sprint_id == sprint.id))).all()
    committed = sprint.committed_points or sum(t.estimated_points or 0 for t in tickets)
    completed_pts = sum(t.estimated_points or 0 for t in tickets if t.completed)
    remaining = max(0.0, committed - completed_pts)
    today = date.today()
    start = sprint.start_date or today
    end = sprint.end_date or (start + timedelta(days=team.sprint_length_days))

    data, predicted_end_day = _build_burndown_data(start, end, committed, remaining, today)
    sprint_length = (end - start).days

    return BurndownResponse(data=data, sprint_length=sprint_length, predicted_end_day=predicted_end_day)


@dashboard_router.get("/capacity", response_model=SprintCapacityResponse)
async def get_sprint_capacity(
    team: Team = Depends(resolve_team_query),
    db: AsyncSession = Depends(get_db),
):
    """Current capacity per developer for the active sprint."""
    active_sprint = await db.scalar(
        select(Sprint).where(Sprint.team_id == team.id, Sprint.status == SprintStatus.ACTIVE)
        .order_by(Sprint.start_date.desc())
    )
    if not active_sprint:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active sprint")

    developers = (
        await db.scalars(select(Developer).where(Developer.team_id == team.id, Developer.is_active.is_(True)))
    ).all()

    total_days = (
        (active_sprint.end_date - active_sprint.start_date).days
        if active_sprint.start_date and active_sprint.end_date
        else team.sprint_length_days
    )

    if not developers:
        return SprintCapacityResponse(sprint_id=str(active_sprint.id), sprint_length_days=max(1, total_days), capacity=[])

    sprint_meta = SprintMeta(total_working_days=max(1, total_days), team_members=[str(d.id) for d in developers])
    capacity_rows = CapacityModel().model(sprint=sprint_meta, pto=[], meetings=[])
    dev_map = {str(d.id): d for d in developers}

    sprint_tickets = (
        await db.scalars(select(SprintTicket).where(SprintTicket.sprint_id == active_sprint.id))
    ).all()
    committed_by_dev: dict[str, float] = {}
    completed_by_dev: dict[str, float] = {}
    for t in sprint_tickets:
        if t.assignee_id:
            key = str(t.assignee_id)
            committed_by_dev[key] = committed_by_dev.get(key, 0.0) + (t.estimated_points or 0.0)
            if t.completed:
                completed_by_dev[key] = completed_by_dev.get(key, 0.0) + (t.actual_points or t.estimated_points or 0.0)

    items = [
        DeveloperCapacityItem(
            developer_id=row.developer_id,
            name=dev_map[row.developer_id].name,
            available_days=row.available_days,
            availability_ratio=row.availability_ratio,
            committed_points=committed_by_dev.get(row.developer_id, 0.0),
            completed_points=completed_by_dev.get(row.developer_id, 0.0),
            is_over_capacity=committed_by_dev.get(row.developer_id, 0.0) > row.available_days * 2,
        )
        for row in capacity_rows
        if row.developer_id in dev_map
    ]
    return SprintCapacityResponse(sprint_id=str(active_sprint.id), sprint_length_days=total_days, capacity=items)


@dashboard_router.get("/health-score", response_model=HealthScoreResponse)
async def get_health_score(
    team: Team = Depends(resolve_team_query),
    db: AsyncSession = Depends(get_db),
):
    """Sprint health score (0–100) with trend and three explanatory bullets."""
    sprint = await db.scalar(
        select(Sprint).where(Sprint.team_id == team.id, Sprint.status == SprintStatus.ACTIVE)
        .order_by(Sprint.start_date.desc())
    )
    if not sprint:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active sprint")

    tickets = (await db.scalars(select(SprintTicket).where(SprintTicket.sprint_id == sprint.id))).all()
    committed = sprint.committed_points or sum(t.estimated_points or 0 for t in tickets)
    completed_pts = sum(t.estimated_points or 0 for t in tickets if t.completed)
    remaining = max(0.0, committed - completed_pts)
    today = date.today()
    start = sprint.start_date or today
    end = sprint.end_date or (start + timedelta(days=team.sprint_length_days))
    completed_count = sum(1 for t in tickets if t.completed)

    score, trend, reasons = compute_health_score(
        committed=committed, remaining=remaining, start=start, end=end,
        today=today, ticket_count=len(tickets), completed_count=completed_count,
    )
    return HealthScoreResponse(score=score, trend=trend, reasons=reasons, updated_at=datetime.now(timezone.utc))


@dashboard_router.get("/stats", response_model=VelocityStatsResponse)
async def get_velocity_stats(
    window: int = Query(default=6, ge=3, le=12),
    team: Team = Depends(resolve_team_query),
    db: AsyncSession = Depends(get_db),
):
    """Statistical velocity analysis for the team over the last N completed sprints."""
    sprints = (
        await db.scalars(
            select(Sprint)
            .where(
                Sprint.team_id == team.id,
                Sprint.status == SprintStatus.COMPLETED,
                Sprint.delivered_points.isnot(None),
            )
            .order_by(Sprint.end_date.asc())
        )
    ).all()

    if len(sprints) < 3:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Insufficient sprint data (need at least 3 completed sprints with delivered points)",
        )

    velocities = [float(s.delivered_points) for s in sprints]
    stats = compute_velocity_stats(velocities, window=window)

    # Map outlier indices (relative to window slice) → sprint IDs
    window_sprints = list(sprints[-window:])
    outlier_sprint_ids = [
        str(window_sprints[i].id)
        for i in stats.outlier_sprint_indices
        if i < len(window_sprints)
    ]

    sprint_window_points = [
        SprintPoint(name=s.name, velocity=float(s.delivered_points))
        for s in window_sprints
    ]

    return VelocityStatsResponse(
        team_id=str(team.id),
        window=window,
        sprint_count=len(sprints),
        rolling_avg=stats.rolling_avg,
        weighted_avg=stats.weighted_avg,
        std_dev=stats.std_dev,
        trend=stats.trend,
        confidence_interval=ConfidenceIntervalRange(
            lower=stats.ci_lower,
            upper=stats.ci_upper,
        ),
        outlier_sprints=outlier_sprint_ids,
        forecast=ForecastRange(
            point=stats.forecast_point,
            lower=stats.forecast_lower,
            upper=stats.forecast_upper,
        ),
        sprint_window=sprint_window_points,
    )
