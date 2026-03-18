"""Shared FastAPI dependencies."""
import uuid
from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_org_id
from src.database import get_db
from src.models.organization import Organization
from src.models.team import Team


async def resolve_team(
    team_id: uuid.UUID | None = None,
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
) -> Team:
    """Return the Team if it belongs to the authenticated organisation; 404 otherwise.
    If team_id is omitted, resolves to the first team in the organisation.
    """
    org = await db.scalar(select(Organization).where(Organization.clerk_org_id == clerk_org_id))
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organisation not found")
    if team_id:
        team = await db.scalar(select(Team).where(Team.id == team_id, Team.organization_id == org.id))
    else:
        team = await db.scalar(select(Team).where(Team.organization_id == org.id))
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    return team
