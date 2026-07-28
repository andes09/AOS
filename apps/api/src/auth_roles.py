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
    if row is None:
        return "developer"
    # SQLAlchemy returns the AppRole enum member, not the string — extract its value.
    return row.value if isinstance(row, AppRole) else str(row)


def role_at_least(role: str | AppRole, minimum: str) -> bool:
    """
    Plain predicate behind the ROLE_HIERARCHY comparison — extracted so the
    MCP `regenerate_milestone` tool's role gate (src/mcp_server/tools.py) can
    reuse the exact same comparison `require_role` uses below, rather than a
    second copy of it. MCP tool calls carry an Omada-minted opaque token
    (never a Clerk JWT), so they can't go through `Depends(require_role(...))`
    directly — but the rank comparison itself is identical.

    `role` is normalized defensively: `require_role`'s caller already gets a
    plain string via `get_current_app_role` (which does its own
    `AppRole`-member normalization), but the MCP tool passes a freshly-loaded
    `Developer.app_role` straight from the DB — a `SAEnum(AppRole,
    native_enum=False)` column, which reloads as the enum *member*, not its
    string value (same footgun documented on `Task.status`/`Project.status`
    elsewhere in this codebase). Normalizing here means both callers are safe
    regardless of which shape they hand in.
    """
    role = role.value if isinstance(role, AppRole) else role
    return ROLE_HIERARCHY.get(role, 0) >= ROLE_HIERARCHY.get(minimum, 0)


def require_role(minimum: str):
    """
    Dependency factory. Usage: Depends(require_role("exec"))
    Raises HTTP 403 if current user's role rank < minimum rank.
    """
    async def _check(role: str = Depends(get_current_app_role)):
        if not role_at_least(role, minimum):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires '{minimum}' role or higher.",
            )
        return role
    return _check
