import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.developer import Developer
from src.models.team import Team
from src.models.team_access import TeamAccessGrant


async def get_accessible_teams(
    clerk_user_id: str,
    clerk_org_id: str,
    db: AsyncSession,
) -> list[Team]:
    """
    Returns all teams the user has access to:
    1. The user's primary team (via Developer.team_id)
    2. Any teams in TeamAccessGrant where developer_id matches the user's Developer row
    All teams must belong to the same org (enforced by the Developer → Team → Organization chain).
    Returns deduplicated list sorted by team name.
    """
    # Find the developer row
    dev_result = await db.execute(
        select(Developer).where(Developer.clerk_user_id == clerk_user_id)
    )
    developer = dev_result.scalar_one_or_none()
    if not developer:
        return []

    team_ids: set[uuid.UUID] = {developer.team_id}

    # Add any granted teams
    grants_result = await db.execute(
        select(TeamAccessGrant).where(TeamAccessGrant.developer_id == developer.id)
    )
    for grant in grants_result.scalars().all():
        team_ids.add(grant.team_id)

    teams_result = await db.execute(
        select(Team).where(Team.id.in_(list(team_ids)))
    )
    teams = teams_result.scalars().all()
    return sorted(teams, key=lambda t: t.name)
