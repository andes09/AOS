"""
GitHub activity ingestion — links pushes/merged PRs to roadmap tasks and
auto-completes the ones that were referenced by name. Fed by two paths that
share this exact same matching/idempotency logic:

  1. The webhook receiver (routers/github_webhooks.py) — near-real-time,
     calls `process_github_event.delay(...)` per delivery.
  2. The reconciliation sweep (`reconcile_org_github` below), on a Celery
     beat cron — a safety net for missed webhook deliveries, using
     `MAX(occurred_at)` per (org, repo) from `github_activity_events` itself
     as the "since" cursor (falling back to the connection's `created_at`).

Matching happens in two tiers, and the distinction is load-bearing:

  1. **Exact** — a `Task.short_id` token ("AOS-142") in the commit message,
     branch, or PR title/body. Authoritative, and the *only* tier permitted to
     mutate `Task.status` / `completed_at`.
  2. **Heuristic** — token/path overlap via services/github_matching.py, run
     only when tier 1 finds nothing. Recorded as `match_method='heuristic'`
     with a confidence, and consumed as *evidence* by the drift service. It
     never moves a task, because a wrong guess that silently ticks a task off
     a founder's plan is worse than no match at all. Whatever this tier can't
     resolve is left `'unmatched'` for the LLM classifier
     (services/github_classifier.py) to take a second look at.

Idempotency: every insert into `github_activity_events` is guarded by that
table's `UNIQUE (organization_id, repo_full_name, event_type, external_id)`
constraint via `ON CONFLICT DO NOTHING`. Task-status mutation only happens
when the insert actually lands a *new* row — so a duplicate delivery (or the
reconciliation sweep re-seeing something the webhook already recorded) never
double-applies a status flip.

Footgun avoided on purpose: `tasks.status` is a SAEnum column, so a `Task`
loaded from the DB carries `TaskStatus.DONE` (the enum member), not the
string `"done"` — comparing it with `==`/`!=` against a literal string
silently misbehaves once the row has round-tripped. `_status_str` below
normalizes before every comparison (same pattern as
services/roadmap_adjuster.py's private helper of the same name).
"""

import asyncio
import logging
import re
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import AsyncSessionLocal
from src.integrations.github.client import GithubClient, _parse_gh_datetime
from src.models.github_activity_event import GithubActivityEvent, MatchMethod
from src.models.github_connection import GithubConnection
from src.models.milestone import Milestone
from src.models.project import Project
from src.models.task import Task, TaskStatus
from src.models.team import Team
from src.services.github_matching import TaskCandidate as GithubTaskCandidate
from src.services.github_matching import best_match
from src.worker import celery_app

logger = logging.getLogger(__name__)

# Matches short_id-style tokens (e.g. "AOS-142") in commit messages, branch
# names, and PR titles/bodies. Deliberately generic on the prefix — the real
# org-scoping happens in `_find_task`, which only matches a task belonging to
# the org the webhook's installation_id (or the reconciliation sweep's org)
# resolved to, so a lookalike token from an unrelated org's repo can never
# flip someone else's task.
SHORT_ID_RE = re.compile(r"\b([A-Z][A-Z0-9]{0,9}-\d+)\b")

_UNIQUE_INDEX_ELEMENTS = ["organization_id", "repo_full_name", "event_type", "external_id"]

# Upper bound on how many open tasks the heuristic matcher scores one event
# against. A roadmap is capped at 8 milestones x 10 tasks (services/
# roadmap_shapes.py), so this only binds for orgs carrying several projects —
# and past a few hundred candidates the IDF weighting stops discriminating
# anyway, so scoring more would cost time without buying precision.
_MAX_CANDIDATE_TASKS = 250


def _status_str(status) -> str:
    """The status as a plain string — see module docstring's footgun note."""
    return status.value if isinstance(status, TaskStatus) else status


def extract_short_ids(*texts: str | None) -> set[str]:
    ids: set[str] = set()
    for text in texts:
        if text:
            ids.update(SHORT_ID_RE.findall(text))
    return ids


async def _find_task(db: AsyncSession, organization_id, short_id: str) -> Task | None:
    """Task -> Milestone -> Project -> Team -> Organization, scoped to the
    org the event actually belongs to."""
    return await db.scalar(
        select(Task)
        .join(Milestone, Task.milestone_id == Milestone.id)
        .join(Project, Milestone.project_id == Project.id)
        .join(Team, Project.team_id == Team.id)
        .where(Team.organization_id == organization_id, Task.short_id == short_id)
    )


async def _first_matching_task(db: AsyncSession, organization_id, short_ids: set[str]) -> Task | None:
    for short_id in short_ids:
        task = await _find_task(db, organization_id, short_id)
        if task is not None:
            return task
    return None


async def _candidate_tasks(db: AsyncSession, organization_id, repo_full_name: str) -> list[Task]:
    """Open tasks the heuristic matcher may consider, narrowest scope first.

    Prefer tasks belonging to the project actually linked to this repo
    (`Project.github_repo_full_name`) — an org with three projects shouldn't
    have a commit in one repo matched against another project's plan. Only
    when no project claims the repo do we widen to the whole org, which is the
    common case today since repo linkage is set during onboarding and can be
    skipped.

    DONE tasks are excluded: they can still be referenced by an exact
    `short_id` (that path doesn't come through here), but they must not
    compete as fuzzy candidates — finished work attracting new commits is
    exactly the ambiguity the margin rule exists to reject.
    """
    base = (
        select(Task)
        .join(Milestone, Task.milestone_id == Milestone.id)
        .join(Project, Milestone.project_id == Project.id)
        .join(Team, Project.team_id == Team.id)
        .where(Team.organization_id == organization_id, Task.status != TaskStatus.DONE.value)
        .order_by(Task.created_at)
        .limit(_MAX_CANDIDATE_TASKS)
    )

    scoped = list(await db.scalars(base.where(Project.github_repo_full_name == repo_full_name)))
    if scoped:
        return scoped
    return list(await db.scalars(base))


def _to_candidates(tasks: list[Task]) -> list[GithubTaskCandidate]:
    return [
        GithubTaskCandidate(
            task_id=str(t.id),
            short_id=t.short_id,
            title=t.title,
            description=t.description,
            github_path=t.github_path,
        )
        for t in tasks
    ]


async def _resolve_match(
    db: AsyncSession,
    organization_id,
    repo_full_name: str,
    *,
    short_id_texts: tuple[str | None, ...],
    heuristic_message: str | None,
    branch: str | None,
    changed_paths: list[str],
    candidates_cache: list[Task] | None = None,
) -> tuple[Task | None, str, float | None, list[Task] | None]:
    """Resolve one GitHub event to a task, exact path first.

    Returns `(task, match_method, confidence, candidates_cache)`. The cache is
    threaded back out so a push carrying twenty commits loads the org's open
    tasks once rather than twenty times.

    The returned `match_method` is what decides whether the caller may touch
    `Task.status` — only `SHORT_ID` may. See the module docstring.
    """
    short_ids = extract_short_ids(*short_id_texts)
    if short_ids:
        task = await _first_matching_task(db, organization_id, short_ids)
        if task is not None:
            return task, MatchMethod.SHORT_ID, None, candidates_cache

    if candidates_cache is None:
        candidates_cache = await _candidate_tasks(db, organization_id, repo_full_name)
    if not candidates_cache:
        return None, MatchMethod.UNMATCHED, None, candidates_cache

    hit = best_match(
        message=heuristic_message,
        branch=branch,
        changed_paths=changed_paths,
        tasks=_to_candidates(candidates_cache),
    )
    if hit is None:
        return None, MatchMethod.UNMATCHED, None, candidates_cache

    matched = next((t for t in candidates_cache if str(t.id) == hit.task_id), None)
    if matched is None:  # pragma: no cover — cache and candidates are built together
        return None, MatchMethod.UNMATCHED, None, candidates_cache
    return matched, MatchMethod.HEURISTIC, round(hit.score, 4), candidates_cache


def _changed_paths(commit: dict) -> list[str]:
    """Files a push-payload commit touched.

    Only the webhook carries these — the reconciliation sweep's
    `list_commits` returns commit metadata without a file list (GitHub only
    includes `files` on the single-commit endpoint), so matching degrades to
    text-only on that path. Acceptable: the sweep is a safety net for missed
    deliveries, and anything it under-matches gets a second look from the LLM
    classifier.
    """
    paths: list[str] = []
    for key in ("added", "modified", "removed"):
        paths.extend(commit.get(key) or [])
    return paths


async def _record_event(
    db: AsyncSession,
    *,
    organization_id,
    repo_full_name: str,
    event_type: str,
    external_id: str,
    branch: str | None,
    title_or_message: str | None,
    author_login: str | None,
    url: str | None,
    matched_task_id,
    occurred_at: datetime,
    match_method: str = MatchMethod.UNMATCHED,
    match_confidence: float | None = None,
) -> bool:
    """Idempotent insert on the (org, repo, event_type, external_id) unique
    constraint. Returns True iff a new row was actually inserted — a
    duplicate delivery returns False and the caller must not re-apply the
    status mutation.

    The dialect-specific `insert(...).on_conflict_do_nothing(...)` construct
    is picked at call time (postgresql in production, sqlite in tests — see
    tests/conftest.py's in-memory tmp_db fixture) since both dialects support
    the same `ON CONFLICT` API shape in SQLAlchemy.
    """
    insert = postgresql.insert if db.bind.dialect.name == "postgresql" else sqlite.insert
    stmt = (
        insert(GithubActivityEvent)
        .values(
            organization_id=organization_id,
            repo_full_name=repo_full_name,
            event_type=event_type,
            external_id=external_id,
            branch=branch,
            title_or_message=title_or_message,
            author_login=author_login,
            url=url,
            matched_task_id=matched_task_id,
            match_method=match_method,
            match_confidence=match_confidence,
            occurred_at=occurred_at,
        )
        .on_conflict_do_nothing(index_elements=_UNIQUE_INDEX_ELEMENTS)
        .returning(GithubActivityEvent.id)
    )
    result = await db.execute(stmt)
    return result.first() is not None


# ─── matching rules ──────────────────────────────────────────────────────────
async def _process_push_event(db: AsyncSession, organization_id, repo_full_name: str, payload: dict) -> None:
    ref = payload.get("ref") or ""
    branch = ref[len("refs/heads/"):] if ref.startswith("refs/heads/") else None
    sender = (payload.get("sender") or {}).get("login")

    candidates: list[Task] | None = None
    for commit in payload.get("commits") or []:
        sha = commit.get("id") or commit.get("sha")
        if not sha:
            continue
        message = commit.get("message") or ""
        occurred_at = _parse_gh_datetime(commit.get("timestamp")) or datetime.utcnow()
        changed = _changed_paths(commit)
        task, method, confidence, candidates = await _resolve_match(
            db,
            organization_id,
            repo_full_name,
            short_id_texts=(message, branch),
            heuristic_message=message,
            branch=branch,
            changed_paths=changed,
            candidates_cache=candidates,
        )

        inserted = await _record_event(
            db,
            organization_id=organization_id,
            repo_full_name=repo_full_name,
            event_type="push",
            external_id=sha,
            branch=branch,
            title_or_message=message,
            author_login=(commit.get("author") or {}).get("username") or sender,
            url=commit.get("url"),
            matched_task_id=task.id if task else None,
            match_method=method,
            match_confidence=confidence,
            occurred_at=occurred_at,
        )
        # A push marks the task IN_PROGRESS (work is happening) — but never
        # downgrades a task that's already DONE, and never re-applies on a
        # delivery we've already recorded.
        #
        # Gated on an exact short_id: a heuristic match is recorded as evidence
        # for drift reporting, but a guess must never move a founder's task.
        if (
            inserted
            and task is not None
            and method == MatchMethod.SHORT_ID
            and _status_str(task.status) != TaskStatus.DONE.value
        ):
            task.status = TaskStatus.IN_PROGRESS.value


async def _process_pull_request_event(db: AsyncSession, organization_id, repo_full_name: str, payload: dict) -> None:
    pr = payload.get("pull_request") or {}
    action = payload.get("action") or ""
    number = pr.get("number")
    if number is None:
        return

    merged = bool(pr.get("merged"))
    is_merge = action == "closed" and merged
    event_type = "pr_merged" if is_merge else ("pr_opened" if action == "opened" else "pr_closed")
    external_id = f"pr-{number}-{action}"

    title = pr.get("title") or ""
    body = pr.get("body") or ""
    branch = (pr.get("head") or {}).get("ref")
    occurred_at = (
        _parse_gh_datetime(pr.get("merged_at"))
        or _parse_gh_datetime(pr.get("updated_at"))
        or _parse_gh_datetime(pr.get("created_at"))
        or datetime.utcnow()
    )
    # No file list on a pull_request payload, so the heuristic works from the
    # PR title, body and branch name alone.
    task, method, confidence, _ = await _resolve_match(
        db,
        organization_id,
        repo_full_name,
        short_id_texts=(title, body, branch),
        heuristic_message=f"{title}\n{body}",
        branch=branch,
        changed_paths=[],
    )

    inserted = await _record_event(
        db,
        organization_id=organization_id,
        repo_full_name=repo_full_name,
        event_type=event_type,
        external_id=external_id,
        branch=branch,
        title_or_message=title,
        author_login=(pr.get("user") or {}).get("login"),
        url=pr.get("html_url"),
        matched_task_id=task.id if task else None,
        match_method=method,
        match_confidence=confidence,
        occurred_at=occurred_at,
    )
    # Only a MERGE completes a task — opening a PR alone does not — and only
    # when the PR named the task outright. Completing a task is the single most
    # destructive thing this pipeline can do to a plan, so it stays behind the
    # exact-identifier path; a heuristic match is evidence, not authority.
    if inserted and task is not None and is_merge and method == MatchMethod.SHORT_ID:
        task.status = TaskStatus.DONE.value
        task.completed_at = occurred_at


async def process_github_event_async(organization_id, event_type: str, payload: dict, db: AsyncSession) -> None:
    repo_full_name = (payload.get("repository") or {}).get("full_name")
    if not repo_full_name:
        return
    if event_type == "push":
        await _process_push_event(db, organization_id, repo_full_name, payload)
    elif event_type == "pull_request":
        await _process_pull_request_event(db, organization_id, repo_full_name, payload)
    await db.commit()


@celery_app.task(bind=True, max_retries=3)
def process_github_event(self, organization_id: str, event_type: str, payload: dict):
    """Celery entry point — thin sync wrapper that bridges into the async DB
    session for a single webhook delivery. Tests call
    `process_github_event_async` directly against the tmp_db-overridden
    session rather than going through Celery, same as this repo's other
    background-task tests exercise their core logic directly."""
    async def _run() -> None:
        async with AsyncSessionLocal() as db:
            try:
                await process_github_event_async(organization_id, event_type, payload, db)
            except Exception:
                await db.rollback()
                raise

    try:
        asyncio.run(_run())
    except Exception as exc:  # pragma: no cover — exercised via retry semantics, not unit tests
        logger.exception("process_github_event failed for org %s", organization_id)
        raise self.retry(exc=exc, countdown=min(60 * (2 ** self.request.retries), 900))


# ─── reconciliation sweep (safety net for missed webhook deliveries) ─────────
async def _cursor_for_repo(db: AsyncSession, organization_id, repo_full_name: str, fallback: datetime) -> datetime:
    """`MAX(occurred_at)` for this (org, repo) from github_activity_events
    itself — no separate sync-state table to keep consistent. Falls back to
    the connection's `created_at` when this repo has no recorded events yet."""
    cursor = await db.scalar(
        select(func.max(GithubActivityEvent.occurred_at)).where(
            GithubActivityEvent.organization_id == organization_id,
            GithubActivityEvent.repo_full_name == repo_full_name,
        )
    )
    return cursor or fallback


async def _reconcile_repo_commits(db: AsyncSession, organization_id, repo_full_name: str, client: GithubClient, since: datetime) -> None:
    owner, _, name = repo_full_name.partition("/")
    commits = await client.list_commits(owner, name, since=since)
    candidates: list[Task] | None = None
    for commit in commits:
        sha = commit.get("sha")
        if not sha:
            continue
        commit_info = commit.get("commit") or {}
        message = commit_info.get("message") or ""
        occurred_at = _parse_gh_datetime((commit_info.get("author") or {}).get("date")) or since
        # No branch and no file list from the commits-list endpoint — the
        # heuristic runs on the message alone here. See `_changed_paths`.
        task, method, confidence, candidates = await _resolve_match(
            db,
            organization_id,
            repo_full_name,
            short_id_texts=(message,),
            heuristic_message=message,
            branch=None,
            changed_paths=[],
            candidates_cache=candidates,
        )

        inserted = await _record_event(
            db,
            organization_id=organization_id,
            repo_full_name=repo_full_name,
            event_type="push",
            external_id=sha,
            branch=None,  # not reliably available from the commits list endpoint
            title_or_message=message,
            author_login=(commit.get("author") or {}).get("login"),
            url=commit.get("html_url"),
            matched_task_id=task.id if task else None,
            match_method=method,
            match_confidence=confidence,
            occurred_at=occurred_at,
        )
        if (
            inserted
            and task is not None
            and method == MatchMethod.SHORT_ID
            and _status_str(task.status) != TaskStatus.DONE.value
        ):
            task.status = TaskStatus.IN_PROGRESS.value


async def _reconcile_repo_pull_requests(db: AsyncSession, organization_id, repo_full_name: str, client: GithubClient, since: datetime) -> None:
    owner, _, name = repo_full_name.partition("/")
    prs = await client.list_pull_requests(owner, name, state="all", since=since)
    candidates: list[Task] | None = None
    for pr in prs:
        number = pr.get("number")
        if number is None:
            continue
        merged = pr.get("merged_at") is not None
        state = pr.get("state")
        action = "closed" if state == "closed" else "opened"
        is_merge = action == "closed" and merged
        event_type = "pr_merged" if is_merge else ("pr_opened" if action == "opened" else "pr_closed")
        external_id = f"pr-{number}-{action}"

        title = pr.get("title") or ""
        body = pr.get("body") or ""
        branch = (pr.get("head") or {}).get("ref")
        occurred_at = (
            _parse_gh_datetime(pr.get("merged_at"))
            or _parse_gh_datetime(pr.get("updated_at"))
            or since
        )
        task, method, confidence, candidates = await _resolve_match(
            db,
            organization_id,
            repo_full_name,
            short_id_texts=(title, body, branch),
            heuristic_message=f"{title}\n{body}",
            branch=branch,
            changed_paths=[],
            candidates_cache=candidates,
        )

        inserted = await _record_event(
            db,
            organization_id=organization_id,
            repo_full_name=repo_full_name,
            event_type=event_type,
            external_id=external_id,
            branch=branch,
            title_or_message=title,
            author_login=(pr.get("user") or {}).get("login"),
            url=pr.get("html_url"),
            matched_task_id=task.id if task else None,
            match_method=method,
            match_confidence=confidence,
            occurred_at=occurred_at,
        )
        if inserted and task is not None and is_merge and method == MatchMethod.SHORT_ID:
            task.status = TaskStatus.DONE.value
            task.completed_at = occurred_at


async def reconcile_org_github_async(organization_id, db: AsyncSession) -> None:
    """Safety net for missed webhook deliveries: for the org's active GitHub
    connection, walk every visible repo and diff recent commits/PRs against
    `github_activity_events`, backfilling anything a webhook missed. Cheap
    and idempotent — repos with nothing new since their cursor do near-zero
    work (one commits call, one pulls call, both filtered to `since`)."""
    from src.integrations.github.router import _get_valid_access_token  # local import: avoid a router<->events cycle

    connection = await db.scalar(
        select(GithubConnection).where(
            GithubConnection.organization_id == organization_id,
            GithubConnection.is_active == True,  # noqa: E712
        )
    )
    if connection is None:
        return

    access_token = await _get_valid_access_token(connection, db)
    client = GithubClient(access_token)
    repos = await client.list_repos()

    for repo in repos:
        repo_full_name = repo["full_name"]
        since = await _cursor_for_repo(db, organization_id, repo_full_name, connection.created_at)
        await _reconcile_repo_commits(db, organization_id, repo_full_name, client, since)
        await _reconcile_repo_pull_requests(db, organization_id, repo_full_name, client, since)

    await db.commit()

    # Third matching tier, chained here rather than given its own beat entry:
    # it should only ever run on a settled set of events, and the sweep is what
    # settles them. Its failures are swallowed internally so a classifier
    # problem can never fail the reconciliation that produced the rows.
    from src.services.github_classifier import classify_unmatched_events_async  # local: avoid an import cycle via worker

    await classify_unmatched_events_async(organization_id, db)


@celery_app.task(bind=True, max_retries=3)
def reconcile_org_github(self, organization_id: str):
    async def _run() -> None:
        async with AsyncSessionLocal() as db:
            try:
                await reconcile_org_github_async(organization_id, db)
            except Exception:
                await db.rollback()
                raise

    try:
        asyncio.run(_run())
    except Exception as exc:  # pragma: no cover — exercised via retry semantics, not unit tests
        logger.exception("reconcile_org_github failed for org %s", organization_id)
        raise self.retry(exc=exc, countdown=min(60 * (2 ** self.request.retries), 900))


@celery_app.task
def github_reconciliation_sweep():
    """Beat entry: fan out `reconcile_org_github` to every active GitHub
    connection's org. Runs a plain sync query over `database_url_sync`
    rather than the async engine, since Celery beat tasks execute outside
    any event loop."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from src.config import settings

    engine = create_engine(settings.database_url_sync)
    with Session(engine) as session:
        rows = session.execute(
            select(GithubConnection.organization_id).where(GithubConnection.is_active == True)  # noqa: E712
        ).all()
    org_ids = {str(r[0]) for r in rows}
    for org_id in org_ids:
        reconcile_org_github.delay(org_id)
