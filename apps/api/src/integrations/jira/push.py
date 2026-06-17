from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.developer import Developer


async def resolve_jira_account_id(developer_id: str, team_id: str, db: AsyncSession) -> str | None:
    """Return the Jira account ID for a developer, or None if not linked."""
    result = await db.execute(
        select(Developer.jira_account_id)
        .where(Developer.id == developer_id, Developer.team_id == team_id)
    )
    return result.scalar_one_or_none()
