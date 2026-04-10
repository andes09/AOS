import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.organization import Organization
from src.models.team import Team
from src.models.jira_connection import JiraConnection
from src.models.sprint import Sprint, SprintStatus
from src.models.ticket import Ticket, TicketStatus
from src.integrations.jira.client import JiraClient


async def get_onboarding_status(org_id: uuid.UUID, team_id: uuid.UUID, db: AsyncSession) -> dict:
    """
    Returns a dict with five fields describing onboarding progress:
      jiraConnected, boardSelected, importStatus, importedSprints, onboardingCompleted
    """
    # Check Jira connection
    conn_result = await db.execute(
        select(JiraConnection).where(
            JiraConnection.organization_id == org_id,
            JiraConnection.is_active == True,
        )
    )
    jira_connected = conn_result.scalar_one_or_none() is not None

    # Load team and org
    team_result = await db.execute(select(Team).where(Team.id == team_id))
    team = team_result.scalar_one_or_none()

    org_result = await db.execute(select(Organization).where(Organization.id == org_id))
    org = org_result.scalar_one_or_none()

    board_selected = bool(team and team.jira_board_id)
    import_status = team.jira_import_status if team else "pending"
    imported_sprints = team.jira_import_sprints_imported if team else None
    onboarding_completed = org.onboarding_completed_at is not None if org else False

    return {
        "jiraConnected": jira_connected,
        "boardSelected": board_selected,
        "importStatus": import_status,
        "importedSprints": imported_sprints,
        "onboardingCompleted": onboarding_completed,
    }


async def import_jira_sprint_history(
    team: Team,
    jira_client: JiraClient,
    sprint_count: int,
    db: AsyncSession,
) -> int:
    """
    Fetches the last `sprint_count` completed sprints from Jira for the team's project.
    Upserts Sprint rows (COMPLETED status) with committed_points and delivered_points.
    Also upserts Ticket rows belonging to those sprints.
    Returns the count of sprints imported.
    Sets team.jira_import_status = "completed" on success, "failed" on error.
    """
    team.jira_import_status = "in_progress"
    await db.flush()

    try:
        # Get all sprints visible via JQL and pick the most recent completed ones
        all_sprints = await jira_client.get_sprints()
        completed_sprints = [s for s in all_sprints if s.get("state") == "closed"]
        # Sort descending by id (proxy for recency)
        completed_sprints.sort(key=lambda s: s.get("id", 0), reverse=True)
        to_import = completed_sprints[:sprint_count]

        imported = 0
        for jira_sprint in to_import:
            jira_sprint_id = str(jira_sprint.get("id", ""))
            sprint_name = jira_sprint.get("name", f"Sprint {jira_sprint_id}")
            start_date = jira_sprint.get("startDate")
            end_date = jira_sprint.get("endDate")

            # Check for existing sprint by jira_board_id + name match
            existing = await db.execute(
                select(Sprint).where(
                    Sprint.team_id == team.id,
                    Sprint.name == sprint_name,
                )
            )
            sprint = existing.scalar_one_or_none()

            if not sprint:
                from datetime import date
                sprint = Sprint(
                    id=uuid.uuid4(),
                    team_id=team.id,
                    name=sprint_name,
                    status=SprintStatus.COMPLETED,
                    start_date=_parse_date(start_date),
                    end_date=_parse_date(end_date),
                    committed_points=0.0,
                    delivered_points=0.0,
                )
                db.add(sprint)
                await db.flush()

            # Fetch issues for this sprint
            issues = await jira_client.get_sprint_issues(jira_sprint_id)
            committed = 0.0
            delivered = 0.0
            for issue in issues:
                fields = issue.get("fields", {})
                story_pts = fields.get("customfield_10016") or 0
                committed += float(story_pts)
                status_cat = (fields.get("status") or {}).get("statusCategory", {}).get("key", "")
                if status_cat == "done":
                    delivered += float(story_pts)

                # Upsert ticket
                jira_issue_id = issue.get("id", "")
                jira_issue_key = issue.get("key", "")
                ticket_result = await db.execute(
                    select(Ticket).where(Ticket.jira_issue_id == jira_issue_id)
                )
                ticket = ticket_result.scalar_one_or_none()
                if not ticket:
                    ticket = Ticket(
                        id=uuid.uuid4(),
                        sprint_id=sprint.id,
                        team_id=team.id,
                        jira_issue_id=jira_issue_id,
                        jira_issue_key=jira_issue_key,
                        title=fields.get("summary", ""),
                        status=TicketStatus.DONE if status_cat == "done" else TicketStatus.TODO,
                        story_points_estimated=float(story_pts) if story_pts else None,
                    )
                    db.add(ticket)

            sprint.committed_points = committed
            sprint.delivered_points = delivered
            await db.flush()
            imported += 1

        team.jira_import_status = "completed"
        team.jira_import_sprints_imported = imported
        await db.flush()
        return imported

    except Exception:
        team.jira_import_status = "failed"
        await db.flush()
        raise


def _parse_date(date_str: str | None):
    if not date_str:
        return None
    try:
        from datetime import date
        return datetime.fromisoformat(date_str.replace("Z", "+00:00")).date()
    except Exception:
        return None
