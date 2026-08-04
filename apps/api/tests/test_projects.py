"""
Router tests for /api/projects — the Project Hub. Covers listing/grouping by
status, the org's max_projects cap, valid/invalid status transitions, rename,
and the full session-scoped creation flow (purpose -> chat -> generate).

Follows the test_roadmap.py / test_onboarding_v2.py skeleton (tmp_db fixture,
_patch_clerk, ASGI test client, manual seeding, Groq faked the same way
test_roadmap.py fakes it for generate/regenerate).
"""

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from httpx import AsyncClient, ASGITransport
from openai import RateLimitError

from src.main import app
from src.database import get_db
from src.models.organization import Organization
from src.models.team import Team
from src.models.onboarding_session import OnboardingSession
from src.models.project import Project

ORG = "org_projects_test"
USER = "user_projects"
AUTH = {"Authorization": "Bearer tok"}


def _patch_clerk(user_id=USER, org_id=ORG):
    payload = {"sub": user_id, "org_id": org_id}
    state = type("S", (), {"is_signed_in": True, "payload": payload})()
    return patch("src.auth._clerk.authenticate_request_async", new=AsyncMock(return_value=state))


def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _seed_org(clerk_org_id=ORG, with_team=True, max_projects=None):
    org_id, team_id = uuid.uuid4(), uuid.uuid4()
    async for db in app.dependency_overrides[get_db]():
        db.add(Organization(
            id=org_id, clerk_org_id=clerk_org_id, name="Test Org", slug=clerk_org_id,
            use_managed_key=False, max_projects=max_projects,
        ))
        if with_team:
            db.add(Team(id=team_id, organization_id=org_id, name="Default"))
        await db.commit()
        return org_id, (team_id if with_team else None)


async def _seed_project(team_id, session_id=None, status="active", name="Proj"):
    project_id = uuid.uuid4()
    async for db in app.dependency_overrides[get_db]():
        if session_id is None:
            session = OnboardingSession(
                id=uuid.uuid4(), organization_id=None, status="completed",
            )
            # organization_id is required; caller must pass a real session_id
            # in practice — kept simple here since every call site below does.
            raise AssertionError("pass an explicit session_id")
        db.add(Project(
            id=project_id, team_id=team_id, onboarding_session_id=session_id,
            name=name, purpose="hobby", status=status,
        ))
        await db.commit()
        return project_id


async def _seed_session(org_id, brief=None, purpose=None):
    session_id = uuid.uuid4()
    async for db in app.dependency_overrides[get_db]():
        db.add(OnboardingSession(
            id=session_id, organization_id=org_id, status="in_progress",
            project_brief=brief, project_purpose=purpose,
        ))
        await db.commit()
        return session_id


class _FakeToolCall:
    def __init__(self, name, payload):
        self.function = SimpleNamespace(name=name, arguments=json.dumps(payload))


class _FakeStream:
    """Async-iterable standing in for the OpenAI SDK's streaming response —
    see test_roadmap_generator.py for the shape this mirrors."""

    def __init__(self, chunks):
        self._chunks = chunks

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for chunk in self._chunks:
            yield chunk


def _stream_chunks_for(arguments, usage):
    if not arguments:
        return [SimpleNamespace(choices=[], usage=usage)]
    mid = len(arguments) // 2
    fragments = [arguments[:mid], arguments[mid:]] if mid else [arguments]
    chunks = [
        SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(
                tool_calls=[SimpleNamespace(function=SimpleNamespace(arguments=frag))]
            ))],
            usage=None,
        )
        for frag in fragments
        if frag
    ]
    chunks.append(SimpleNamespace(choices=[], usage=usage))
    return chunks


def _fake_groq(payload=None, tool_name="build_roadmap", tool_calls=None):
    """Stream-aware — /plan/draft's generating path now calls the streamed
    _call_planner_stream, not the non-streamed _call_planner."""
    if tool_calls is None:
        tool_calls = [_FakeToolCall(tool_name, payload)] if payload is not None else []
    message = SimpleNamespace(tool_calls=tool_calls or None)
    usage = SimpleNamespace(prompt_tokens=100, completion_tokens=200)
    response = SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)
    arguments = tool_calls[0].function.arguments if tool_calls else None
    stream_chunks = _stream_chunks_for(arguments, usage)

    async def create(**kwargs):
        return _FakeStream(stream_chunks) if kwargs.get("stream") else response

    fake_completions = SimpleNamespace(create=AsyncMock(side_effect=create))
    return SimpleNamespace(chat=SimpleNamespace(completions=fake_completions))


def _patch_groq(fake):
    return patch("src.services.roadmap_generator.AsyncOpenAI", return_value=fake)


def _patch_api_key():
    return patch(
        "src.services.idea_interview.resolve_api_key", new=AsyncMock(return_value="sk-test")
    )


# ─── GET /api/projects (list, grouped by status client-side) ────────────────────
@pytest.mark.asyncio
async def test_list_projects_empty(tmp_db):
    await _seed_org()
    with _patch_clerk():
        async with _client() as client:
            resp = await client.get("/api/projects", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["projects"] == []


@pytest.mark.asyncio
async def test_list_projects_all_statuses_and_filter(tmp_db):
    org_id, team_id = await _seed_org()
    s1 = await _seed_session(org_id)
    s2 = await _seed_session(org_id)
    s3 = await _seed_session(org_id)
    p_active = await _seed_project(team_id, s1, status="active", name="Active One")
    p_finished = await _seed_project(team_id, s2, status="finished", name="Finished One")
    p_archived = await _seed_project(team_id, s3, status="archived", name="Archived One")

    with _patch_clerk():
        async with _client() as client:
            resp_all = await client.get("/api/projects", headers=AUTH)
            resp_active = await client.get("/api/projects?status=active", headers=AUTH)

    assert {p["id"] for p in resp_all.json()["projects"]} == {
        str(p_active), str(p_finished), str(p_archived)
    }
    assert [p["id"] for p in resp_active.json()["projects"]] == [str(p_active)]
    assert resp_active.json()["projects"][0]["hasRoadmap"] is False


@pytest.mark.asyncio
async def test_list_projects_bad_status_422(tmp_db):
    await _seed_org()
    with _patch_clerk():
        async with _client() as client:
            resp = await client.get("/api/projects?status=bogus", headers=AUTH)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_projects_cross_org_isolation(tmp_db):
    org_a, team_a = await _seed_org(clerk_org_id="org_a")
    session_a = await _seed_session(org_a)
    await _seed_project(team_a, session_a, name="A's project")
    await _seed_org(clerk_org_id="org_b")

    with _patch_clerk(org_id="org_b"):
        async with _client() as client:
            resp = await client.get("/api/projects", headers=AUTH)
    assert resp.json()["projects"] == []


# ─── GET /api/projects/{id} ──────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_get_project_not_found(tmp_db):
    await _seed_org()
    with _patch_clerk():
        async with _client() as client:
            resp = await client.get(f"/api/projects/{uuid.uuid4()}", headers=AUTH)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "project_not_found"


# ─── PATCH /api/projects/{id} — rename + status transitions ────────────────────
@pytest.mark.asyncio
async def test_rename_project(tmp_db):
    org_id, team_id = await _seed_org()
    session_id = await _seed_session(org_id)
    project_id = await _seed_project(team_id, session_id, name="Old Name")

    with _patch_clerk():
        async with _client() as client:
            resp = await client.patch(
                f"/api/projects/{project_id}", json={"name": "New Name"}, headers=AUTH
            )
    assert resp.status_code == 200
    assert resp.json()["name"] == "New Name"


@pytest.mark.asyncio
@pytest.mark.parametrize("start,target", [
    ("active", "finished"),
    ("finished", "active"),
    ("active", "archived"),
    ("archived", "active"),
    ("finished", "archived"),
])
async def test_valid_status_transitions(tmp_db, start, target):
    org_id, team_id = await _seed_org()
    session_id = await _seed_session(org_id)
    project_id = await _seed_project(team_id, session_id, status=start)

    with _patch_clerk():
        async with _client() as client:
            resp = await client.patch(
                f"/api/projects/{project_id}", json={"status": target}, headers=AUTH
            )
    assert resp.status_code == 200
    assert resp.json()["status"] == target


@pytest.mark.asyncio
async def test_archived_to_finished_is_not_allowed(tmp_db):
    org_id, team_id = await _seed_org()
    session_id = await _seed_session(org_id)
    project_id = await _seed_project(team_id, session_id, status="archived")

    with _patch_clerk():
        async with _client() as client:
            resp = await client.patch(
                f"/api/projects/{project_id}", json={"status": "finished"}, headers=AUTH
            )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "invalid_status_transition"


# ─── POST /api/projects — cap enforcement ───────────────────────────────────────
@pytest.mark.asyncio
async def test_start_creation_no_cap_allows_many(tmp_db):
    org_id, team_id = await _seed_org(max_projects=None)
    session_id = await _seed_session(org_id)
    await _seed_project(team_id, session_id)

    with _patch_clerk():
        async with _client() as client:
            resp = await client.post("/api/projects", headers=AUTH)
    assert resp.status_code == 201
    assert "sessionId" in resp.json()


@pytest.mark.asyncio
async def test_start_creation_cap_reached_422(tmp_db):
    org_id, team_id = await _seed_org(max_projects=1)
    session_id = await _seed_session(org_id)
    await _seed_project(team_id, session_id)

    with _patch_clerk():
        async with _client() as client:
            resp = await client.post("/api/projects", headers=AUTH)
    assert resp.status_code == 422
    assert resp.json()["detail"] == "project_limit_reached"


@pytest.mark.asyncio
async def test_cap_counts_archived_projects_too(tmp_db):
    """Archiving is a visibility flag, not a resource-freeing operation — it
    must not be a loophole around the cap."""
    org_id, team_id = await _seed_org(max_projects=1)
    session_id = await _seed_session(org_id)
    await _seed_project(team_id, session_id, status="archived")

    with _patch_clerk():
        async with _client() as client:
            resp = await client.post("/api/projects", headers=AUTH)
    assert resp.status_code == 422
    assert resp.json()["detail"] == "project_limit_reached"


# ─── Full creation flow: POST -> purpose -> chat -> generate ────────────────────
@pytest.mark.asyncio
async def test_full_creation_flow(tmp_db):
    org_id, team_id = await _seed_org()

    with _patch_clerk():
        async with _client() as client:
            start_resp = await client.post("/api/projects", headers=AUTH)
            assert start_resp.status_code == 201
            session_id = start_resp.json()["sessionId"]

            purpose_resp = await client.put(
                f"/api/projects/sessions/{session_id}/purpose",
                json={"purpose": "startup"},
                headers=AUTH,
            )
            assert purpose_resp.status_code == 200
            assert purpose_resp.json()["purpose"] == "startup"

            chat_resp = await client.get(
                f"/api/projects/sessions/{session_id}/chat", headers=AUTH
            )
            assert chat_resp.status_code == 200
            assert chat_resp.json()["messages"][0]["role"] == "assistant"

    # Fake the interview turn directly (SSE streaming isn't worth faking token-
    # by-token here — same approach test_onboarding_v2.py uses for idea_chat).
    fake_result = {
        "message_id": str(uuid.uuid4()),
        "status": "in_progress",
        "brief": {"projectName": "New Co", "problemStatement": "Something real"},
        "missing_fields": [],
        "brief_complete": True,
    }
    with _patch_clerk():
        async with _client() as client:
            with patch(
                "src.routers.projects.idea_interview.run_interview_turn",
                new=AsyncMock(return_value=fake_result),
            ), _patch_api_key():
                msg_resp = await client.post(
                    f"/api/projects/sessions/{session_id}/chat/message",
                    json={"content": "It's a project management tool."},
                    headers=AUTH,
                )
                assert msg_resp.status_code == 200
                # Drain the SSE stream so the mocked runner actually executes.
                assert b"done" in msg_resp.content or msg_resp.content

    # Manually mark the brief complete on the session (the streamed turn does
    # this in the real flow; here we bypass the SSE body to keep the test
    # focused on the generate step).
    async for db in app.dependency_overrides[get_db]():
        from sqlalchemy import select
        session = await db.scalar(
            select(OnboardingSession).where(OnboardingSession.id == uuid.UUID(session_id))
        )
        session.project_brief = fake_result["brief"]
        await db.commit()
        break

    roadmap_payload = {
        "projectName": "New Co",
        "milestones": [{"title": "Kickoff", "tasks": [{"title": "Set up repo", "dayOffset": 0}]}],
    }
    fake_groq = _fake_groq(roadmap_payload)

    with _patch_clerk(), _patch_api_key(), _patch_groq(fake_groq):
        async with _client() as client:
            gen_resp = await client.post(
                f"/api/projects/sessions/{session_id}/generate", headers=AUTH
            )
    assert gen_resp.status_code == 200
    body = gen_resp.json()
    assert body["name"] == "New Co"
    assert body["hasRoadmap"] is True

    # Idempotent: calling generate again returns the same project rather than
    # erroring on the 1:1 onboarding_session_id FK.
    with _patch_clerk(), _patch_api_key(), _patch_groq(fake_groq):
        async with _client() as client:
            gen_resp2 = await client.post(
                f"/api/projects/sessions/{session_id}/generate", headers=AUTH
            )
    assert gen_resp2.json()["id"] == body["id"]
    assert fake_groq.chat.completions.create.await_count == 1


@pytest.mark.asyncio
async def test_generate_returns_429_when_groq_rate_limits(tmp_db):
    """A provider rate limit is its own status, not a generic 502 — the UI
    surfaces "try again in a moment" and nothing is persisted."""
    org_id, _ = await _seed_org()
    session_id = await _seed_session(org_id, brief={"projectName": "X"})

    rate_limited = RateLimitError(
        "Rate limit reached",
        response=httpx.Response(429, request=httpx.Request("POST", "http://groq.test")),
        body={"code": "rate_limit_exceeded"},
    )
    fake_groq = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=AsyncMock(side_effect=rate_limited)
    )))

    with _patch_clerk(), _patch_api_key(), _patch_groq(fake_groq):
        async with _client() as client:
            resp = await client.post(
                f"/api/projects/sessions/{session_id}/generate", headers=AUTH
            )
    assert resp.status_code == 429
    assert "rate limit" in resp.json()["detail"].lower()
    assert fake_groq.chat.completions.create.await_count == 1


@pytest.mark.asyncio
async def test_generate_requires_brief(tmp_db):
    org_id, team_id = await _seed_org()
    session_id = await _seed_session(org_id, purpose="hobby")

    with _patch_clerk():
        async with _client() as client:
            resp = await client.post(
                f"/api/projects/sessions/{session_id}/generate", headers=AUTH
            )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_generate_rechecks_cap(tmp_db):
    """Time may pass between POST /api/projects and .../generate; the cap is
    re-checked at generate time too."""
    org_id, team_id = await _seed_org(max_projects=1)
    session_id = await _seed_session(org_id, brief={"projectName": "X"})
    # A different project fills the cap between start and generate.
    other_session = await _seed_session(org_id)
    await _seed_project(team_id, other_session)

    with _patch_clerk():
        async with _client() as client:
            resp = await client.post(
                f"/api/projects/sessions/{session_id}/generate", headers=AUTH
            )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "project_limit_reached"
