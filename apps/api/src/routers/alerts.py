"""
Alerts API router.

Endpoints
---------
GET  /api/alerts?team_id=<uuid>
    Returns active (non-dismissed) alerts for the current sprint.
    Returns [] when no active sprint exists (not 404).

PATCH /api/alerts/{alert_id}/dismiss?team_id=<uuid>
    Marks an alert as dismissed.
"""
import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.dependencies import resolve_team
from src.models.alert import SprintAlert
from src.models.sprint import Sprint, SprintStatus
from src.models.team import Team

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


class AlertResponse(BaseModel):
    id: str
    type: str
    description: str
    recommended_action: str
    created_at: datetime
    dismissed: bool


@router.get("", response_model=list[AlertResponse])
async def get_alerts(
    team: Team = Depends(resolve_team),
    db: AsyncSession = Depends(get_db),
):
    """Return active alerts for the current sprint. Returns [] when no active sprint."""
    sprint = await db.scalar(
        select(Sprint)
        .where(Sprint.team_id == team.id, Sprint.status == SprintStatus.ACTIVE)
        .order_by(Sprint.start_date.desc())
    )
    if not sprint:
        return []

    alerts = (
        await db.scalars(
            select(SprintAlert)
            .where(
                SprintAlert.sprint_id == sprint.id,
                SprintAlert.dismissed.is_(False),
            )
            .order_by(SprintAlert.created_at.desc())
        )
    ).all()

    return [
        AlertResponse(
            id=str(a.id),
            type=a.type.value,
            description=a.description,
            recommended_action=a.recommended_action,
            created_at=a.created_at,
            dismissed=a.dismissed,
        )
        for a in alerts
    ]


@router.patch("/{alert_id}/dismiss", response_model=AlertResponse)
async def dismiss_alert(
    alert_id: uuid.UUID,
    team: Team = Depends(resolve_team),
    db: AsyncSession = Depends(get_db),
):
    """Mark an alert as dismissed. 404 if alert not found or not owned by this team."""
    alert = await db.scalar(
        select(SprintAlert).where(
            SprintAlert.id == alert_id,
            SprintAlert.team_id == team.id,
        )
    )
    if not alert:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")

    alert.dismissed = True
    await db.commit()
    await db.refresh(alert)

    return AlertResponse(
        id=str(alert.id),
        type=alert.type.value,
        description=alert.description,
        recommended_action=alert.recommended_action,
        created_at=alert.created_at,
        dismissed=alert.dismissed,
    )
