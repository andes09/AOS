"""
Celery tasks for syncing Jira data into the AgileOS database.

sync_jira_team  — full sync: boards → sprints → issues → users
sync_jira_sprint — incremental sync for a single sprint
"""

import asyncio
import time
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


def _get_or_create_event_loop() -> asyncio.AbstractEventLoop:
    """Return a usable event loop for sync contexts (Celery workers, thread-pool threads).

    Python 3.12 raised the bar: get_event_loop() raises RuntimeError in non-main
    threads when no loop has been set. Celery workers and FastAPI BackgroundTask
    threads both fall into that category, so we create and register a fresh loop
    when needed.
    """
    try:
        loop = asyncio.get_event_loop()
        if not loop.is_closed():
            return loop
    except RuntimeError:
        pass
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop

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

    access_token = decrypt(connection.encrypted_access_token)

    if connection.token_expires_at and connection.token_expires_at <= datetime.utcnow():
        refresh_tok = decrypt(connection.encrypted_refresh_token)
        tokens = _get_or_create_event_loop().run_until_complete(
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
        logger.warning("jira date parse failed raw=%r", iso_str)
        return None


def _parse_datetime(iso_str: str | None) -> datetime | None:
    if not iso_str:
        return None
    try:
        return datetime.fromisoformat(iso_str.rstrip("Z"))
    except (ValueError, AttributeError):
        logger.warning("jira datetime parse failed raw=%r", iso_str)
        return None


def _write_sync_status(db: Session, team_id: str, **kwargs) -> None:
    """Best-effort upsert of SyncStatus — never raises."""
    try:
        from src.models.sync_status import SyncStatus
        team_uuid = uuid.UUID(team_id)
        existing = db.get(SyncStatus, team_uuid)
        if existing:
            for k, v in kwargs.items():
                setattr(existing, k, v)
        else:
            db.add(SyncStatus(team_id=team_uuid, **kwargs))
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def sync_jira_team(self, team_id: str):
    """Full sync of all sprints and issues for a team from Jira."""
    from src.models.team import Team
    from src.models.jira_connection import JiraConnection

    t0 = time.monotonic()
    logger.info("[sync] team=%s starting full sync", team_id)
    db = _get_sync_session()
    _write_sync_status(db, team_id, state="running", started_at=datetime.utcnow())
    _n_members = 0
    _n_tickets = 0
    try:
        team = db.get(Team, uuid.UUID(team_id))
        if not team:
            logger.warning("Team %s not found", team_id)
            return

        if not team.jira_board_id:
            _write_sync_status(
                db, team_id, state="failed", finished_at=datetime.utcnow(),
                error_code="no_board_id",
                error_message=(
                    "No Jira board is configured for this team. "
                    "Reconnect Jira in Settings and pick a board."
                ),
            )
            logger.warning("[sync] team=%s aborted: jira_board_id is None", team_id)
            return

        # Pre-2026-06-17 onboarding could persist synthetic "project-<id>" values
        # in jira_board_id when the Agile API came back empty. Those aren't valid
        # board IDs — /board/project-<id>/sprint comes back 401 from Atlassian's
        # gateway, which looks like an auth failure but is really bad data. Fail
        # fast with a clear message instead of retrying.
        if team.jira_board_id.startswith("project-"):
            _write_sync_status(
                db, team_id, state="failed", finished_at=datetime.utcnow(),
                error_code="invalid_board_id",
                error_message=(
                    "This team's saved board is a Jira project, not a real board "
                    "(legacy onboarding). Reconnect Jira in Settings and pick a board."
                ),
            )
            logger.warning(
                "[sync] team=%s aborted: legacy project-* board_id %r",
                team_id, team.jira_board_id,
            )
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
        loop = _get_or_create_event_loop()

        # Fetch users + sprint list concurrently
        logger.info("[sync] team=%s fetching users + sprint list...", team_id)
        t_fetch = time.monotonic()
        users, sprints = loop.run_until_complete(asyncio.gather(
            client.get_users(),
            client.get_board_sprints(team.jira_board_id),
        ))
        logger.info(
            "[sync] team=%s found %d sprints, %d users (%.1fs)",
            team_id, len(sprints), len(users), time.monotonic() - t_fetch,
        )
        _upsert_team_members(db, team, users)
        _n_members = len(users)

        # Preload member map once — eliminates N×M per-ticket DB lookups
        member_map = _build_member_map(db, team)

        # Fetch all sprint issues + backlog in one concurrent gather
        _ISSUE_FIELDS = [
            "summary", "status", "assignee", "issuetype", "labels",
            "components", "timespent", "timeoriginalestimate",
            "created", "updated", "resolutiondate",
            "customfield_10016", "customfield_10028",
        ]

        logger.info(
            "[sync] team=%s fetching issues for %d sprints + backlog in parallel...",
            team_id, len(sprints),
        )
        t_fetch = time.monotonic()

        async def _fetch_all_issues():
            coros = [client.get_sprint_issues(str(s["id"])) for s in sprints]
            coros.append(client.get_board_backlog(team.jira_board_id, _ISSUE_FIELDS))
            return await asyncio.gather(*coros)

        results = loop.run_until_complete(_fetch_all_issues())
        all_sprint_issues = results[:-1]
        backlog_issues = results[-1]

        total_sprint_issues = sum(len(r) for r in all_sprint_issues)
        _n_tickets = total_sprint_issues + len(backlog_issues)
        logger.info(
            "[sync] team=%s fetch done in %.1fs — %d sprint issues, %d backlog",
            team_id, time.monotonic() - t_fetch, total_sprint_issues, len(backlog_issues),
        )

        n_sprints = len(sprints)
        closed_sprint_ids: list[uuid.UUID] = []
        t_upsert = time.monotonic()

        for i, (jira_sprint, issues) in enumerate(zip(sprints, all_sprint_issues), 1):
            t_sprint = time.monotonic()
            sprint_obj, just_closed = _upsert_sprint(db, team, jira_sprint)
            if sprint_obj:
                _upsert_issues(db, team, sprint_obj, issues, member_map)
                if just_closed:
                    closed_sprint_ids.append(sprint_obj.id)

            elapsed_sprint = time.monotonic() - t_sprint
            elapsed_upsert = time.monotonic() - t_upsert
            eta_s = (elapsed_upsert / i) * (n_sprints - i)
            eta_str = f" | ETA ~{eta_s:.0f}s" if i < n_sprints else ""
            logger.info(
                "[sync] [%d/%d] %-35s %3d tickets  %.2fs%s",
                i, n_sprints,
                jira_sprint.get("name", f"Sprint {jira_sprint['id']}")[:35],
                len(issues),
                elapsed_sprint,
                eta_str,
            )

        # Sync backlog issues (not in any sprint). SprintBrain's candidate
        # query in _get_candidate_tickets returns Tickets with sprint_id IS
        # NULL or in completed sprints, so without this step a fresh team
        # board (one that's never had a completed sprint) yields an empty
        # candidate pool and /api/sprint-brain/plan 422s.
        if backlog_issues:
            logger.info("[sync] team=%s upserting %d backlog tickets...", team_id, len(backlog_issues))
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
        logger.info("[sync] team=%s complete in %.1fs", team_id, time.monotonic() - t0)
        _write_sync_status(db, team_id, state="complete", finished_at=datetime.utcnow(),
                           tickets_synced=_n_tickets, members_synced=_n_members)

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
        _write_sync_status(db, team_id, state="failed", finished_at=datetime.utcnow(),
                           error_code=type(exc).__name__[:50], error_message=str(exc)[:500])
        logger.exception("Jira sync failed for team %s: %s", team_id, exc)
        raise self.retry(exc=exc)
    finally:
        db.close()


def _fire_sprint_close_hooks(team_id: str, closed_sprint_ids: list[uuid.UUID]) -> None:
    """Best-effort Initiative A hooks. Builds a per-call async engine so the
    asyncpg connection binds to the loop we run the hooks on, not to whatever
    loop happened to import ``src.database`` at app startup. Critical when this
    runs from a FastAPI BackgroundTasks thread (the in-process onboarding sync
    path): reusing ``database.AsyncSessionLocal`` there would hand back a
    connection bound to uvicorn's main loop and hang.

    All exceptions logged and swallowed so sync results stay durable.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from src.services.identifier_refresh_service import refresh_after_sprint_close
    from src.services.plan_quality import persist_plan_quality

    loop = _get_or_create_event_loop()
    hook_engine = create_async_engine(settings.database_url)
    HookSession = async_sessionmaker(hook_engine, expire_on_commit=False)

    async def _run_refresh():
        async with HookSession() as adb:
            await refresh_after_sprint_close(uuid.UUID(team_id), None, adb)

    async def _run_plan_quality(sprint_id: uuid.UUID):
        async with HookSession() as adb:
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

    try:
        loop.run_until_complete(hook_engine.dispose())
    except Exception:
        pass


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def sync_jira_sprint(self, team_id: str, jira_sprint_id: str):
    """Incremental sync for a single sprint's issues from Jira."""
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

        issues = _get_or_create_event_loop().run_until_complete(
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
    """Return {jira_account_id: Developer.id} for the team.

    Called once per sync after _upsert_team_members so every sprint's issue
    upsert can resolve assignees with a dict lookup instead of a per-ticket
    SELECT.
    """
    from src.models.developer import Developer
    rows = db.execute(select(Developer).where(Developer.team_id == team.id)).scalars().all()
    return {d.jira_account_id: d.id for d in rows if d.jira_account_id}


def _upsert_team_members(db: Session, team, jira_users: list[dict]):
    from src.models.developer import Developer

    for user in jira_users:
        account_id = user.get("accountId")
        if not account_id:
            continue
        display_name = user.get("displayName", account_id)
        email = user.get("emailAddress")
        # ON CONFLICT on the partial unique index (team_id, jira_account_id)
        # WHERE jira_account_id IS NOT NULL — safe for concurrent Celery workers.
        stmt = pg_insert(Developer).values(
            id=uuid.uuid4(),
            team_id=team.id,
            jira_account_id=account_id,
            name=display_name,
            email=email,
            is_active=True,
            app_role="developer",
        ).on_conflict_do_update(
            index_elements=["team_id", "jira_account_id"],
            index_where=Developer.jira_account_id.isnot(None),
            set_={
                "name": display_name,
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
    from src.models.developer import Developer

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
                dev = db.execute(
                    select(Developer).where(
                        Developer.team_id == team.id,
                        Developer.jira_account_id == account_id,
                    )
                ).scalar_one_or_none()
                if dev:
                    assignee_id = dev.id

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
    from src.models.developer import Developer

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
                dev = db.execute(
                    select(Developer).where(
                        Developer.team_id == team.id,
                        Developer.jira_account_id == account_id,
                    )
                ).scalar_one_or_none()
                if dev:
                    assignee_id = dev.id

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
    from src.database import AsyncSessionLocal
    from src.services.sprint_brain import _prewarm_complexity

    async def _run():
        async with AsyncSessionLocal() as db:
            await _prewarm_complexity(team_id, db)

    _get_or_create_event_loop().run_until_complete(_run())
