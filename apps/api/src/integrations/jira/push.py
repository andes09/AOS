from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.developer import Developer, TeamMember


async def resolve_jira_account_id(developer_id: str, team_id: str, db: AsyncSession) -> str | None:
    """
    Joins Developer → TeamMember on email within the same team.
    Canonical join: Developer.email == TeamMember.email AND TeamMember.team_id == team_id
    Returns jira_account_id or None if no match.
    """
    result = await db.execute(
        select(TeamMember.jira_account_id)
        .join(Developer, Developer.email == TeamMember.email)
        .where(Developer.id == developer_id)
        .where(TeamMember.team_id == team_id)
        .limit(1)
    )
    row = result.scalar_one_or_none()
    return row
