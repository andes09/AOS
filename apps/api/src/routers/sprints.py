"""
Sprint API router.

Endpoints
---------
GET /api/sprints/current
    Returns the active sprint for the authenticated team.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import date

from src.database import get_db
from src.models.sprint import Sprint, SprintStatus
from src.models.team import Team
from src.dependencies import resolve_team

router = APIRouter(prefix="/api/sprints", tags=["sprints"])


class CurrentSprintResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    id: str
    name: str
    start_date: date | None
    end_date: date | None
    sprint_length: int
    total_points: float | None
    status: str


@router.get("/current", response_model=CurrentSprintResponse)
async def get_current_sprint(
    team: Team = Depends(resolve_team),
    db: AsyncSession = Depends(get_db),
):
    """Return the active sprint for the authenticated team."""
    sprint = await db.scalar(
        select(Sprint)
        .where(Sprint.team_id == team.id, Sprint.status == SprintStatus.ACTIVE)
        .order_by(Sprint.start_date.desc())
    )
    if not sprint:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active sprint")
    return CurrentSprintResponse(
        id=str(sprint.id),
        name=sprint.name,
        start_date=sprint.start_date,
        end_date=sprint.end_date,
        sprint_length=team.sprint_length_days,
        total_points=sprint.committed_points,
        status=sprint.status.value,
    )
