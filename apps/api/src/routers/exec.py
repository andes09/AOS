"""
Exec Dashboard API router.

Endpoints
---------
GET /api/exec/sector-overview
    Aggregate health overview for all teams in the organisation.
"""
from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_org_id
from src.auth_roles import require_role
from src.config import settings
from src.database import get_db
from src.models.organization import Organization
from src.models.sprint import Sprint, SprintStatus, SprintTicket
from src.models.team import Team
from src.services.health import compute_health_score

exec_router = APIRouter(tags=["exec"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class TeamSummary(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    team_id: str
    name: str
    health_score: int
    status: Literal["green", "amber", "red"]
    velocity_trend: Literal["accelerating", "stable", "declining"]
    sprint_completion_rate: float
    last_sprint_name: str | None
    has_active_sprint: bool


class SectorOverviewResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    org_id: str
    sector_health_score: float
    team_count: int
    teams: list[TeamSummary]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rag_status(score: int) -> Literal["green", "amber", "red"]:
    if score >= 70:
        return "green"
    if score >= 40:
        return "amber"
    return "red"


def _velocity_trend(
    completed_sprints: list[Sprint],
) -> Literal["accelerating", "stable", "declining"]:
    """
    Compare last completed sprint velocity vs rolling avg of prior 3.
    sprints must be ordered by end_date desc.
    """
    with_points = [s for s in completed_sprints if s.delivered_points is not None]
    if len(with_points) < 2:
        return "stable"

    last_velocity = float(with_points[0].delivered_points)
    prior = [float(s.delivered_points) for s in with_points[1:4]]
    prior_avg = sum(prior) / len(prior)
    if prior_avg <= 0:
        return "stable"

    pct_change = (last_velocity - prior_avg) / prior_avg
    if pct_change > 0.05:
        return "accelerating"
    if pct_change < -0.05:
        return "declining"
    return "stable"


def _sprint_completion_rate(completed_sprints: list[Sprint]) -> float:
    """
    Mean of delivered_points / committed_points for last 3 completed sprints.
    committed_points = 0 → treat that sprint as 1.0.
    """
    recent = list(completed_sprints)[:3]
    if not recent:
        return 0.0

    rates = []
    for s in recent:
        committed = s.committed_points or 0.0
        delivered = s.delivered_points or 0.0
        rates.append(1.0 if committed <= 0 else min(delivered / committed, 1.0))

    return round(sum(rates) / len(rates), 4)


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@exec_router.get("/sector-overview", response_model=SectorOverviewResponse)
async def get_sector_overview(
    _: str = Depends(require_role("exec")),
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """Aggregate health and velocity overview for all teams in the organisation."""
    if not settings.is_feature_enabled("exec_dashboard"):
        raise HTTPException(status_code=404, detail="Feature not available")
    org = await db.scalar(
        select(Organization).where(Organization.clerk_org_id == clerk_org_id)
    )
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organisation not found")

    teams = (
        await db.scalars(select(Team).where(Team.organization_id == org.id))
    ).all()

    team_summaries: list[TeamSummary] = []

    for team in teams:
        # --- Active sprint → health score ---
        active_sprint = await db.scalar(
            select(Sprint)
            .where(Sprint.team_id == team.id, Sprint.status == SprintStatus.ACTIVE)
            .order_by(Sprint.start_date.desc())
        )

        if active_sprint:
            tickets = (
                await db.scalars(
                    select(SprintTicket).where(SprintTicket.sprint_id == active_sprint.id)
                )
            ).all()
            committed = active_sprint.committed_points or sum(
                t.estimated_points or 0 for t in tickets
            )
            completed_pts = sum(t.estimated_points or 0 for t in tickets if t.completed)
            remaining = max(0.0, committed - completed_pts)
            today = date.today()
            start = active_sprint.start_date or today
            end = active_sprint.end_date or (start + timedelta(days=team.sprint_length_days))
            completed_count = sum(1 for t in tickets if t.completed)

            health_score, _, _ = compute_health_score(
                committed=committed,
                remaining=remaining,
                start=start,
                end=end,
                today=today,
                ticket_count=len(tickets),
                completed_count=completed_count,
            )
        else:
            health_score = 0

        # --- Completed sprints → velocity trend + completion rate ---
        completed_sprints = (
            await db.scalars(
                select(Sprint)
                .where(
                    Sprint.team_id == team.id,
                    Sprint.status == SprintStatus.COMPLETED,
                )
                .order_by(Sprint.end_date.desc())
                .limit(4)
            )
        ).all()

        trend = _velocity_trend(list(completed_sprints))
        completion_rate = _sprint_completion_rate(list(completed_sprints))

        # --- Most recent sprint name ---
        last_sprint = active_sprint or (completed_sprints[0] if completed_sprints else None)

        team_summaries.append(
            TeamSummary(
                team_id=str(team.id),
                name=team.name,
                health_score=health_score,
                status=_rag_status(health_score),
                velocity_trend=trend,
                sprint_completion_rate=completion_rate,
                last_sprint_name=last_sprint.name if last_sprint else None,
                has_active_sprint=active_sprint is not None,
            )
        )

    sector_score = (
        round(sum(t.health_score for t in team_summaries) / len(team_summaries), 2)
        if team_summaries
        else 0.0
    )

    return SectorOverviewResponse(
        org_id=str(org.id),
        sector_health_score=sector_score,
        team_count=len(teams),
        teams=team_summaries,
    )
