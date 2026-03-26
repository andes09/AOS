"""
Celery tasks for syncing Jira data into the AgileOS database.

sync_jira_team  — full sync: boards → sprints → issues → users
sync_jira_sprint — incremental sync for a single sprint
"""

import uuid
import logging
from datetime import datetime, date

from sqlalchemy import select, create_engine
from sqlalchemy.orm import Session

from src.worker import celery_app
from src.config import settings
from src.services.encryption import decrypt
from src.integrations.jira.client import JiraClient
from src.integrations.jira.oauth import refresh_access_token

logger = logging.getLogger(__name__)

# Sync tasks use a synchronous SQLAlchemy session (Celery workers are sync).
def _get_sync_session() -> Session:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    engine = create_engine(settings.database_url_sync)
    return sessionmaker(bind=engine)()


def _get_fresh_client(connection) -> JiraClient:
    """Return a JiraClient, refreshing the access token if needed."""
    import asyncio

    access_token = decrypt(connection.encrypted_access_token)

    if connection.token_expires_at and connection.token_expires_at <= datetime.utcnow():
        refresh_tok = decrypt(connection.encrypted_refresh_token)
        tokens = asyncio.get_event_loop().run_until_complete(
            refresh_access_token(refresh_tok)
        )
        access_token = tokens["access_token"]
        # Persist refreshed tokens
        from src.services.encryption import encrypt
        connection.encrypted_access_token = encrypt(access_token)
        if "refresh_token" in tokens:
            connection.encrypted_refresh_token = encrypt(tokens["refresh_token"])
        if "expires_in" in tokens:
            from datetime import timedelta
            connection.token_expires_at = datetime.utcnow() + timedelta(seconds=tokens["expires_in"])

    return JiraClient(cloud_id=connection.jira_cloud_id, access_token=access_token)


def _map_jira_status(jira_status: str) -> str:
    """Normalise Jira status categories to TicketStatus enum values."""
    status_lower = jira_status.lower()
    mapping = {
        "to do": "todo",
        "in progress": "in_progress",
        "in review": "in_review",
        "done": "done",
        "cancelled": "cancelled",
    }
    return mapping.get(status_lower, "todo")


def _parse_date(iso_str: str | None) -> date | None:
    if not iso_str:
        return None
    try:
        return datetime.fromisoformat(iso_str.rstrip("Z")).date()
    except (ValueError, AttributeError):
        return None


def _parse_datetime(iso_str: str | None) -> datetime | None:
    if not iso_str:
        return None
    try:
        return datetime.fromisoformat(iso_str.rstrip("Z"))
    except (ValueError, AttributeError):
        return None


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def sync_jira_team(self, team_id: str):
    """Full sync of all sprints and issues for a team from Jira."""
    import asyncio
    from src.models.team import Team
    from src.models.jira_connection import JiraConnection

    logger.info("Starting full Jira sync for team %s", team_id)
    db = _get_sync_session()
    try:
        team = db.get(Team, uuid.UUID(team_id))
        if not team:
            logger.warning("Team %s not found", team_id)
            return

        connection = db.execute(
            select(JiraConnection)
            .where(
                JiraConnection.organization_id == team.organization_id,
                JiraConnection.is_active == True,
            )
        ).scalar_one_or_none()

        if not connection:
            logger.warning("No active Jira connection for org of team %s", team_id)
            return

        client = _get_fresh_client(connection)

        # Sync users first so we can match assignees when syncing issues
        users = asyncio.get_event_loop().run_until_complete(client.get_users())
        _upsert_team_members(db, team, users)

        # Sync sprints (uses JQL — no Jira Software scope required)
        sprints = asyncio.get_event_loop().run_until_complete(
            client.get_sprints()
        )
        from src.models.sprint import Sprint as SprintModel

        for jira_sprint in sprints:
            sprint_obj = _upsert_sprint(db, team, jira_sprint)
            issues = asyncio.get_event_loop().run_until_complete(
                client.get_sprint_issues(str(jira_sprint["id"]))
            )
            if sprint_obj:
                _upsert_issues(db, team, sprint_obj, issues)

        connection.last_synced_at = datetime.utcnow()
        db.commit()
        logger.info("Full Jira sync complete for team %s", team_id)

    except Exception as exc:
        db.rollback()
        logger.exception("Jira sync failed for team %s: %s", team_id, exc)
        raise self.retry(exc=exc)
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def sync_jira_sprint(self, team_id: str, jira_sprint_id: str):
    """Incremental sync for a single sprint's issues from Jira."""
    import asyncio
    from src.models.team import Team
    from src.models.sprint import Sprint
    from src.models.jira_connection import JiraConnection

    logger.info("Syncing sprint %s for team %s", jira_sprint_id, team_id)
    db = _get_sync_session()
    try:
        team = db.get(Team, uuid.UUID(team_id))
        if not team:
            return

        connection = db.execute(
            select(JiraConnection)
            .where(
                JiraConnection.organization_id == team.organization_id,
                JiraConnection.is_active == True,
            )
        ).scalar_one_or_none()
        if not connection:
            return

        client = _get_fresh_client(connection)

        sprint_obj = db.execute(
            select(Sprint).where(
                Sprint.team_id == team.id,
                Sprint.jira_sprint_id == jira_sprint_id,
            )
        ).scalar_one_or_none()

        if not sprint_obj:
            logger.warning("Sprint %s not found locally; run full team sync first", jira_sprint_id)
            return

        issues = asyncio.get_event_loop().run_until_complete(
            client.get_sprint_issues(jira_sprint_id)
        )
        _upsert_issues(db, team, sprint_obj, issues)
        db.commit()
        logger.info("Sprint %s sync complete for team %s", jira_sprint_id, team_id)

    except Exception as exc:
        db.rollback()
        logger.exception("Sprint sync failed: %s", exc)
        raise self.retry(exc=exc)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _upsert_team_members(db: Session, team, jira_users: list[dict]):
    from src.models.developer import TeamMember

    for user in jira_users:
        account_id = user.get("accountId")
        if not account_id:
            continue
        member = db.execute(
            select(TeamMember).where(
                TeamMember.team_id == team.id,
                TeamMember.jira_account_id == account_id,
            )
        ).scalar_one_or_none()
        if member is None:
            member = TeamMember(
                team_id=team.id,
                jira_account_id=account_id,
                display_name=user.get("displayName", account_id),
                email=user.get("emailAddress"),
            )
            db.add(member)
        else:
            member.display_name = user.get("displayName", member.display_name)
            member.email = user.get("emailAddress", member.email)


def _upsert_sprint(db: Session, team, jira_sprint: dict):
    from src.models.sprint import Sprint, SprintStatus

    jira_id = str(jira_sprint["id"])
    sprint = db.execute(
        select(Sprint).where(
            Sprint.team_id == team.id,
            Sprint.jira_sprint_id == jira_id,
        )
    ).scalar_one_or_none()

    state = jira_sprint.get("state", "").lower()
    status_map = {
        "active": SprintStatus.ACTIVE,
        "closed": SprintStatus.COMPLETED,
        "future": SprintStatus.PLANNING,
    }
    status = status_map.get(state, SprintStatus.PLANNING)

    if sprint is None:
        sprint = Sprint(
            team_id=team.id,
            jira_sprint_id=jira_id,
            name=jira_sprint.get("name", f"Sprint {jira_id}"),
            status=status,
            start_date=_parse_date(jira_sprint.get("startDate")),
            end_date=_parse_date(jira_sprint.get("endDate")),
        )
        db.add(sprint)
    else:
        sprint.name = jira_sprint.get("name", sprint.name)
        sprint.status = status
        sprint.start_date = _parse_date(jira_sprint.get("startDate")) or sprint.start_date
        sprint.end_date = _parse_date(jira_sprint.get("endDate")) or sprint.end_date

    db.flush()
    return sprint


def _upsert_issues(db: Session, team, sprint, jira_issues: list[dict]):
    from src.models.ticket import Ticket, TicketStatus
    from src.models.developer import TeamMember

    for issue in jira_issues:
        jira_issue_id = issue["id"]
        fields = issue.get("fields", {})

        # Resolve assignee
        assignee_id = None
        assignee_data = fields.get("assignee")
        if assignee_data:
            member = db.execute(
                select(TeamMember).where(
                    TeamMember.team_id == team.id,
                    TeamMember.jira_account_id == assignee_data.get("accountId"),
                )
            ).scalar_one_or_none()
            if member:
                assignee_id = member.id

        status_name = fields.get("status", {}).get("name", "To Do")
        ticket_status_str = _map_jira_status(status_name)
        try:
            ticket_status = TicketStatus(ticket_status_str)
        except ValueError:
            ticket_status = TicketStatus.TODO

        # Story points: Jira stores them under customfield_10016 or story_points
        story_points = (
            fields.get("story_points")
            or fields.get("customfield_10016")
            or fields.get("customfield_10028")
        )

        time_estimate_seconds = fields.get("timeoriginalestimate")
        time_spent_seconds = fields.get("timespent")

        ticket = db.execute(
            select(Ticket).where(Ticket.jira_issue_id == jira_issue_id)
        ).scalar_one_or_none()

        if ticket is None:
            ticket = Ticket(
                sprint_id=sprint.id,
                team_id=team.id,
                assignee_id=assignee_id,
                jira_issue_id=jira_issue_id,
                jira_issue_key=issue.get("key"),
                title=fields.get("summary", ""),
                status=ticket_status,
                ticket_type=fields.get("issuetype", {}).get("name"),
                story_points_estimated=float(story_points) if story_points is not None else None,
                time_estimate_hours=time_estimate_seconds / 3600 if time_estimate_seconds else None,
                time_actual_hours=time_spent_seconds / 3600 if time_spent_seconds else None,
                labels=fields.get("labels"),
                components=[c.get("name") for c in fields.get("components", [])],
                created_at=_parse_datetime(fields.get("created")) or datetime.utcnow(),
                jira_updated_at=_parse_datetime(fields.get("updated")),
            )
            db.add(ticket)
        else:
            ticket.sprint_id = sprint.id
            ticket.assignee_id = assignee_id
            ticket.status = ticket_status
            ticket.story_points_estimated = float(story_points) if story_points is not None else ticket.story_points_estimated
            ticket.time_estimate_hours = time_estimate_seconds / 3600 if time_estimate_seconds else ticket.time_estimate_hours
            ticket.time_actual_hours = time_spent_seconds / 3600 if time_spent_seconds else ticket.time_actual_hours
            ticket.jira_updated_at = _parse_datetime(fields.get("updated"))

        if ticket_status == TicketStatus.DONE and not ticket.completed_at:
            ticket.completed_at = _parse_datetime(fields.get("resolutiondate")) or datetime.utcnow()


@celery_app.task
def sync_all_teams():
    """Full sync for every org that has an active Jira connection and a configured board."""
    from src.models.jira_connection import JiraConnection
    from src.models.team import Team

    db = _get_sync_session()
    try:
        connections = db.execute(
            select(JiraConnection).where(JiraConnection.is_active == True)
        ).scalars().all()

        for conn in connections:
            teams = db.execute(
                select(Team).where(
                    Team.organization_id == conn.organization_id,
                    Team.jira_board_id.isnot(None),
                )
            ).scalars().all()
            for team in teams:
                sync_jira_team.delay(str(team.id))
    finally:
        db.close()


@celery_app.task
def incremental_sync_all_teams():
    """Incremental sync of the active sprint for every configured team."""
    from src.models.jira_connection import JiraConnection
    from src.models.team import Team
    from src.models.sprint import Sprint, SprintStatus

    db = _get_sync_session()
    try:
        connections = db.execute(
            select(JiraConnection).where(JiraConnection.is_active == True)
        ).scalars().all()

        for conn in connections:
            teams = db.execute(
                select(Team).where(
                    Team.organization_id == conn.organization_id,
                    Team.jira_board_id.isnot(None),
                )
            ).scalars().all()
            for team in teams:
                active_sprint = db.execute(
                    select(Sprint).where(
                        Sprint.team_id == team.id,
                        Sprint.status == SprintStatus.ACTIVE,
                    )
                ).scalar_one_or_none()
                if active_sprint and active_sprint.jira_sprint_id:
                    sync_jira_sprint.delay(str(team.id), active_sprint.jira_sprint_id)
    finally:
        db.close()
