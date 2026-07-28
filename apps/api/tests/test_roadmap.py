"""
Router tests for /api/projects/{project_id}/roadmap. Follows the
test_onboarding_v2.py skeleton (tmp_db fixture, _patch_clerk, ASGI test
client, manual seeding).

Happy-path generate/regenerate tests exercise the real service with only the
Groq client faked (same approach as test_roadmap_generator.py) so the
router->service wiring and response shapes are actually verified. Error-
mapping tests (402/502) mock the service functions directly since that's
testing the router's own exception translation, not the service's.

Every route is now project-scoped (see docs/plans/2026-07-20-project-hub.md);
in addition to the org-scoping tests, this file covers the cross-tenant-
within-org gap the multi-project change introduces: a task/milestone from
project A must 404 through project B's URL even when both projects belong to
the same org.
"""

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient, ASGITransport

from src.main import app
from src.database import get_db
from src.models.organization import Organization
from src.models.team import Team
from src.models.onboarding_session import OnboardingSession
from src.models.project import Project
from src.models.milestone import Milestone
from src.models.task import Task

ORG = "org_roadmap_test"
USER = "user_roadmap"
AUTH = {"Authorization": "Bearer tok"}

_BRIEF = {"projectName": "Brief Name", "problemStatement": "Founders lack plans"}

_ROADMAP_PAYLOAD = {
    "projectName": "Trail Buddy",
    "summary": "Two weeks to a hikeable MVP.",
    "milestones": [
        {
            "title": "Foundations",
            "tasks": [{"title": "Init repo", "dayOffset": 0}],
        },
    ],
}


def _patch_clerk(user_id=USER, org_id=ORG):
    payload = {"sub": user_id, "org_id": org_id}
    state = type("S", (), {"is_signed_in": True, "payload": payload})()
    return patch("src.auth._clerk.authenticate_request_async", new=AsyncMock(return_value=state))


def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _seed_org(clerk_org_id=ORG, with_team=True):
    org_id, team_id = uuid.uuid4(), uuid.uuid4()
    async for db in app.dependency_overrides[get_db]():
        db.add(Organization(
            id=org_id, clerk_org_id=clerk_org_id, name="Test Org", slug=clerk_org_id,
            use_managed_key=False,
        ))
        if with_team:
            db.add(Team(id=team_id, organization_id=org_id, name="Default"))
        await db.commit()
        return org_id, (team_id if with_team else None)


async def _seed_session(org_id, brief=_BRIEF, purpose="hobby"):
    session_id = uuid.uuid4()
    async for db in app.dependency_overrides[get_db]():
        db.add(OnboardingSession(
            id=session_id, organization_id=org_id, status="completed",
            project_brief=brief, project_purpose=purpose,
        ))
        await db.commit()
        return session_id


async def _seed_project_no_milestones(team_id, session_id, name="Seeded"):
    """A Project row with no milestones yet — the "repair" case for POST .../generate."""
    project_id = uuid.uuid4()
    async for db in app.dependency_overrides[get_db]():
        db.add(Project(
            id=project_id, team_id=team_id, onboarding_session_id=session_id,
            name=name, purpose="hobby",
        ))
        await db.commit()
        return project_id


async def _seed_roadmap(team_id, session_id):
    """Persist a project with 2 milestones (M0: 2 tasks, M1: 1 task) directly."""
    project_id = uuid.uuid4()
    m0, m1 = uuid.uuid4(), uuid.uuid4()
    async for db in app.dependency_overrides[get_db]():
        db.add(Project(
            id=project_id, team_id=team_id, onboarding_session_id=session_id,
            name="Seeded", purpose="hobby",
        ))
        await db.flush()
        db.add_all([
            Milestone(id=m0, project_id=project_id, title="M0", sort_order=0),
            Milestone(id=m1, project_id=project_id, title="M1", sort_order=1),
        ])
        await db.flush()
        db.add_all([
            Task(milestone_id=m0, title="T0", sort_order=0),
            Task(milestone_id=m0, title="T1", sort_order=1),
            Task(milestone_id=m1, title="T2", sort_order=0),
        ])
        await db.commit()
        return project_id, (m0, m1)


def _url(project_id, suffix=""):
    return f"/api/projects/{project_id}/roadmap{suffix}"


# ─── Groq fakes (mirrors test_roadmap_generator.py) ─────────────────────────────
class _FakeToolCall:
    def __init__(self, name, payload):
        self.function = SimpleNamespace(name=name, arguments=json.dumps(payload))


def _fake_groq(payload=None, tool_name="build_roadmap", tool_calls=None):
    if tool_calls is None:
        tool_calls = [_FakeToolCall(tool_name, payload)] if payload is not None else []
    message = SimpleNamespace(tool_calls=tool_calls or None)
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=message)],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=200),
    )
    fake_completions = SimpleNamespace(create=AsyncMock(return_value=response))
    return SimpleNamespace(chat=SimpleNamespace(completions=fake_completions))


def _patch_groq(fake):
    return patch("src.services.roadmap_generator.AsyncOpenAI", return_value=fake)


def _patch_api_key():
    return patch(
        "src.services.idea_interview.resolve_api_key", new=AsyncMock(return_value="sk-test")
    )


# ─── GET /api/projects/{project_id}/roadmap ─────────────────────────────────────
@pytest.mark.asyncio
async def test_get_roadmap_org_not_provisioned(tmp_db):
    with _patch_clerk():
        async with _client() as client:
            resp = await client.get(_url(uuid.uuid4()), headers=AUTH)
    assert resp.status_code == 409
    assert resp.json()["detail"] == "org_not_provisioned"


@pytest.mark.asyncio
async def test_get_roadmap_project_not_found(tmp_db):
    await _seed_org()
    with _patch_clerk():
        async with _client() as client:
            resp = await client.get(_url(uuid.uuid4()), headers=AUTH)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "project_not_found"


@pytest.mark.asyncio
async def test_get_roadmap_happy_path(tmp_db):
    org_id, team_id = await _seed_org()
    session_id = await _seed_session(org_id)
    project_id, _ = await _seed_roadmap(team_id, session_id)

    with _patch_clerk():
        async with _client() as client:
            resp = await client.get(_url(project_id), headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(project_id)
    assert body["status"] == "active"
    assert [m["title"] for m in body["milestones"]] == ["M0", "M1"]


# ─── POST /api/projects/{project_id}/roadmap/generate (idempotent repair) ───────
@pytest.mark.asyncio
async def test_generate_repair_requires_brief(tmp_db):
    org_id, team_id = await _seed_org()
    session_id = await _seed_session(org_id, brief=None)
    project_id = await _seed_project_no_milestones(team_id, session_id)
    with _patch_clerk():
        async with _client() as client:
            resp = await client.post(_url(project_id, "/generate"), headers=AUTH)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_generate_repair_returns_existing_without_calling_groq(tmp_db):
    org_id, team_id = await _seed_org()
    session_id = await _seed_session(org_id)
    project_id, _ = await _seed_roadmap(team_id, session_id)
    fake = _fake_groq(_ROADMAP_PAYLOAD)

    with _patch_clerk(), _patch_api_key(), _patch_groq(fake):
        async with _client() as client:
            resp = await client.post(_url(project_id, "/generate"), headers=AUTH)
    assert resp.status_code == 200
    assert [m["title"] for m in resp.json()["milestones"]] == ["M0", "M1"]
    fake.chat.completions.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_generate_repair_populates_when_no_milestones(tmp_db):
    org_id, team_id = await _seed_org()
    session_id = await _seed_session(org_id)
    project_id = await _seed_project_no_milestones(team_id, session_id)
    fake = _fake_groq(_ROADMAP_PAYLOAD)

    with _patch_clerk(), _patch_api_key(), _patch_groq(fake):
        async with _client() as client:
            resp = await client.post(_url(project_id, "/generate"), headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    # regenerate_roadmap keeps the existing Project row/id (no duplicate insert).
    assert body["id"] == str(project_id)
    assert [m["title"] for m in body["milestones"]] == ["Foundations"]


@pytest.mark.asyncio
async def test_generate_repair_upstream_error_maps_to_502(tmp_db):
    org_id, team_id = await _seed_org()
    session_id = await _seed_session(org_id)
    project_id = await _seed_project_no_milestones(team_id, session_id)
    fake = _fake_groq(tool_calls=[])

    with _patch_clerk(), _patch_api_key(), _patch_groq(fake):
        async with _client() as client:
            resp = await client.post(_url(project_id, "/generate"), headers=AUTH)
    assert resp.status_code == 502


# ─── POST /api/projects/{project_id}/roadmap/regenerate (full replan) ───────────
@pytest.mark.asyncio
async def test_regenerate_requires_brief(tmp_db):
    org_id, team_id = await _seed_org()
    session_id = await _seed_session(org_id, brief=None)
    project_id, _ = await _seed_roadmap(team_id, session_id)
    with _patch_clerk():
        async with _client() as client:
            resp = await client.post(_url(project_id, "/regenerate"), headers=AUTH)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_regenerate_replaces_existing_roadmap(tmp_db):
    org_id, team_id = await _seed_org()
    session_id = await _seed_session(org_id)
    project_id, _ = await _seed_roadmap(team_id, session_id)

    regen_payload = {
        "projectName": "Trail Buddy 2",
        "milestones": [{"title": "Restart", "tasks": [{"title": "Redo it", "dayOffset": 0}]}],
    }
    fake = _fake_groq(regen_payload)

    with _patch_clerk(), _patch_api_key(), _patch_groq(fake):
        async with _client() as client:
            resp = await client.post(_url(project_id, "/regenerate"), headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Trail Buddy 2"
    assert [m["title"] for m in body["milestones"]] == ["Restart"]


@pytest.mark.asyncio
async def test_regenerate_bad_key_maps_to_402(tmp_db):
    org_id, team_id = await _seed_org()
    session_id = await _seed_session(org_id)
    project_id, _ = await _seed_roadmap(team_id, session_id)

    with _patch_clerk(), _patch_api_key():
        with patch(
            "src.routers.roadmap.roadmap_generator.regenerate_roadmap",
            new=AsyncMock(side_effect=ValueError("Invalid Groq API key.")),
        ):
            async with _client() as client:
                resp = await client.post(_url(project_id, "/regenerate"), headers=AUTH)
    assert resp.status_code == 402


# ─── POST .../milestones/{id}/regenerate ────────────────────────────────────────
@pytest.mark.asyncio
async def test_regenerate_milestone_happy_path(tmp_db):
    org_id, team_id = await _seed_org()
    session_id = await _seed_session(org_id)
    project_id, (m0, m1) = await _seed_roadmap(team_id, session_id)

    payload = {
        "title": "M1 rebuilt",
        "description": "Sharper phase",
        "tasks": [{"title": "New task", "dayOffset": 0}],
    }
    fake = _fake_groq(payload, tool_name="rebuild_milestone")

    with _patch_clerk(), _patch_api_key(), _patch_groq(fake):
        async with _client() as client:
            resp = await client.post(_url(project_id, f"/milestones/{m1}/regenerate"), headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(m1)
    assert body["title"] == "M1 rebuilt"
    assert [t["title"] for t in body["tasks"]] == ["New task"]

    # Sibling untouched.
    with _patch_clerk():
        async with _client() as client:
            roadmap = (await client.get(_url(project_id), headers=AUTH)).json()
    sibling = next(m for m in roadmap["milestones"] if m["id"] == str(m0))
    assert sibling["title"] == "M0"
    assert [t["title"] for t in sibling["tasks"]] == ["T0", "T1"]


@pytest.mark.asyncio
async def test_regenerate_milestone_not_found(tmp_db):
    org_id, team_id = await _seed_org()
    session_id = await _seed_session(org_id)
    project_id, _ = await _seed_roadmap(team_id, session_id)
    with _patch_clerk(), _patch_api_key():
        async with _client() as client:
            resp = await client.post(_url(project_id, f"/milestones/{uuid.uuid4()}/regenerate"), headers=AUTH)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "milestone_not_found"


@pytest.mark.asyncio
async def test_regenerate_milestone_cross_org_404(tmp_db):
    org_a, team_a = await _seed_org(clerk_org_id="org_a")
    session_a = await _seed_session(org_a)
    project_a, (m0, _) = await _seed_roadmap(team_a, session_a)

    org_b, _ = await _seed_org(clerk_org_id="org_b")
    await _seed_session(org_b)

    with _patch_clerk(org_id="org_b"), _patch_api_key():
        async with _client() as client:
            resp = await client.post(_url(project_a, f"/milestones/{m0}/regenerate"), headers=AUTH)
    # project_a doesn't belong to org_b: the project lookup itself 404s first.
    assert resp.status_code == 404
    assert resp.json()["detail"] == "project_not_found"


@pytest.mark.asyncio
async def test_regenerate_milestone_cross_project_within_org_404(tmp_db):
    """A milestone that belongs to a sibling project in the SAME org must still 404 —
    this is the real cross-tenant-within-org gap the multi-project change introduces."""
    org_id, team_id = await _seed_org()
    session_a = await _seed_session(org_id)
    project_a, (m0, _) = await _seed_roadmap(team_id, session_a)

    session_b = await _seed_session(org_id)
    project_b = await _seed_project_no_milestones(team_id, session_b, name="Sibling")

    with _patch_clerk(), _patch_api_key():
        async with _client() as client:
            resp = await client.post(_url(project_b, f"/milestones/{m0}/regenerate"), headers=AUTH)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "milestone_not_found"


@pytest.mark.asyncio
async def test_regenerate_milestone_upstream_error_maps_to_502(tmp_db):
    org_id, team_id = await _seed_org()
    session_id = await _seed_session(org_id)
    project_id, (m0, _) = await _seed_roadmap(team_id, session_id)
    fake = _fake_groq(tool_calls=[])

    with _patch_clerk(), _patch_api_key(), _patch_groq(fake):
        async with _client() as client:
            resp = await client.post(_url(project_id, f"/milestones/{m0}/regenerate"), headers=AUTH)
    assert resp.status_code == 502


# ─── PATCH .../tasks/{id} ────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_patch_task_status_title_description(tmp_db):
    org_id, team_id = await _seed_org()
    session_id = await _seed_session(org_id)
    project_id, _ = await _seed_roadmap(team_id, session_id)

    with _patch_clerk():
        async with _client() as client:
            roadmap = (await client.get(_url(project_id), headers=AUTH)).json()
            task_id = roadmap["milestones"][0]["tasks"][0]["id"]

            resp = await client.patch(
                _url(project_id, f"/tasks/{task_id}"),
                json={"status": "done", "title": "Renamed", "description": "New desc"},
                headers=AUTH,
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "done"
    assert body["title"] == "Renamed"
    assert body["description"] == "New desc"


@pytest.mark.asyncio
async def test_patch_task_cross_org_404(tmp_db):
    org_a, team_a = await _seed_org(clerk_org_id="org_a")
    session_a = await _seed_session(org_a)
    project_a, _ = await _seed_roadmap(team_a, session_a)

    org_b, _ = await _seed_org(clerk_org_id="org_b")

    with _patch_clerk(org_id="org_a"):
        async with _client() as client:
            roadmap = (await client.get(_url(project_a), headers=AUTH)).json()
            task_id = roadmap["milestones"][0]["tasks"][0]["id"]

    with _patch_clerk(org_id="org_b"):
        async with _client() as client:
            resp = await client.patch(
                _url(project_a, f"/tasks/{task_id}"), json={"status": "done"}, headers=AUTH
            )
    # project_a doesn't belong to org_b: the project lookup itself 404s first.
    assert resp.status_code == 404
    assert resp.json()["detail"] == "project_not_found"


@pytest.mark.asyncio
async def test_patch_task_cross_project_within_org_404(tmp_db):
    """A task belonging to a sibling project in the same org must 404 through this
    project's URL — an org-only check would wrongly authorize it."""
    org_id, team_id = await _seed_org()
    session_a = await _seed_session(org_id)
    project_a, _ = await _seed_roadmap(team_id, session_a)

    session_b = await _seed_session(org_id)
    project_b = await _seed_project_no_milestones(team_id, session_b, name="Sibling")

    with _patch_clerk():
        async with _client() as client:
            roadmap = (await client.get(_url(project_a), headers=AUTH)).json()
            task_id = roadmap["milestones"][0]["tasks"][0]["id"]

            resp = await client.patch(
                _url(project_b, f"/tasks/{task_id}"), json={"status": "done"}, headers=AUTH
            )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "task_not_found"


@pytest.mark.asyncio
async def test_patch_task_reorder_shifts_siblings(tmp_db):
    org_id, team_id = await _seed_org()
    session_id = await _seed_session(org_id)
    project_id, _ = await _seed_roadmap(team_id, session_id)

    with _patch_clerk():
        async with _client() as client:
            roadmap = (await client.get(_url(project_id), headers=AUTH)).json()
            tasks = roadmap["milestones"][0]["tasks"]  # T0 (0), T1 (1)
            t0_id = tasks[0]["id"]

            # Move T0 to the end (index 1 of 2).
            resp = await client.patch(
                _url(project_id, f"/tasks/{t0_id}"), json={"sortOrder": 1}, headers=AUTH
            )
            assert resp.status_code == 200
            assert resp.json()["sortOrder"] == 1

            roadmap = (await client.get(_url(project_id), headers=AUTH)).json()
    reordered = roadmap["milestones"][0]["tasks"]
    assert [t["title"] for t in reordered] == ["T1", "T0"]
    assert [t["sortOrder"] for t in reordered] == [0, 1]


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_order", [-1, 2])
async def test_patch_task_reorder_out_of_bounds(tmp_db, bad_order):
    org_id, team_id = await _seed_org()
    session_id = await _seed_session(org_id)
    project_id, _ = await _seed_roadmap(team_id, session_id)

    with _patch_clerk():
        async with _client() as client:
            roadmap = (await client.get(_url(project_id), headers=AUTH)).json()
            task_id = roadmap["milestones"][0]["tasks"][0]["id"]

            resp = await client.patch(
                _url(project_id, f"/tasks/{task_id}"), json={"sortOrder": bad_order}, headers=AUTH
            )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "sort_order_out_of_bounds"


# ─── DELETE .../tasks/{id} ───────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_delete_task(tmp_db):
    org_id, team_id = await _seed_org()
    session_id = await _seed_session(org_id)
    project_id, _ = await _seed_roadmap(team_id, session_id)

    with _patch_clerk():
        async with _client() as client:
            roadmap = (await client.get(_url(project_id), headers=AUTH)).json()
            task_id = roadmap["milestones"][0]["tasks"][0]["id"]

            resp = await client.delete(_url(project_id, f"/tasks/{task_id}"), headers=AUTH)
            assert resp.status_code == 204

            roadmap = (await client.get(_url(project_id), headers=AUTH)).json()
    assert [t["title"] for t in roadmap["milestones"][0]["tasks"]] == ["T1"]


@pytest.mark.asyncio
async def test_delete_task_cross_project_within_org_404(tmp_db):
    org_id, team_id = await _seed_org()
    session_a = await _seed_session(org_id)
    project_a, _ = await _seed_roadmap(team_id, session_a)

    session_b = await _seed_session(org_id)
    project_b = await _seed_project_no_milestones(team_id, session_b, name="Sibling")

    with _patch_clerk():
        async with _client() as client:
            roadmap = (await client.get(_url(project_a), headers=AUTH)).json()
            task_id = roadmap["milestones"][0]["tasks"][0]["id"]

            resp = await client.delete(_url(project_b, f"/tasks/{task_id}"), headers=AUTH)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "task_not_found"


# ─── GET .../members (workload scoped to this project only) ─────────────────────
@pytest.mark.asyncio
async def test_members_scheduled_count_scoped_to_project(tmp_db):
    """A developer's scheduled-task count must only reflect THIS project's tasks,
    not their workload across every project in the org."""
    from src.models.developer import Developer

    org_id, team_id = await _seed_org()
    session_a = await _seed_session(org_id)
    project_a, (m0, _) = await _seed_roadmap(team_id, session_a)

    session_b = await _seed_session(org_id)
    project_b, (m0_b, _) = await _seed_roadmap(team_id, session_b)

    dev_id = uuid.uuid4()
    async for db in app.dependency_overrides[get_db]():
        db.add(Developer(id=dev_id, team_id=team_id, name="Dev", role="developer"))
        await db.flush()
        # Assign + schedule one task in EACH project to the same developer.
        task_a = (await db.execute(
            __import__("sqlalchemy").select(Task).where(Task.milestone_id == m0)
        )).scalars().first()
        task_b = (await db.execute(
            __import__("sqlalchemy").select(Task).where(Task.milestone_id == m0_b)
        )).scalars().first()
        from datetime import date
        task_a.assignee_id = dev_id
        task_a.scheduled_date = date.today()
        task_b.assignee_id = dev_id
        task_b.scheduled_date = date.today()
        await db.commit()

    with _patch_clerk():
        async with _client() as client:
            resp = await client.get(_url(project_a, "/members"), headers=AUTH)
    assert resp.status_code == 200
    member = next(m for m in resp.json()["members"] if m["id"] == str(dev_id))
    assert member["scheduledCount"] == 1
