"""
Celery tasks for syncing Jira data into the AgileOS database.

sync_jira_team  — full sync: boards → sprints → issues → users
sync_jira_sprint — incremental sync for a single sprint
"""

import uuid
import logging
from datetime import datetime, date

from sqlalchemy import select, create_engine, update as sa_update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
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


def _get_fresh_client(connection, db: Session) -> JiraClient:
    """Return a JiraClient, refreshing the access token if needed.

    Token updates are committed immediately so a subsequent rollback on the
    sync transaction cannot discard the new (rotated) refresh token.
    Atlassian uses one-time refresh token rotation: if the new refresh_token
    is rolled back, the next retry sends the already-consumed token → 403.
    """
    import asyncio

    access_token = decrypt(connection.encrypted_access_token)

    if connection.token_expires_at and connection.token_expires_at <= datetime.utcnow():
        refresh_tok = decrypt(connection.encrypted_refresh_token)
        tokens = asyncio.get_event_loop().run_until_complete(
            refresh_access_token(refresh_tok)
        )
        access_token = tokens["access_token"]
        from src.services.encryption import encrypt
        from datetime import timedelta
        connection.encrypted_access_token = encrypt(access_token)
        if "refresh_token" in tokens:
            connection.encrypted_refresh_token = encrypt(tokens["refresh_token"])
        if "expires_in" in tokens:
            connection.token_expires_at = datetime.utcnow() + timedelta(seconds=tokens["expires_in"])
        # Commit immediately — token rotation must survive a sync failure/rollback
        db.commit()

    return JiraClient(cloud_id=connection.jira_cloud_id, access_token=access_token)


class JiraReauthRequired(Exception):
    """Raised when Jira refresh fails with a non-recoverable auth error
    (400/401/403). The connection has been deactivated; the user must
    reconnect via OAuth before any further Jira call will succeed.
    """


async def _get_fresh_client_async(connection, db: AsyncSession) -> JiraClient:
    """Async sibling of :func:`_get_fresh_client` for use from FastAPI routes.

    Same rotation semantics as the sync variant: token updates are committed
    immediately so that a later rollback on the request transaction cannot
    discard the rotated refresh token.

    Raises :class:`JiraReauthRequired` if Atlassian rejects the refresh token
    (typically because a prior request consumed it but didn't persist the
    rotated value). The connection row is deactivated before re-raising.
    """
    import httpx

    access_token = decrypt(connection.encrypted_access_token)

    if connection.token_expires_at and connection.token_expires_at <= datetime.utcnow():
        from datetime import timedelta
        from src.services.encryption import encrypt

        refresh_tok = decrypt(connection.encrypted_refresh_token)
        try:
            tokens = await refresh_access_token(refresh_tok)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (400, 401, 403):
                logger.warning(
                    "Jira refresh rejected (%s) — deactivating connection %s",
                    exc.response.status_code, connection.id,
                )
                connection.is_active = False
                await db.commit()
                raise JiraReauthRequired(
                    f"Jira refresh token rejected ({exc.response.status_code}). "
                    "Please reconnect Jira in Settings."
                ) from exc
            raise
        access_token = tokens["access_token"]
        connection.encrypted_access_token = encrypt(access_token)
        if "refresh_token" in tokens:
            connection.encrypted_refresh_token = encrypt(tokens["refresh_token"])
        if "expires_in" in tokens:
            connection.token_expires_at = datetime.utcnow() + timedelta(seconds=tokens["expires_in"])
        await db.commit()

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

        client = _get_fresh_client(connection, db)
        loop = asyncio.get_event_loop()

        # Fetch users + sprint list concurrently
        users, sprints = loop.run_until_complete(asyncio.gather(
            client.get_users(),
            client.get_sprints(),
        ))
        _upsert_team_members(db, team, users)

        # Preload member map once — eliminates N×M per-ticket DB lookups
        member_map = _build_member_map(db, team)

        # Fetch all sprint issues + backlog in one concurrent gather
        _ISSUE_FIELDS = [
            "summary", "status", "assignee", "issuetype", "labels",
            "components", "timespent", "timeoriginalestimate",
            "created", "updated", "resolutiondate",
            "customfield_10016", "customfield_10028",
        ]

        async def _fetch_all_issues():
            coros = [client.get_sprint_issues(str(s["id"])) for s in sprints]
            if team.jira_project_key:
                coros.append(client.search_issues(
                    jql=(
                        f"project = {team.jira_project_key} "
                        f"AND sprint is EMPTY ORDER BY created ASC"
                    ),
                    fields=_ISSUE_FIELDS,
                ))
            return await asyncio.gather(*coros)

        results = loop.run_until_complete(_fetch_all_issues())

        if team.jira_project_key:
            all_sprint_issues = results[:-1]
            backlog_issues = results[-1]
        else:
            all_sprint_issues = results
            backlog_issues = []

        closed_sprint_ids: list[uuid.UUID] = []
        for jira_sprint, issues in zip(sprints, all_sprint_issues):
            sprint_obj, just_closed = _upsert_sprint(db, team, jira_sprint)
            if sprint_obj:
                _upsert_issues(db, team, sprint_obj, issues, member_map)
                if just_closed:
                    closed_sprint_ids.append(sprint_obj.id)

        # Sync backlog issues (not in any sprint). SprintBrain's candidate
        # query in _get_candidate_tickets returns Tickets with sprint_id IS
        # NULL or in completed sprints, so without this step a fresh team
        # board (one that's never had a completed sprint) yields an empty
        # candidate pool and /api/sprint-brain/plan 422s.
        if backlog_issues:
            _upsert_backlog_issues(db, team, backlog_issues, member_map)

        db.commit()

        # Bookkeeping write done via explicit UPDATE: _get_fresh_client may
        # have committed a token refresh mid-task, expiring `connection`, and
        # setting an attribute on an expired instance has been unreliable here
        # (the UPDATE sometimes didn't reach the DB, leaving /status stale).
        db.execute(
            sa_update(JiraConnection)
            .where(JiraConnection.id == connection.id)
            .values(last_synced_at=datetime.utcnow())
        )
        db.commit()
        logger.info("Full Jira sync complete for team %s", team_id)

        # Warm ticket complexity cache in the background so the next plan
        # generation skips the Claude complexity call entirely.
        try:
            prewarm_ticket_complexity.delay(team_id)
        except Exception:
            pass  # never block sync completion

        # Initiative A: fire sprint-close hooks for any sprint that transitioned
        # to COMPLETED in this sync. Hooks are best-effort — failures are logged
        # but never block sync completion.
        if closed_sprint_ids:
            _fire_sprint_close_hooks(team_id, closed_sprint_ids)

    except Exception as exc:
        db.rollback()
        logger.exception("Jira sync failed for team %s: %s", team_id, exc)
        raise self.retry(exc=exc)
    finally:
        db.close()


def _fire_sprint_close_hooks(team_id: str, closed_sprint_ids: list[uuid.UUID]) -> None:
    """Best-effort Initiative A hooks. Opens its own AsyncSessionLocal per hook.
    All exceptions logged and swallowed so sync results stay durable.
    """
    from src.database import AsyncSessionLocal
    from src.services.identifier_refresh_service import refresh_after_sprint_close
    from src.services.plan_quality import persist_plan_quality

    loop = asyncio.get_event_loop()

    async def _run_refresh():
        async with AsyncSessionLocal() as adb:
            await refresh_after_sprint_close(uuid.UUID(team_id), None, adb)

    async def _run_plan_quality(sprint_id: uuid.UUID):
        async with AsyncSessionLocal() as adb:
            await persist_plan_quality(str(sprint_id), adb)

    try:
        loop.run_until_complete(_run_refresh())
    except Exception:
        logger.exception("sprint_close_hook: identifier refresh failed for team %s", team_id)

    for sid in closed_sprint_ids:
        try:
            loop.run_until_complete(_run_plan_quality(sid))
        except Exception:
            logger.exception("sprint_close_hook: persist_plan_quality failed for sprint %s", sid)


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

        client = _get_fresh_client(connection, db)

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

def _build_member_map(db: Session, team) -> dict[str, uuid.UUID]:
    """Return {jira_account_id: TeamMember.id} for the team.

    Called once per sync after _upsert_team_members so every sprint's issue
    upsert can resolve assignees with a dict lookup instead of a per-ticket
    SELECT.
    """
    from src.models.developer import TeamMember
    rows = db.execute(select(TeamMember).where(TeamMember.team_id == team.id)).scalars().all()
    return {m.jira_account_id: m.id for m in rows if m.jira_account_id}


def _upsert_team_members(db: Session, team, jira_users: list[dict]):
    from src.models.developer import TeamMember

    for user in jira_users:
        account_id = user.get("accountId")
        if not account_id:
            continue
        display_name = user.get("displayName", account_id)
        email = user.get("emailAddress")
        # Use ON CONFLICT DO UPDATE so concurrent Celery workers syncing the
        # same team don't race on the unique (team_id, jira_account_id) index.
        stmt = pg_insert(TeamMember).values(
            id=uuid.uuid4(),
            team_id=team.id,
            jira_account_id=account_id,
            display_name=display_name,
            email=email,
        ).on_conflict_do_update(
            index_elements=["team_id", "jira_account_id"],
            set_={
                "display_name": display_name,
                "email": email,
            },
        )
        db.execute(stmt)


def _upsert_sprint(db: Session, team, jira_sprint: dict):
    """Upsert a Jira sprint row.

    Returns (sprint, transitioned_to_completed) — the bool is True only when this
    call observed the sprint transitioning INTO COMPLETED (newly created and
    already closed, or updated from a non-COMPLETED state). Used by sync_jira_team
    to fire Initiative A's sprint-close hooks (identifier refresh + plan_quality).
    """
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

    old_status = sprint.status if sprint is not None else None

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
    transitioned = status == SprintStatus.COMPLETED and old_status != SprintStatus.COMPLETED
    return sprint, transitioned


def _upsert_issues(db: Session, team, sprint, jira_issues: list[dict], member_map: dict | None = None):
    from src.models.ticket import Ticket, TicketStatus
    from src.models.developer import TeamMember

    for issue in jira_issues:
        jira_issue_id = issue["id"]
        fields = issue.get("fields", {})

        # Resolve assignee — O(1) dict lookup when member_map is provided
        assignee_id = None
        assignee_data = fields.get("assignee")
        if assignee_data:
            account_id = assignee_data.get("accountId")
            if member_map is not None:
                assignee_id = member_map.get(account_id)
            else:
                member = db.execute(
                    select(TeamMember).where(
                        TeamMember.team_id == team.id,
                        TeamMember.jira_account_id == account_id,
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


def _upsert_backlog_issues(db: Session, team, jira_issues: list[dict], member_map: dict | None = None):
    """Upsert backlog tickets (sprint_id = None) into Ticket.

    Same field extraction as _upsert_issues but for issues that are NOT in any
    sprint. These rows become candidates for /api/sprint-brain/plan via
    _get_candidate_tickets, which looks for sprint_id IS NULL OR sprint in
    completed sprints. A ticket that previously lived in a sprint and is now
    in backlog (spillover) gets its sprint_id nulled out by this path.
    """
    from src.models.ticket import Ticket, TicketStatus
    from src.models.developer import TeamMember

    for issue in jira_issues:
        jira_issue_id = issue["id"]
        fields = issue.get("fields", {})

        assignee_id = None
        assignee_data = fields.get("assignee")
        if assignee_data:
            account_id = assignee_data.get("accountId")
            if member_map is not None:
                assignee_id = member_map.get(account_id)
            else:
                member = db.execute(
                    select(TeamMember).where(
                        TeamMember.team_id == team.id,
                        TeamMember.jira_account_id == account_id,
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
                sprint_id=None,
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
            ticket.sprint_id = None
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


@celery_app.task
def prewarm_ticket_complexity(team_id: str) -> None:
    """Warm the ticket complexity cache after a sync so plan generation skips Claude's complexity call."""
    import asyncio
    from src.database import AsyncSessionLocal
    from src.services.sprint_brain import _prewarm_complexity

    async def _run():
        async with AsyncSessionLocal() as db:
            await _prewarm_complexity(team_id, db)

    asyncio.get_event_loop().run_until_complete(_run())
