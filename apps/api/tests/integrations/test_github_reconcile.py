"""
Tests for the reconciliation sweep's cursor logic (integrations/github/events.py's
`_cursor_for_repo` and `reconcile_org_github_async`) — the safety net for
missed webhook deliveries. Per the corrected GitHub-App-native design (see
docs/plans/2026-07-20-github-task-autocomplete.md's Implementation Notes),
the cursor is `MAX(occurred_at)` per (organization_id, repo_full_name) from
github_activity_events itself — no separate sync-state table.

GithubClient calls are mocked; only the cursor/matching/idempotency logic is
under test here (list_commits/list_pull_requests themselves are thin httpx
wrappers, not worth re-testing against a fake GitHub API).
"""

import uuid
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.database import Base
import src.models  # noqa: F401 — registers all models
from src.models.organization import Organization
from src.models.github_activity_event import GithubActivityEvent
from src.models.github_connection import GithubConnection
from src.integrations.github.events import (
    _cursor_for_repo,
    reconcile_org_github_async,
)

REPO = "octocat/hello"


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_cursor_falls_back_to_connection_created_at_when_no_events(db_session):
    org_id = uuid.uuid4()
    fallback = datetime(2026, 1, 1)
    cursor = await _cursor_for_repo(db_session, org_id, REPO, fallback)
    assert cursor == fallback


@pytest.mark.asyncio
async def test_cursor_uses_max_occurred_at_across_events(db_session):
    org_id = uuid.uuid4()
    fallback = datetime(2026, 1, 1)
    older = datetime(2026, 6, 1, 10, 0, 0)
    newer = datetime(2026, 7, 1, 10, 0, 0)

    db_session.add_all([
        GithubActivityEvent(
            id=uuid.uuid4(), organization_id=org_id, repo_full_name=REPO,
            event_type="push", external_id="sha-old", occurred_at=older,
        ),
        GithubActivityEvent(
            id=uuid.uuid4(), organization_id=org_id, repo_full_name=REPO,
            event_type="push", external_id="sha-new", occurred_at=newer,
        ),
    ])
    await db_session.commit()

    cursor = await _cursor_for_repo(db_session, org_id, REPO, fallback)
    assert cursor == newer


@pytest.mark.asyncio
async def test_cursor_is_scoped_per_repo(db_session):
    """A cursor for repo A must not be pulled forward by events recorded
    against a different repo in the same org."""
    org_id = uuid.uuid4()
    fallback = datetime(2026, 1, 1)
    other_repo_event_at = datetime(2026, 7, 1)

    db_session.add(GithubActivityEvent(
        id=uuid.uuid4(), organization_id=org_id, repo_full_name="octocat/other-repo",
        event_type="push", external_id="sha-1", occurred_at=other_repo_event_at,
    ))
    await db_session.commit()

    cursor = await _cursor_for_repo(db_session, org_id, REPO, fallback)
    assert cursor == fallback


@pytest.mark.asyncio
async def test_reconcile_backfills_missed_commit_and_advances_cursor(db_session):
    """End-to-end reconcile: a connection exists, list_repos/list_commits are
    faked, and a commit referencing a task's short_id (never seen by any
    webhook) gets recorded and the task flipped IN_PROGRESS — with no
    duplicate row on a second sweep."""
    from src.models.team import Team
    from src.models.onboarding_session import OnboardingSession
    from src.models.project import Project
    from src.models.milestone import Milestone
    from src.models.task import Task, TaskStatus

    org_id, team_id, session_id, project_id, milestone_id, task_id = (
        uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    )
    conn_created_at = datetime(2026, 1, 1)

    db_session.add(Organization(
        id=org_id, clerk_org_id="org_reconcile", name="Org", slug="org-reconcile",
        use_managed_key=False,
    ))
    db_session.add(Team(id=team_id, organization_id=org_id, name="Default"))
    db_session.add(OnboardingSession(id=session_id, organization_id=org_id, status="completed"))
    db_session.add(Project(
        id=project_id, team_id=team_id, onboarding_session_id=session_id, name="P", purpose="hobby",
    ))
    await db_session.flush()
    db_session.add(Milestone(id=milestone_id, project_id=project_id, title="M0", sort_order=0))
    await db_session.flush()
    db_session.add(Task(
        id=task_id, milestone_id=milestone_id, short_id="AOS-9",
        title="Task", status=TaskStatus.TODO.value, sort_order=0,
    ))
    db_session.add(GithubConnection(
        id=uuid.uuid4(), organization_id=org_id, installation_id="42",
        github_user_id="1", github_login="octocat", encrypted_access_token="enc",
        is_active=True, created_at=conn_created_at,
    ))
    await db_session.commit()

    fake_commit = {
        "sha": "deadbeef",
        "commit": {"message": "Ship it (AOS-9)", "author": {"date": "2026-07-15T00:00:00Z"}},
        "author": {"login": "octocat"},
        "html_url": "https://github.com/octocat/hello/commit/deadbeef",
    }

    with (
        patch(
            "src.integrations.github.router._get_valid_access_token",
            new=AsyncMock(return_value="tok"),
        ),
        patch(
            "src.integrations.github.events.GithubClient.list_repos",
            new=AsyncMock(return_value=[{"full_name": REPO}]),
        ),
        patch(
            "src.integrations.github.events.GithubClient.list_commits",
            new=AsyncMock(return_value=[fake_commit]),
        ),
        patch(
            "src.integrations.github.events.GithubClient.list_pull_requests",
            new=AsyncMock(return_value=[]),
        ),
    ):
        await reconcile_org_github_async(org_id, db_session)
        # A second sweep must be idempotent (same commit, same cursor logic).
        await reconcile_org_github_async(org_id, db_session)

    events = (await db_session.execute(select(GithubActivityEvent))).scalars().all()
    assert len(events) == 1
    assert events[0].external_id == "deadbeef"

    task = await db_session.get(Task, task_id)
    status = task.status.value if isinstance(task.status, TaskStatus) else task.status
    assert status == TaskStatus.IN_PROGRESS.value
