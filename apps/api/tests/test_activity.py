"""
Router tests for the anti-dormancy MVP, Milestone 1
(docs/plans/2026-07-20-anti-dormancy-mvp.md).

Covers the two behaviors that make the feature actually work:
  - GET /api/activity/summary: reads the *previous* last_active_at before
    overwriting it, so "days away" / "completed since last visit" reflect the
    real gap; is_returning gates on the threshold; next_up is capped.
  - PATCH .../tasks/{id} → done: stamps completed_at (the manual-flip gap this
    milestone fixes) and touches the *assignee's* clock, not just the caller's.

Follows test_roadmap.py's skeleton (tmp_db, _patch_clerk, ASGI client, manual
seeding).
"""

import uuid
from datetime import datetime, timedelta

import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch

from src.main import app
from src.database import get_db
from src.models.organization import Organization
from src.models.team import Team
from src.models.developer import Developer
from src.models.onboarding_session import OnboardingSession
from src.models.project import Project
from src.models.milestone import Milestone
from src.models.task import Task

ORG = "org_activity_test"
USER = "user_activity"
AUTH = {"Authorization": "Bearer tok"}


def _patch_clerk(user_id=USER, org_id=ORG):
    payload = {"sub": user_id, "org_id": org_id}
    state = type("S", (), {"is_signed_in": True, "payload": payload})()
    return patch("src.auth._clerk.authenticate_request_async", new=AsyncMock(return_value=state))


def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _seed(
    *,
    last_active_delta=timedelta(days=5),
    caller_has_clerk=True,
):
    """Org + team + caller developer + one active project with a small roadmap.

    Returns (project_id, milestone_id, caller_dev_id).
    """
    org_id, team_id, session_id, project_id, milestone_id, caller_dev_id = (
        uuid.uuid4() for _ in range(6)
    )
    async for db in app.dependency_overrides[get_db]():
        db.add(Organization(
            id=org_id, clerk_org_id=ORG, name="Test Org", slug=ORG, use_managed_key=False,
        ))
        db.add(Team(id=team_id, organization_id=org_id, name="Default"))
        db.add(Developer(
            id=caller_dev_id, team_id=team_id,
            clerk_user_id=USER if caller_has_clerk else None,
            name="Caller", email="caller@example.com",
            last_active_at=(datetime.utcnow() - last_active_delta) if last_active_delta else None,
        ))
        db.add(OnboardingSession(
            id=session_id, organization_id=org_id, status="completed",
            project_brief={"projectName": "X"}, project_purpose="hobby",
        ))
        db.add(Project(
            id=project_id, team_id=team_id, onboarding_session_id=session_id,
            name="Seeded", purpose="hobby", status="active",
        ))
        db.add(Milestone(id=milestone_id, project_id=project_id, title="M0", sort_order=0))
        await db.commit()
        return project_id, milestone_id, caller_dev_id


async def _add_task(milestone_id, **kw):
    task_id = uuid.uuid4()
    async for db in app.dependency_overrides[get_db]():
        db.add(Task(id=task_id, milestone_id=milestone_id, sort_order=kw.pop("sort_order", 0), **kw))
        await db.commit()
        return task_id


async def _get_dev(dev_id):
    async for db in app.dependency_overrides[get_db]():
        return await db.get(Developer, dev_id)


# ─── GET /api/activity/summary ──────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_summary_returning_user_counts_and_next_up(tmp_db):
    project_id, m_id, caller_id = await _seed(last_active_delta=timedelta(days=5))
    # Two todo (one scheduled overdue, one unscheduled), one done since visit.
    await _add_task(m_id, title="Overdue todo", status="todo", sort_order=0,
                    scheduled_date=(datetime.utcnow() - timedelta(days=1)).date())
    await _add_task(m_id, title="Later todo", status="todo", sort_order=1)
    await _add_task(m_id, title="Freshly done", status="done", sort_order=2,
                    completed_at=datetime.utcnow() - timedelta(days=1))

    with _patch_clerk():
        async with _client() as client:
            r = await client.get("/api/activity/summary", headers=AUTH)

    assert r.status_code == 200
    body = r.json()
    assert body["isReturning"] is True
    assert body["daysSinceLastActive"] == 5
    assert body["tasksRemaining"] == 2
    assert body["tasksCompletedSinceLastVisit"] == 1
    assert body["overdueCount"] == 1
    titles = [t["title"] for t in body["nextUp"]]
    assert titles == ["Overdue todo", "Later todo"]  # scheduled first, capped


@pytest.mark.asyncio
async def test_summary_touch_overwrites_so_second_call_not_returning(tmp_db):
    project_id, m_id, caller_id = await _seed(last_active_delta=timedelta(days=5))
    await _add_task(m_id, title="Todo", status="todo")

    with _patch_clerk():
        async with _client() as client:
            first = await client.get("/api/activity/summary", headers=AUTH)
            second = await client.get("/api/activity/summary", headers=AUTH)

    assert first.json()["isReturning"] is True
    # First call overwrote last_active_at to now → the second sees ~0 days away.
    assert second.json()["isReturning"] is False
    assert second.json()["daysSinceLastActive"] == 0


@pytest.mark.asyncio
async def test_summary_recently_active_not_returning(tmp_db):
    project_id, m_id, caller_id = await _seed(last_active_delta=timedelta(hours=3))
    await _add_task(m_id, title="Todo", status="todo")

    with _patch_clerk():
        async with _client() as client:
            r = await client.get("/api/activity/summary", headers=AUTH)

    assert r.json()["isReturning"] is False
    assert r.json()["daysSinceLastActive"] == 0


@pytest.mark.asyncio
async def test_summary_first_visit_ever_not_returning(tmp_db):
    # last_active_at NULL → no previous → not a "return".
    project_id, m_id, caller_id = await _seed(last_active_delta=None)
    await _add_task(m_id, title="Todo", status="todo")

    with _patch_clerk():
        async with _client() as client:
            r = await client.get("/api/activity/summary", headers=AUTH)

    body = r.json()
    assert body["isReturning"] is False
    assert body["daysSinceLastActive"] is None
    assert body["tasksCompletedSinceLastVisit"] == 0


# ─── PATCH .../tasks/{id} → done ────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_complete_stamps_completed_at_and_touches_assignee(tmp_db):
    project_id, m_id, caller_id = await _seed(last_active_delta=timedelta(days=5))
    # A different assignee (real account) — their clock must move, not the caller's only.
    assignee_id = uuid.uuid4()
    async for db in app.dependency_overrides[get_db]():
        caller = await db.get(Developer, caller_id)
        db.add(Developer(
            id=assignee_id, team_id=caller.team_id, clerk_user_id="user_assignee",
            name="Assignee", email="a@example.com",
            last_active_at=datetime.utcnow() - timedelta(days=10),
        ))
        await db.commit()
    task_id = await _add_task(m_id, title="Do it", status="todo", assignee_id=assignee_id)

    with _patch_clerk():
        async with _client() as client:
            r = await client.patch(
                f"/api/projects/{project_id}/roadmap/tasks/{task_id}",
                headers=AUTH, json={"status": "done"},
            )
    assert r.status_code == 200
    assert r.json()["completedAt"] is not None

    assignee = await _get_dev(assignee_id)
    # Was 10 days dormant; completion just reset their clock to ~now.
    assert (datetime.utcnow() - assignee.last_active_at) < timedelta(minutes=5)


@pytest.mark.asyncio
async def test_reopen_clears_completed_at(tmp_db):
    project_id, m_id, caller_id = await _seed(last_active_delta=timedelta(days=1))
    task_id = await _add_task(m_id, title="Do it", status="done",
                              completed_at=datetime.utcnow() - timedelta(days=2))

    with _patch_clerk():
        async with _client() as client:
            r = await client.patch(
                f"/api/projects/{project_id}/roadmap/tasks/{task_id}",
                headers=AUTH, json={"status": "todo"},
            )
    assert r.status_code == 200
    assert r.json()["completedAt"] is None
