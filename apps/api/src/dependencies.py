"""Shared FastAPI dependencies."""
import uuid
from datetime import datetime

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_org_id, get_current_user_id
from src.database import get_db
from src.models.organization import Organization
from src.models.team import Team
from src.services import activity


async def mark_developer_active(
    clerk_user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> datetime | None:
    """Touch the caller's `last_active_at` and return its *previous* value.

    Attach it as a router-level dependency to cover a whole surface (roadmap
    load + every task mutation) in one line, or as an explicit per-route
    `Depends()` when the handler needs the previous value — e.g. the
    re-engagement summary, which must read how long the user was away before
    this very request overwrites it. FastAPI caches the call per request, so
    doing both on one route still touches only once.

    Never raises: a signed-in user with no developer row simply yields None.

    Commits the touch itself rather than leaning on the session manager's
    end-of-request commit: on a plain GET (roadmap load, the summary) nothing
    else writes, so the activity signal would otherwise ride on an implicit
    commit that's easy to break. On a PATCH the dependency runs first, so this
    early commit only persists the caller's timestamp; the handler's own commit
    still carries the task change (and the assignee touch) afterward.
    """
    previous = await activity.touch_by_clerk_user(clerk_user_id, db)
    await db.commit()
    return previous


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
