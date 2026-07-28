import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient, ASGITransport

from src.main import app

ORG = "org_v2_test"
USER = "user_v2"


def _patch_clerk(user_id=USER, org_id=ORG):
    payload = {"sub": user_id, "org_id": org_id}
    state = type("S", (), {"is_signed_in": True, "payload": payload})()
    return patch("src.auth._clerk.authenticate_request_async", new=AsyncMock(return_value=state))


async def _seed_org_and_team(clerk_org_id=ORG):
    from src.database import get_db
    from src.models.organization import Organization
    from src.models.team import Team

    async for db in app.dependency_overrides[get_db]():
        org = Organization(
            id=uuid.uuid4(),
            clerk_org_id=clerk_org_id,
            name="Test Org",
            slug=clerk_org_id,
            use_managed_key=False,
        )
        db.add(org)
        await db.flush()
        team = Team(id=uuid.uuid4(), organization_id=org.id, name="Default")
        db.add(team)
        await db.commit()
        return org.id, team.id


def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


AUTH = {"Authorization": "Bearer tok"}


class _FakeToolCall:
    def __init__(self, name, payload):
        self.function = SimpleNamespace(name=name, arguments=json.dumps(payload))


def _fake_groq(payload=None, tool_name="build_roadmap", tool_calls=None):
    """Mirrors test_projects.py's fake Groq client (same forced-tool shape
    roadmap_generator.generate_roadmap expects)."""
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


async def _complete_profile_and_chat(org_id, team_id, brief):
    """Fast-forwards past github/profile/purpose/plan-source and stamps the
    idea-chat session as completed with `brief`, bypassing the real SSE chat
    turns — mirrors how test_projects.py sets up its own generate tests."""
    from src.database import get_db
    from src.models.onboarding_session import OnboardingSession

    with _patch_clerk():
        async with _client() as client:
            await client.post("/api/onboarding/v2/github/skip", headers=AUTH)
            await client.put(
                "/api/onboarding/v2/profile", json={"name": "Ada", "phone": "+15551234567"},
                headers=AUTH,
            )
            await client.put("/api/onboarding/v2/purpose", json={"purpose": "startup"}, headers=AUTH)
            await client.put(
                "/api/onboarding/v2/plan-source", json={"source": "chat"}, headers=AUTH
            )

    async for db in app.dependency_overrides[get_db]():
        from sqlalchemy import select

        session = await db.scalar(
            select(OnboardingSession).where(OnboardingSession.organization_id == org_id)
        )
        session.project_brief = brief
        session.status = "completed"
        await db.commit()
        return session.id


@pytest.mark.asyncio
async def test_state_requires_provisioned_org(tmp_db):
    with _patch_clerk():
        async with _client() as client:
            resp = await client.get("/api/onboarding/v2/state", headers=AUTH)
    assert resp.status_code == 409
    assert resp.json()["detail"] == "org_not_provisioned"


@pytest.mark.asyncio
async def test_state_initial(tmp_db):
    await _seed_org_and_team()
    with _patch_clerk():
        async with _client() as client:
            resp = await client.get("/api/onboarding/v2/state", headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["currentStep"] == "github_connect"
    assert [s["id"] for s in body["steps"]] == [
        "github_connect", "profile", "purpose", "build_plan", "repo_select",
    ]
    # repo_select auto-completes when there's no GitHub connection to pick a
    # repo from at all yet (see docs/plans/2026-07-20-import-artifacts.md) —
    # it's "complete" out of order here, ahead of steps still pending.
    assert [s["status"] for s in body["steps"]] == [
        "current", "pending", "pending", "pending", "complete",
    ]
    assert body["github"] == {"connected": False, "login": None, "skipped": False, "needsReconnect": False}
    assert body["profile"] == {"name": None, "phone": None, "complete": False}
    assert body["purpose"] == {"value": None, "complete": False}
    assert body["ideaChat"]["status"] == "not_started"
    assert body["onboardingPath"] is None
    assert body["importArtifact"] is None
    assert body["repo"] == {"selected": None, "skipped": False, "available": False}
    assert body["onboardingCompleted"] is False


@pytest.mark.asyncio
async def test_github_skip_advances_flow(tmp_db):
    await _seed_org_and_team()
    with _patch_clerk():
        async with _client() as client:
            resp = await client.post("/api/onboarding/v2/github/skip", headers=AUTH)
    body = resp.json()
    assert body["github"]["skipped"] is True
    assert body["currentStep"] == "profile"
    assert [s["status"] for s in body["steps"]] == [
        "complete", "current", "pending", "pending", "complete",
    ]


@pytest.mark.asyncio
async def test_github_connection_completes_step(tmp_db):
    org_id, _ = await _seed_org_and_team()

    from src.database import get_db
    from src.models.github_connection import GithubConnection
    from src.services.encryption import encrypt

    async for db in app.dependency_overrides[get_db]():
        db.add(GithubConnection(
            organization_id=org_id,
            installation_id="inst_1",
            github_user_id="42",
            github_login="octocat",
            encrypted_access_token=encrypt("tok"),
            is_active=True,
        ))
        await db.commit()
        break

    with _patch_clerk():
        async with _client() as client:
            resp = await client.get("/api/onboarding/v2/state", headers=AUTH)
    body = resp.json()
    assert body["github"]["connected"] is True
    assert body["github"]["login"] == "octocat"
    assert body["github"]["needsReconnect"] is False
    assert body["currentStep"] == "profile"


@pytest.mark.asyncio
async def test_github_legacy_connection_needs_reconnect_and_blocks_step(tmp_db):
    """A pre-GitHub-App-migration connection (no installation_id) must not
    complete the step — the user has to reconnect through the App install
    flow before onboarding advances."""
    org_id, _ = await _seed_org_and_team()

    from src.database import get_db
    from src.models.github_connection import GithubConnection
    from src.services.encryption import encrypt

    async for db in app.dependency_overrides[get_db]():
        db.add(GithubConnection(
            organization_id=org_id,
            github_user_id="42",
            github_login="octocat",
            encrypted_access_token=encrypt("legacy_oauth_tok"),
            is_active=True,
        ))
        await db.commit()
        break

    with _patch_clerk():
        async with _client() as client:
            resp = await client.get("/api/onboarding/v2/state", headers=AUTH)
    body = resp.json()
    assert body["github"]["connected"] is True
    assert body["github"]["needsReconnect"] is True
    assert body["currentStep"] == "github_connect"
    github_step = next(s for s in body["steps"] if s["id"] == "github_connect")
    assert github_step["status"] == "current"


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    {"name": "", "phone": "+1 555 123 4567"},
    {"name": "Ada", "phone": "not-a-phone"},
    {"name": "Ada", "phone": "12"},
    {"name": "x" * 300, "phone": "+1 555 123 4567"},
])
async def test_profile_validation(tmp_db, payload):
    await _seed_org_and_team()
    with _patch_clerk():
        async with _client() as client:
            resp = await client.put("/api/onboarding/v2/profile", json=payload, headers=AUTH)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_profile_upserts_and_completes_step(tmp_db):
    await _seed_org_and_team()
    with _patch_clerk():
        async with _client() as client:
            resp = await client.put(
                "/api/onboarding/v2/profile",
                json={"name": "Ada Lovelace", "phone": "+1 (555) 123-4567"},
                headers=AUTH,
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["profile"] == {
                "name": "Ada Lovelace",
                "phone": "+1 (555) 123-4567",
                "complete": True,
            }

            # Updating again must not create a second Developer row.
            resp = await client.put(
                "/api/onboarding/v2/profile",
                json={"name": "Ada L.", "phone": "+1 555 000 1111"},
                headers=AUTH,
            )
            assert resp.json()["profile"]["name"] == "Ada L."

    from sqlalchemy import func, select
    from src.database import get_db
    from src.models.developer import Developer

    async for db in app.dependency_overrides[get_db]():
        count = await db.scalar(select(func.count(Developer.id)))
        assert count == 1
        break


@pytest.mark.asyncio
@pytest.mark.parametrize("purpose", ["", "business", "Startup", "hobby "])
async def test_purpose_validation(tmp_db, purpose):
    await _seed_org_and_team()
    with _patch_clerk():
        async with _client() as client:
            resp = await client.put(
                "/api/onboarding/v2/purpose", json={"purpose": purpose}, headers=AUTH
            )
    # "Startup" / "hobby " are normalized (stripped + lowercased) and accepted;
    # only genuinely unknown values or an empty string should 422.
    if purpose.strip().lower() in ("hobby", "startup", "learning"):
        assert resp.status_code == 200
    else:
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_purpose_completes_step_and_advances_flow(tmp_db):
    await _seed_org_and_team()
    with _patch_clerk():
        async with _client() as client:
            await client.post("/api/onboarding/v2/github/skip", headers=AUTH)
            await client.put(
                "/api/onboarding/v2/profile",
                json={"name": "Ada", "phone": "+15551234567"},
                headers=AUTH,
            )
            resp = await client.put(
                "/api/onboarding/v2/purpose", json={"purpose": "hobby"}, headers=AUTH
            )
    body = resp.json()
    assert body["purpose"] == {"value": "hobby", "complete": True}
    # No plan-source chosen yet, so the 4th step is still "build_plan" (the
    # chooser), not "idea_chat" — see PUT /plan-source.
    assert body["currentStep"] == "build_plan"
    assert [s["id"] for s in body["steps"]] == [
        "github_connect", "profile", "purpose", "build_plan", "repo_select",
    ]
    assert [s["status"] for s in body["steps"]] == [
        "complete", "complete", "complete", "current", "complete",
    ]


@pytest.mark.asyncio
async def test_chat_start_requires_purpose(tmp_db):
    await _seed_org_and_team()
    with _patch_clerk():
        async with _client() as client:
            resp = await client.post("/api/onboarding/v2/chat/start", headers=AUTH)
    assert resp.status_code == 409
    assert resp.json()["detail"] == "purpose_not_set"


@pytest.mark.asyncio
async def test_autoprovisioned_developer_name_not_leaked(tmp_db):
    """A Developer row auto-created with name == clerk_user_id doesn't count as a profile."""
    org_id, team_id = await _seed_org_and_team()

    from src.database import get_db
    from src.models.developer import Developer

    async for db in app.dependency_overrides[get_db]():
        db.add(Developer(
            id=uuid.uuid4(), team_id=team_id, clerk_user_id=USER, name=USER, app_role="developer",
        ))
        await db.commit()
        break

    with _patch_clerk():
        async with _client() as client:
            resp = await client.get("/api/onboarding/v2/state", headers=AUTH)
    body = resp.json()
    assert body["profile"] == {"name": None, "phone": None, "complete": False}


@pytest.mark.asyncio
async def test_complete_requires_profile(tmp_db):
    await _seed_org_and_team()
    with _patch_clerk():
        async with _client() as client:
            resp = await client.post("/api/onboarding/v2/complete", headers=AUTH)
    assert resp.status_code == 409
    assert resp.json()["detail"] == "profile_incomplete"


@pytest.mark.asyncio
async def test_complete_sets_completed_at_idempotently(tmp_db):
    await _seed_org_and_team()
    with _patch_clerk():
        async with _client() as client:
            await client.put(
                "/api/onboarding/v2/profile",
                json={"name": "Ada", "phone": "+15551234567"},
                headers=AUTH,
            )
            resp = await client.post("/api/onboarding/v2/complete", headers=AUTH)
            assert resp.status_code == 200
            first = resp.json()["completedAt"]

            resp = await client.post("/api/onboarding/v2/complete", headers=AUTH)
            assert resp.json()["completedAt"] == first

            state = (await client.get("/api/onboarding/v2/state", headers=AUTH)).json()
            assert state["onboardingCompleted"] is True


@pytest.mark.asyncio
async def test_org_onboarding_resolves_to_earliest_session(tmp_db):
    """An org can now have multiple OnboardingSessions (one per project, see
    docs/plans/2026-07-20-project-hub.md) — org onboarding must still always
    resolve to the FIRST session ever created, even after project-creation
    sessions exist for the same org."""
    org_id, team_id = await _seed_org_and_team()

    from src.database import get_db
    from src.models.onboarding_session import OnboardingSession

    founding_id = uuid.uuid4()
    later_id = uuid.uuid4()
    async for db in app.dependency_overrides[get_db]():
        db.add(OnboardingSession(
            id=founding_id, organization_id=org_id, status="in_progress",
            project_purpose="startup",
        ))
        await db.flush()
        # A later, second-project-creation session for the same org.
        db.add(OnboardingSession(
            id=later_id, organization_id=org_id, status="in_progress",
            project_purpose="hobby",
        ))
        await db.commit()
        break

    with _patch_clerk():
        async with _client() as client:
            resp = await client.get("/api/onboarding/v2/state", headers=AUTH)
    assert resp.status_code == 200
    # The founding session's purpose ("startup"), not the later one's ("hobby").
    assert resp.json()["purpose"]["value"] == "startup"


# ─── plan-source (build_plan chooser) ──────────────────────────────────────────
@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["", "carrier_pigeon", "Chat", " import "])
async def test_plan_source_validation(tmp_db, source):
    await _seed_org_and_team()
    with _patch_clerk():
        async with _client() as client:
            resp = await client.put(
                "/api/onboarding/v2/plan-source", json={"source": source}, headers=AUTH
            )
    if source.strip().lower() in ("chat", "import"):
        assert resp.status_code == 200
    else:
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_plan_source_chat_advances_to_idea_chat_step(tmp_db):
    await _seed_org_and_team()
    with _patch_clerk():
        async with _client() as client:
            await client.post("/api/onboarding/v2/github/skip", headers=AUTH)
            await client.put(
                "/api/onboarding/v2/profile", json={"name": "Ada", "phone": "+15551234567"},
                headers=AUTH,
            )
            await client.put("/api/onboarding/v2/purpose", json={"purpose": "hobby"}, headers=AUTH)
            resp = await client.put(
                "/api/onboarding/v2/plan-source", json={"source": "chat"}, headers=AUTH
            )
    body = resp.json()
    assert body["onboardingPath"] == "chat"
    assert body["currentStep"] == "idea_chat"
    assert [s["id"] for s in body["steps"]] == [
        "github_connect", "profile", "purpose", "idea_chat", "repo_select",
    ]


@pytest.mark.asyncio
async def test_plan_source_import_advances_to_import_artifact_step(tmp_db):
    await _seed_org_and_team()
    with _patch_clerk():
        async with _client() as client:
            await client.post("/api/onboarding/v2/github/skip", headers=AUTH)
            await client.put(
                "/api/onboarding/v2/profile", json={"name": "Ada", "phone": "+15551234567"},
                headers=AUTH,
            )
            await client.put("/api/onboarding/v2/purpose", json={"purpose": "startup"}, headers=AUTH)
            resp = await client.put(
                "/api/onboarding/v2/plan-source", json={"source": "import"}, headers=AUTH
            )
    body = resp.json()
    assert body["onboardingPath"] == "import"
    assert body["currentStep"] == "import_artifact"
    assert [s["id"] for s in body["steps"]] == [
        "github_connect", "profile", "purpose", "import_artifact", "repo_select",
    ]


# ─── repo select ────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_repo_select_before_project_exists_only_sets_session(tmp_db):
    """On the chat path, no Project exists yet when a repo is picked — only
    the session field is set; generate_roadmap copies it onto the Project
    later (see roadmap_generator.generate_roadmap)."""
    await _seed_org_and_team()
    with _patch_clerk():
        async with _client() as client:
            resp = await client.put(
                "/api/onboarding/v2/repo", json={"repoFullName": "octocat/hello-world"}, headers=AUTH
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body["repo"] == {"selected": "octocat/hello-world", "skipped": False, "available": False}


@pytest.mark.asyncio
async def test_repo_select_after_project_exists_stamps_project(tmp_db):
    """On the import path, /import/apply already created the Project by the
    time repo-select runs — PUT /repo must stamp it immediately."""
    org_id, team_id = await _seed_org_and_team()

    from src.database import get_db
    from src.models.onboarding_session import OnboardingSession
    from src.models.project import Project

    session_id = uuid.uuid4()
    async for db in app.dependency_overrides[get_db]():
        db.add(OnboardingSession(
            id=session_id, organization_id=org_id, status="completed", onboarding_path="import",
        ))
        await db.flush()
        db.add(Project(team_id=team_id, onboarding_session_id=session_id, name="Imported Project"))
        await db.commit()
        break

    with _patch_clerk():
        async with _client() as client:
            resp = await client.put(
                "/api/onboarding/v2/repo", json={"repoFullName": "octocat/hello-world"}, headers=AUTH
            )
    assert resp.status_code == 200
    assert resp.json()["repo"]["selected"] == "octocat/hello-world"

    async for db in app.dependency_overrides[get_db]():
        from sqlalchemy import select as sa_select
        project = await db.scalar(sa_select(Project).where(Project.onboarding_session_id == session_id))
        assert project.github_repo_full_name == "octocat/hello-world"
        break


@pytest.mark.asyncio
async def test_repo_skip_is_idempotent_and_advances_flow(tmp_db):
    await _seed_org_and_team()
    with _patch_clerk():
        async with _client() as client:
            resp = await client.post("/api/onboarding/v2/repo/skip", headers=AUTH)
            assert resp.status_code == 200
            assert resp.json()["repo"]["skipped"] is True
            first = resp.json()

            resp = await client.post("/api/onboarding/v2/repo/skip", headers=AUTH)
            assert resp.json()["repo"] == first["repo"]


@pytest.mark.asyncio
async def test_repo_select_required_when_github_connected(tmp_db):
    """Unlike the no-connection case, repo_select must NOT auto-complete once
    GitHub is actually connected — the user has real repos to choose from."""
    org_id, _ = await _seed_org_and_team()

    from src.database import get_db
    from src.models.github_connection import GithubConnection
    from src.services.encryption import encrypt

    async for db in app.dependency_overrides[get_db]():
        db.add(GithubConnection(
            organization_id=org_id,
            installation_id="inst_1",
            github_user_id="42",
            github_login="octocat",
            encrypted_access_token=encrypt("tok"),
            is_active=True,
        ))
        await db.commit()
        break

    with _patch_clerk():
        async with _client() as client:
            resp = await client.get("/api/onboarding/v2/state", headers=AUTH)
    body = resp.json()
    assert body["repo"] == {"selected": None, "skipped": False, "available": True}
    repo_step = next(s for s in body["steps"] if s["id"] == "repo_select")
    assert repo_step["status"] != "complete"


@pytest.mark.asyncio
async def test_complete_generates_and_returns_project_for_chat_path(tmp_db):
    """The chat path never generates a roadmap on its own (unlike the import
    path, which creates the Project synchronously in /import/apply) — Finish
    must draft it now so the frontend can land the user on their new plan
    instead of the empty project hub."""
    org_id, team_id = await _seed_org_and_team()
    await _complete_profile_and_chat(
        org_id, team_id, {"projectName": "New Co", "problemStatement": "Something real"},
    )

    roadmap_payload = {
        "projectName": "New Co",
        "milestones": [{"title": "Kickoff", "tasks": [{"title": "Set up repo", "dayOffset": 0}]}],
    }
    fake_groq = _fake_groq(roadmap_payload)

    with _patch_clerk(), _patch_api_key(), _patch_groq(fake_groq):
        async with _client() as client:
            resp = await client.post("/api/onboarding/v2/complete", headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["projectId"] is not None

    from src.database import get_db
    from src.models.project import Project
    from sqlalchemy import select

    async for db in app.dependency_overrides[get_db]():
        project = await db.scalar(
            select(Project).where(Project.id == uuid.UUID(body["projectId"]))
        )
        assert project is not None
        assert project.name == "New Co"
        break

    # Idempotent: calling complete again doesn't regenerate the roadmap.
    with _patch_clerk(), _patch_api_key(), _patch_groq(fake_groq):
        async with _client() as client:
            resp2 = await client.post("/api/onboarding/v2/complete", headers=AUTH)
    assert resp2.json()["projectId"] == body["projectId"]
    assert fake_groq.chat.completions.create.await_count == 1


@pytest.mark.asyncio
async def test_complete_still_finishes_onboarding_when_generation_fails(tmp_db):
    """Roadmap generation is best-effort — the endpoint's own "never brick"
    rule applies here too, so a failed generation still completes onboarding
    and just leaves projectId null."""
    org_id, team_id = await _seed_org_and_team()
    await _complete_profile_and_chat(org_id, team_id, {"projectName": "New Co"})

    # No tool_calls at all -> generate_roadmap raises RuntimeError internally.
    fake_groq = _fake_groq(tool_calls=[])

    with _patch_clerk(), _patch_api_key(), _patch_groq(fake_groq):
        async with _client() as client:
            resp = await client.post("/api/onboarding/v2/complete", headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["projectId"] is None
    assert body["completedAt"] is not None

    with _patch_clerk():
        async with _client() as client:
            state = (await client.get("/api/onboarding/v2/state", headers=AUTH)).json()
    assert state["onboardingCompleted"] is True
