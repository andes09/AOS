"""
Router tests for /api/roadmap. Follows the test_onboarding_v2.py skeleton
(tmp_db fixture, _patch_clerk, ASGI test client, manual seeding).

Happy-path generate/regenerate tests exercise the real service with only the
Groq client faked (same approach as test_roadmap_generator.py) so the
router->service wiring and response shapes are actually verified. Error-
mapping tests (402/502) mock the service functions directly since that's
testing the router's own exception translation, not the service's.
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


# ─── GET /api/roadmap ───────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_get_roadmap_org_not_provisioned(tmp_db):
    with _patch_clerk():
        async with _client() as client:
            resp = await client.get("/api/roadmap", headers=AUTH)
    assert resp.status_code == 409
    assert resp.json()["detail"] == "org_not_provisioned"


@pytest.mark.asyncio
async def test_get_roadmap_no_session_returns_null(tmp_db):
    await _seed_org()
    with _patch_clerk():
        async with _client() as client:
            resp = await client.get("/api/roadmap", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json() is None


# ─── POST /api/roadmap/generate ─────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_generate_requires_brief(tmp_db):
    org_id, _ = await _seed_org()
    await _seed_session(org_id, brief=None)
    with _patch_clerk():
        async with _client() as client:
            resp = await client.post("/api/roadmap/generate", headers=AUTH)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_generate_no_team_for_org(tmp_db):
    org_id, _ = await _seed_org(with_team=False)
    await _seed_session(org_id)
    with _patch_clerk(), _patch_api_key():
        async with _client() as client:
            resp = await client.post("/api/roadmap/generate", headers=AUTH)
    assert resp.status_code == 409
    assert resp.json()["detail"] == "no_team_for_org"


@pytest.mark.asyncio
async def test_generate_happy_path_then_idempotent(tmp_db):
    org_id, team_id = await _seed_org()
    await _seed_session(org_id)
    fake = _fake_groq(_ROADMAP_PAYLOAD)

    with _patch_clerk(), _patch_api_key(), _patch_groq(fake):
        async with _client() as client:
            resp = await client.post("/api/roadmap/generate", headers=AUTH)
            assert resp.status_code == 200
            body = resp.json()
            assert body["name"] == "Trail Buddy"
            assert [m["title"] for m in body["milestones"]] == ["Foundations"]

            # Idempotent: second call returns the same roadmap without calling Groq again.
            resp2 = await client.post("/api/roadmap/generate", headers=AUTH)
    assert resp2.json() == body
    assert fake.chat.completions.create.await_count == 1


@pytest.mark.asyncio
async def test_generate_upstream_error_maps_to_502(tmp_db):
    org_id, team_id = await _seed_org()
    await _seed_session(org_id)
    fake = _fake_groq(tool_calls=[])

    with _patch_clerk(), _patch_api_key(), _patch_groq(fake):
        async with _client() as client:
            resp = await client.post("/api/roadmap/generate", headers=AUTH)
    assert resp.status_code == 502


# ─── POST /api/roadmap/regenerate ───────────────────────────────────────────────
@pytest.mark.asyncio
async def test_regenerate_requires_brief(tmp_db):
    org_id, _ = await _seed_org()
    await _seed_session(org_id, brief=None)
    with _patch_clerk():
        async with _client() as client:
            resp = await client.post("/api/roadmap/regenerate", headers=AUTH)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_regenerate_falls_back_to_generate_when_no_project(tmp_db):
    org_id, team_id = await _seed_org()
    await _seed_session(org_id)
    fake = _fake_groq(_ROADMAP_PAYLOAD)

    with _patch_clerk(), _patch_api_key(), _patch_groq(fake):
        async with _client() as client:
            resp = await client.post("/api/roadmap/regenerate", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["name"] == "Trail Buddy"


@pytest.mark.asyncio
async def test_regenerate_replaces_existing_roadmap(tmp_db):
    org_id, team_id = await _seed_org()
    session_id = await _seed_session(org_id)
    await _seed_roadmap(team_id, session_id)

    regen_payload = {
        "projectName": "Trail Buddy 2",
        "milestones": [{"title": "Restart", "tasks": [{"title": "Redo it", "dayOffset": 0}]}],
    }
    fake = _fake_groq(regen_payload)

    with _patch_clerk(), _patch_api_key(), _patch_groq(fake):
        async with _client() as client:
            resp = await client.post("/api/roadmap/regenerate", headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Trail Buddy 2"
    assert [m["title"] for m in body["milestones"]] == ["Restart"]


@pytest.mark.asyncio
async def test_regenerate_bad_key_maps_to_402(tmp_db):
    org_id, team_id = await _seed_org()
    await _seed_session(org_id)

    with _patch_clerk(), _patch_api_key():
        with patch(
            "src.routers.roadmap.roadmap_generator.regenerate_roadmap",
            new=AsyncMock(side_effect=ValueError("Invalid Groq API key.")),
        ):
            async with _client() as client:
                resp = await client.post("/api/roadmap/regenerate", headers=AUTH)
    assert resp.status_code == 402


# ─── POST /api/roadmap/milestones/{id}/regenerate ───────────────────────────────
@pytest.mark.asyncio
async def test_regenerate_milestone_happy_path(tmp_db):
    org_id, team_id = await _seed_org()
    session_id = await _seed_session(org_id)
    _, (m0, m1) = await _seed_roadmap(team_id, session_id)

    payload = {
        "title": "M1 rebuilt",
        "description": "Sharper phase",
        "tasks": [{"title": "New task", "dayOffset": 0}],
    }
    fake = _fake_groq(payload, tool_name="rebuild_milestone")

    with _patch_clerk(), _patch_api_key(), _patch_groq(fake):
        async with _client() as client:
            resp = await client.post(f"/api/roadmap/milestones/{m1}/regenerate", headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(m1)
    assert body["title"] == "M1 rebuilt"
    assert [t["title"] for t in body["tasks"]] == ["New task"]

    # Sibling untouched.
    with _patch_clerk():
        async with _client() as client:
            roadmap = (await client.get("/api/roadmap", headers=AUTH)).json()
    sibling = next(m for m in roadmap["milestones"] if m["id"] == str(m0))
    assert sibling["title"] == "M0"
    assert [t["title"] for t in sibling["tasks"]] == ["T0", "T1"]


@pytest.mark.asyncio
async def test_regenerate_milestone_not_found(tmp_db):
    org_id, _ = await _seed_org()
    await _seed_session(org_id)
    with _patch_clerk(), _patch_api_key():
        async with _client() as client:
            resp = await client.post(f"/api/roadmap/milestones/{uuid.uuid4()}/regenerate", headers=AUTH)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "milestone_not_found"


@pytest.mark.asyncio
async def test_regenerate_milestone_cross_org_404(tmp_db):
    org_a, team_a = await _seed_org(clerk_org_id="org_a")
    session_a = await _seed_session(org_a)
    _, (m0, _) = await _seed_roadmap(team_a, session_a)

    org_b, _ = await _seed_org(clerk_org_id="org_b")
    await _seed_session(org_b)

    with _patch_clerk(org_id="org_b"), _patch_api_key():
        async with _client() as client:
            resp = await client.post(f"/api/roadmap/milestones/{m0}/regenerate", headers=AUTH)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "milestone_not_found"


@pytest.mark.asyncio
async def test_regenerate_milestone_upstream_error_maps_to_502(tmp_db):
    org_id, team_id = await _seed_org()
    session_id = await _seed_session(org_id)
    _, (m0, _) = await _seed_roadmap(team_id, session_id)
    fake = _fake_groq(tool_calls=[])

    with _patch_clerk(), _patch_api_key(), _patch_groq(fake):
        async with _client() as client:
            resp = await client.post(f"/api/roadmap/milestones/{m0}/regenerate", headers=AUTH)
    assert resp.status_code == 502


# ─── PATCH /api/roadmap/tasks/{id} ──────────────────────────────────────────────
@pytest.mark.asyncio
async def test_patch_task_status_title_description(tmp_db):
    org_id, team_id = await _seed_org()
    session_id = await _seed_session(org_id)
    _, (m0, _) = await _seed_roadmap(team_id, session_id)

    with _patch_clerk():
        async with _client() as client:
            roadmap = (await client.get("/api/roadmap", headers=AUTH)).json()
            task_id = roadmap["milestones"][0]["tasks"][0]["id"]

            resp = await client.patch(
                f"/api/roadmap/tasks/{task_id}",
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
    _, (m0, _) = await _seed_roadmap(team_a, session_a)

    org_b, _ = await _seed_org(clerk_org_id="org_b")

    with _patch_clerk(org_id="org_a"):
        async with _client() as client:
            roadmap = (await client.get("/api/roadmap", headers=AUTH)).json()
            task_id = roadmap["milestones"][0]["tasks"][0]["id"]

    with _patch_clerk(org_id="org_b"):
        async with _client() as client:
            resp = await client.patch(
                f"/api/roadmap/tasks/{task_id}", json={"status": "done"}, headers=AUTH
            )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "task_not_found"


@pytest.mark.asyncio
async def test_patch_task_reorder_shifts_siblings(tmp_db):
    org_id, team_id = await _seed_org()
    session_id = await _seed_session(org_id)
    _, (m0, _) = await _seed_roadmap(team_id, session_id)

    with _patch_clerk():
        async with _client() as client:
            roadmap = (await client.get("/api/roadmap", headers=AUTH)).json()
            tasks = roadmap["milestones"][0]["tasks"]  # T0 (0), T1 (1)
            t0_id = tasks[0]["id"]

            # Move T0 to the end (index 1 of 2).
            resp = await client.patch(
                f"/api/roadmap/tasks/{t0_id}", json={"sortOrder": 1}, headers=AUTH
            )
            assert resp.status_code == 200
            assert resp.json()["sortOrder"] == 1

            roadmap = (await client.get("/api/roadmap", headers=AUTH)).json()
    reordered = roadmap["milestones"][0]["tasks"]
    assert [t["title"] for t in reordered] == ["T1", "T0"]
    assert [t["sortOrder"] for t in reordered] == [0, 1]


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_order", [-1, 2])
async def test_patch_task_reorder_out_of_bounds(tmp_db, bad_order):
    org_id, team_id = await _seed_org()
    session_id = await _seed_session(org_id)
    _, (m0, _) = await _seed_roadmap(team_id, session_id)

    with _patch_clerk():
        async with _client() as client:
            roadmap = (await client.get("/api/roadmap", headers=AUTH)).json()
            task_id = roadmap["milestones"][0]["tasks"][0]["id"]

            resp = await client.patch(
                f"/api/roadmap/tasks/{task_id}", json={"sortOrder": bad_order}, headers=AUTH
            )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "sort_order_out_of_bounds"


# ─── DELETE /api/roadmap/tasks/{id} ─────────────────────────────────────────────
@pytest.mark.asyncio
async def test_delete_task(tmp_db):
    org_id, team_id = await _seed_org()
    session_id = await _seed_session(org_id)
    _, (m0, _) = await _seed_roadmap(team_id, session_id)

    with _patch_clerk():
        async with _client() as client:
            roadmap = (await client.get("/api/roadmap", headers=AUTH)).json()
            task_id = roadmap["milestones"][0]["tasks"][0]["id"]

            resp = await client.delete(f"/api/roadmap/tasks/{task_id}", headers=AUTH)
            assert resp.status_code == 204

            roadmap = (await client.get("/api/roadmap", headers=AUTH)).json()
    assert [t["title"] for t in roadmap["milestones"][0]["tasks"]] == ["T1"]


@pytest.mark.asyncio
async def test_delete_task_cross_org_404(tmp_db):
    org_a, team_a = await _seed_org(clerk_org_id="org_a")
    session_a = await _seed_session(org_a)
    _, (m0, _) = await _seed_roadmap(team_a, session_a)
    await _seed_org(clerk_org_id="org_b")

    with _patch_clerk(org_id="org_a"):
        async with _client() as client:
            roadmap = (await client.get("/api/roadmap", headers=AUTH)).json()
            task_id = roadmap["milestones"][0]["tasks"][0]["id"]

    with _patch_clerk(org_id="org_b"):
        async with _client() as client:
            resp = await client.delete(f"/api/roadmap/tasks/{task_id}", headers=AUTH)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "task_not_found"
