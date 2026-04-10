import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.developer import Developer
from src.models.team import Team
from src.models.team_access import TeamAccessGrant
from src.models.sprint import Sprint, SprintStatus
from src.models.dependency_radar import Dependency
from src.models.retro import Retrospective
from src.models.ticket import Ticket, TicketStatus
from src.services.health import compute_health_score


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


async def get_multi_team_summary(
    team_ids: list[uuid.UUID],
    db: AsyncSession,
) -> list[dict]:
    """
    For each team: computes health score, active sprint info, completion rate,
    active dependency count, last retro date.
    Returns list sorted by health score ASC (worst first).
    """
    today = date.today()
    summaries = []

    for team_id in team_ids:
        team_result = await db.execute(select(Team).where(Team.id == team_id))
        team = team_result.scalar_one_or_none()
        if not team:
            continue

        # Active sprint
        active_sprint = None
        active_result = await db.execute(
            select(Sprint).where(
                Sprint.team_id == team_id,
                Sprint.status == SprintStatus.ACTIVE,
            ).limit(1)
        )
        active_sprint = active_result.scalar_one_or_none()

        health_score = 50
        completion_rate = 0.0
        active_sprint_name = None

        if active_sprint:
            active_sprint_name = active_sprint.name

            # Count tickets for completion rate
            tickets_result = await db.execute(
                select(Ticket).where(Ticket.sprint_id == active_sprint.id)
            )
            tickets = tickets_result.scalars().all()
            total = len(tickets)
            completed = sum(1 for t in tickets if t.status == TicketStatus.DONE)
            completion_rate = completed / total if total > 0 else 0.0

            health_score, _, _ = compute_health_score(
                committed=active_sprint.committed_points or 0.0,
                remaining=(active_sprint.committed_points or 0.0) - (active_sprint.delivered_points or 0.0),
                start=active_sprint.start_date or today,
                end=active_sprint.end_date or today,
                today=today,
                ticket_count=total,
                completed_count=completed,
            )

        # Active dependency count
        deps_result = await db.execute(
            select(Dependency).where(
                Dependency.team_id == team_id,
                Dependency.resolved_at.is_(None),
            )
        )
        active_deps_count = len(deps_result.scalars().all())

        # Last retro date
        retro_result = await db.execute(
            select(Retrospective).where(
                Retrospective.team_id == team_id,
            ).order_by(Retrospective.generated_at.desc()).limit(1)
        )
        last_retro = retro_result.scalar_one_or_none()
        last_retro_date = last_retro.generated_at.date().isoformat() if last_retro else None

        # RAG status
        if health_score >= 70:
            rag = "green"
        elif health_score >= 40:
            rag = "amber"
        else:
            rag = "red"

        summaries.append({
            "teamId": str(team_id),
            "teamName": team.name,
            "healthScore": health_score,
            "activeSprintName": active_sprint_name,
            "completionRate": round(completion_rate, 4),
            "activeDepsCount": active_deps_count,
            "lastRetroDate": last_retro_date,
            "ragStatus": rag,
        })

    # Sort worst first
    summaries.sort(key=lambda s: s["healthScore"])
    return summaries
