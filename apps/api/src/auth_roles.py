from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.auth import get_current_user_id, get_current_org_id
from src.database import get_db
from src.models.developer import Developer, AppRole
from src.models.organization import Organization
from src.models.team import Team

ROLE_HIERARCHY = {"developer": 0, "lead": 1, "exec": 2, "admin": 3}


async def get_current_app_role(
    user_id: str = Depends(get_current_user_id),
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
) -> str:
    """Returns app_role string. Defaults to 'developer' if no record found — never raises."""
    result = await db.execute(
        select(Developer.app_role)
        .join(Team, Developer.team_id == Team.id)
        .join(Organization, Team.organization_id == Organization.id)
        .where(
            Organization.clerk_org_id == clerk_org_id,
            Developer.clerk_user_id == user_id,
        )
        .limit(1)
    )
    row = result.scalar_one_or_none()
    return row if row is not None else "developer"


def require_role(minimum: str):
    """
    Dependency factory. Usage: Depends(require_role("exec"))
    Raises HTTP 403 if current user's role rank < minimum rank.
    """
    async def _check(role: str = Depends(get_current_app_role)):
        if ROLE_HIERARCHY.get(role, 0) < ROLE_HIERARCHY.get(minimum, 0):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires '{minimum}' role or higher.",
            )
        return role
    return _check
