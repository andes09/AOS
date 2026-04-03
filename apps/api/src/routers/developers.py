"""
Developer Profile API router.

Endpoints
---------
GET /api/developers/{developer_id}/profile
    Returns aggregated profile stats for a single developer.
    Requires lead role.
"""
import math
import uuid
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_org_id
from src.auth_roles import require_role
from src.database import get_db
from src.models.developer import Developer
from src.models.organization import Organization
from src.models.sprint import Sprint, SprintStatus, SprintTicket
from src.models.team import Team
from src.models.velocity import DeveloperVelocityProfile

router = APIRouter(prefix="/api/developers", tags=["developers"])


class DeveloperProfileResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    developer_id: str
    name: str
    role: str | None
    avg_velocity: float
    sprint_count: int
    strong_ticket_types: list[str]
    domains: list[str]
    consistency_score: int


@router.get("/{developer_id}/profile", response_model=DeveloperProfileResponse)
async def get_developer_profile(
    developer_id: uuid.UUID,
    _role: str = Depends(require_role("lead")),
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """Aggregated profile stats for a developer. Requires lead role."""
    # Resolve org
    org = await db.scalar(
        select(Organization).where(Organization.clerk_org_id == clerk_org_id)
    )
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Developer not found")

    # Load developer — 404 if not found or belongs to a different org
    developer = await db.scalar(
        select(Developer)
        .join(Team, Developer.team_id == Team.id)
        .where(
            Developer.id == developer_id,
            Team.organization_id == org.id,
        )
    )
    if not developer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Developer not found")

    # Aggregate per-sprint delivered points from completed sprint ticket assignments
    sprint_tickets = (
        await db.scalars(
            select(SprintTicket).where(SprintTicket.assignee_id == developer_id)
        )
    ).all()

    sprint_ids = list({st.sprint_id for st in sprint_tickets})
    if sprint_ids:
        completed_sprints = (
            await db.scalars(
                select(Sprint).where(
                    Sprint.id.in_(sprint_ids),
                    Sprint.status == SprintStatus.COMPLETED,
                )
            )
        ).all()
    else:
        completed_sprints = []

    completed_sprint_ids = {s.id for s in completed_sprints}

    # Per-sprint: sum of points for completed tickets assigned to this developer
    points_by_sprint: dict[uuid.UUID, float] = defaultdict(float)
    for st in sprint_tickets:
        if st.sprint_id in completed_sprint_ids and st.completed:
            pts = st.actual_points if st.actual_points is not None else (st.estimated_points or 0.0)
            points_by_sprint[st.sprint_id] += pts

    sprint_count = len(completed_sprint_ids)
    per_sprint_points = list(points_by_sprint.values())

    if per_sprint_points:
        mean_vel = sum(per_sprint_points) / len(per_sprint_points)
        variance = sum((p - mean_vel) ** 2 for p in per_sprint_points) / len(per_sprint_points)
        std_dev = math.sqrt(variance)
        if mean_vel > 0:
            consistency_score = max(0, 100 - round((std_dev / mean_vel) * 100))
        else:
            consistency_score = 0
        avg_velocity = round(mean_vel, 2)
    else:
        avg_velocity = 0.0
        consistency_score = 0

    # strongTicketTypes from DeveloperVelocityProfile — top 3 by sample_size descending
    velocity_profiles = (
        await db.scalars(
            select(DeveloperVelocityProfile).where(
                DeveloperVelocityProfile.developer_id == developer_id
            )
        )
    ).all()

    # Group by ticket_type, sum sample_size as proxy for completion count
    type_samples: dict[str, int] = defaultdict(int)
    for vp in velocity_profiles:
        if vp.ticket_type:
            type_samples[vp.ticket_type] += vp.sample_size

    strong_ticket_types = [
        t for t, _ in sorted(type_samples.items(), key=lambda x: x[1], reverse=True)
    ][:3]

    # Distinct domains from velocity profiles
    domains = sorted({vp.domain for vp in velocity_profiles if vp.domain})

    return DeveloperProfileResponse(
        developer_id=str(developer.id),
        name=developer.name,
        role=developer.role,
        avg_velocity=avg_velocity,
        sprint_count=sprint_count,
        strong_ticket_types=strong_ticket_types,
        domains=domains,
        consistency_score=consistency_score,
    )
