import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from httpx import AsyncClient, ASGITransport
from openai import RateLimitError

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
    """Mirrors test_projects.py's fake Groq client (same forced-tool shape
    roadmap_generator.generate_roadmap expects) — stream-aware, since
    /plan/draft's generating path now calls the streamed _call_planner_stream."""
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


def _parse_sse(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.strip().split("\n\n"):
        lines = block.split("\n")
        event = next(l[len("event: "):] for l in lines if l.startswith("event: "))
        data = next(l[len("data: "):] for l in lines if l.startswith("data: "))
        events.append((event, json.loads(data)))
    return events


def _patch_api_key():
    return patch(
        "src.services.idea_interview.resolve_api_key", new=AsyncMock(return_value="sk-test")
    )


async def _complete_profile_and_chat(org_id, team_id, brief):
    """Fast-forwards past github/profile/purpose/tech-stack/plan-source and
    stamps the idea-chat session as completed with `brief`, bypassing the real
    SSE chat turns — mirrors how test_projects.py sets up its own generate
    tests. tech_stack is flag-gated (on in the test env), so it's completed here
    too; otherwise the derived flow parks there and never reaches later steps."""
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
                "/api/onboarding/v2/tech-stack",
                json={"stack": ["React"], "experience": "experienced"},
                headers=AUTH,
            )
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
    assert body["currentStep"] == "profile"
    # tech_stack only appears when experimental.tech_stack_step is on (true in
    # the test environment — see conftest.py).
    # plan_review (flag-gated, on in test env) is appended as the last step.
    assert [s["id"] for s in body["steps"]] == [
        "profile", "purpose", "tech_stack", "build_plan", "github_repo",
        "plan_review",
    ]
    # Unlike the old repo_select, github_repo does NOT auto-complete on a
    # totally fresh session: it requires the GitHub half to be explicitly
    # resolved (connected or skipped) before the merged step counts as done,
    # since that decision now lives inside this step rather than an earlier
    # one. It only auto-completes once github_done is true and there's still
    # no connection (see test_github_skip_advances_flow).
    assert [s["status"] for s in body["steps"]] == [
        "current", "pending", "pending", "pending", "pending", "pending",
    ]
    assert body["github"] == {"connected": False, "login": None, "skipped": False, "needsReconnect": False}
    assert body["profile"] == {"name": None, "phone": None, "complete": False}
    assert body["purpose"] == {"value": None, "complete": False}
    assert body["techStack"] == {"stack": [], "experience": None, "complete": False}
    assert body["ideaChat"]["status"] == "not_started"
    assert body["onboardingPath"] is None
    assert body["importArtifact"] is None
    assert body["repo"] == {
        "selected": None, "skipped": False, "available": False,
        "canCreate": False, "ownerLogin": None,
    }
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
    # Skipping GitHub alone auto-completes the whole github_repo step too
    # (no connection means no repo to pick from either) — but profile, the
    # step now in front of it, is untouched and still current.
    assert [s["status"] for s in body["steps"]] == [
        "current", "pending", "pending", "pending", "complete", "pending",
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
    complete the github_repo step — the user has to reconnect through the App
    install flow before onboarding can finish. Since github_repo now sits at
    position 5 (merged with repo_select), this no longer blocks the whole
    flow from the front — profile/purpose/tech-stack/plan-source all still
    complete normally ahead of it."""
    org_id, _ = await _seed_org_and_team()

    from sqlalchemy import select
    from src.database import get_db
    from src.models.github_connection import GithubConnection
    from src.models.onboarding_session import OnboardingSession
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
            await client.put(
                "/api/onboarding/v2/profile", json={"name": "Ada", "phone": "+15551234567"},
                headers=AUTH,
            )
            await client.put("/api/onboarding/v2/purpose", json={"purpose": "hobby"}, headers=AUTH)
            await client.put(
                "/api/onboarding/v2/tech-stack",
                json={"stack": ["React"], "experience": "experienced"},
                headers=AUTH,
            )
            await client.put(
                "/api/onboarding/v2/plan-source", json={"source": "chat"}, headers=AUTH
            )

    # Stamp the idea-chat session completed directly, bypassing the real SSE
    # turns (same shortcut _complete_profile_and_chat uses below), so the
    # flow reaches github_repo without needing GitHub connected for it.
    async for db in app.dependency_overrides[get_db]():
        session = await db.scalar(
            select(OnboardingSession).where(OnboardingSession.organization_id == org_id)
        )
        session.status = "completed"
        await db.commit()
        break

    with _patch_clerk():
        async with _client() as client:
            resp = await client.get("/api/onboarding/v2/state", headers=AUTH)
    body = resp.json()
    assert body["github"]["connected"] is True
    assert body["github"]["needsReconnect"] is True
    assert body["currentStep"] == "github_repo"
    github_repo_step = next(s for s in body["steps"] if s["id"] == "github_repo")
    assert github_repo_step["status"] == "current"


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
    # tech_stack (flag-gated, on in test env) is required and comes right
    # after purpose, before the plan-source chooser.
    assert body["currentStep"] == "tech_stack"
    assert [s["id"] for s in body["steps"]] == [
        "profile", "purpose", "tech_stack", "build_plan", "github_repo",
        "plan_review",
    ]
    assert [s["status"] for s in body["steps"]] == [
        "complete", "complete", "current", "pending", "complete", "pending",
    ]


# ─── tech stack ─────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_tech_stack_experienced_completes_step(tmp_db):
    await _seed_org_and_team()
    with _patch_clerk():
        async with _client() as client:
            resp = await client.put(
                "/api/onboarding/v2/tech-stack",
                json={"stack": ["React", "Node.js"], "experience": "experienced"},
                headers=AUTH,
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body["techStack"] == {
        "stack": ["React", "Node.js"], "experience": "experienced", "complete": True,
    }


@pytest.mark.asyncio
async def test_tech_stack_new_completes_step_with_empty_stack(tmp_db):
    await _seed_org_and_team()
    with _patch_clerk():
        async with _client() as client:
            resp = await client.put(
                "/api/onboarding/v2/tech-stack",
                json={"stack": [], "experience": "new"},
                headers=AUTH,
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body["techStack"] == {"stack": [], "experience": "new", "complete": True}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"stack": ["React"], "experience": "new"},  # can't pick tools AND be new
        {"stack": [], "experience": "experienced"},  # experienced needs >=1 tool
        {"stack": ["React"], "experience": "expert"},  # not a valid experience value
    ],
)
async def test_tech_stack_rejects_inconsistent_payloads(tmp_db, payload):
    await _seed_org_and_team()
    with _patch_clerk():
        async with _client() as client:
            resp = await client.put(
                "/api/onboarding/v2/tech-stack", json=payload, headers=AUTH
            )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_tech_stack_404s_when_flag_off(tmp_db):
    await _seed_org_and_team()
    # settings is a pydantic model instance — patch the class method, not the
    # instance attribute (pydantic rejects arbitrary instance setattr).
    with patch("src.config.Settings.is_feature_enabled", return_value=False):
        with _patch_clerk():
            async with _client() as client:
                resp = await client.put(
                    "/api/onboarding/v2/tech-stack",
                    json={"stack": ["React"], "experience": "experienced"},
                    headers=AUTH,
                )
    assert resp.status_code == 404


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
            await client.put(
                "/api/onboarding/v2/tech-stack",
                json={"stack": ["React"], "experience": "experienced"},
                headers=AUTH,
            )
            resp = await client.put(
                "/api/onboarding/v2/plan-source", json={"source": "chat"}, headers=AUTH
            )
    body = resp.json()
    assert body["onboardingPath"] == "chat"
    assert body["currentStep"] == "idea_chat"
    assert [s["id"] for s in body["steps"]] == [
        "profile", "purpose", "tech_stack", "idea_chat", "github_repo",
        "plan_review",
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
            await client.put(
                "/api/onboarding/v2/tech-stack",
                json={"stack": [], "experience": "new"},
                headers=AUTH,
            )
            resp = await client.put(
                "/api/onboarding/v2/plan-source", json={"source": "import"}, headers=AUTH
            )
    body = resp.json()
    assert body["onboardingPath"] == "import"
    assert body["currentStep"] == "import_artifact"
    assert [s["id"] for s in body["steps"]] == [
        "profile", "purpose", "tech_stack", "import_artifact", "github_repo",
        "plan_review",
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
    assert body["repo"] == {
        "selected": "octocat/hello-world", "skipped": False, "available": False,
        "canCreate": False, "ownerLogin": None,
    }


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
    """Unlike the no-connection case, github_repo must NOT auto-complete once
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
    assert body["repo"] == {
        "selected": None, "skipped": False, "available": True,
        "canCreate": False, "ownerLogin": "octocat",
    }
    repo_step = next(s for s in body["steps"] if s["id"] == "github_repo")
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


# ─── plan review (plan_review flag) ─────────────────────────────────────────────
@pytest.mark.asyncio
async def test_plan_draft_generates_project_for_chat_path(tmp_db):
    """On the chat path the roadmap is now drafted here (moved out of
    /complete), so the founder can review it. State exposes the new projectId
    and the plan_review step."""
    org_id, team_id = await _seed_org_and_team()
    await _complete_profile_and_chat(
        org_id, team_id, {"projectName": "Draft Co", "problemStatement": "Real"},
    )
    fake_groq = _fake_groq({
        "projectName": "Draft Co",
        "milestones": [{"title": "Kickoff", "tasks": [{"title": "Set up repo", "dayOffset": 0}]}],
    })

    with _patch_clerk(), _patch_api_key(), _patch_groq(fake_groq):
        async with _client() as client:
            resp = await client.post("/api/onboarding/v2/plan/draft", headers=AUTH)
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
            events = _parse_sse(resp.text)
            assert [e for e, _ in events][-1] == "done"
            project_id = events[-1][1]["projectId"]
            assert project_id is not None

            state = (await client.get("/api/onboarding/v2/state", headers=AUTH)).json()
    assert state["projectId"] == project_id
    assert state["currentStep"] == "plan_review"
    assert state["planReview"] == {"confirmed": False}


@pytest.mark.asyncio
async def test_plan_draft_is_idempotent(tmp_db):
    """A second draft returns the same project without regenerating."""
    org_id, team_id = await _seed_org_and_team()
    await _complete_profile_and_chat(org_id, team_id, {"projectName": "Draft Co"})
    fake_groq = _fake_groq({
        "projectName": "Draft Co",
        "milestones": [{"title": "M", "tasks": [{"title": "T", "dayOffset": 0}]}],
    })

    with _patch_clerk(), _patch_api_key(), _patch_groq(fake_groq):
        async with _client() as client:
            first_resp = await client.post("/api/onboarding/v2/plan/draft", headers=AUTH)
            first_project_id = _parse_sse(first_resp.text)[-1][1]["projectId"]
            # Idempotent path: project already exists, so this is plain JSON —
            # no stream, nothing left to generate.
            second_resp = await client.post("/api/onboarding/v2/plan/draft", headers=AUTH)
            assert not second_resp.headers["content-type"].startswith("text/event-stream")
            second_project_id = second_resp.json()["projectId"]
    assert first_project_id == second_project_id
    assert fake_groq.chat.completions.create.await_count == 1


@pytest.mark.asyncio
async def test_plan_draft_502_when_generation_fails(tmp_db):
    """Unlike /complete's best-effort generation, /plan/draft surfaces a
    failure so the review UI can offer 'continue anyway'. Once the roadmap is
    actually streaming, generation failures come back as a terminal `error`
    SSE event rather than a non-200 status — headers are already sent by the
    time generation fails, same as /chat/message's existing error handling."""
    org_id, team_id = await _seed_org_and_team()
    await _complete_profile_and_chat(org_id, team_id, {"projectName": "Draft Co"})
    fake_groq = _fake_groq(tool_calls=[])  # no tool call -> RuntimeError inside

    with _patch_clerk(), _patch_api_key(), _patch_groq(fake_groq):
        async with _client() as client:
            resp = await client.post("/api/onboarding/v2/plan/draft", headers=AUTH)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(resp.text)
    assert events[-1][0] == "error"
    assert events[-1][1]["message"] == "roadmap_generation_failed"


@pytest.mark.asyncio
async def test_plan_draft_reports_rate_limit_distinctly(tmp_db):
    """A Groq 429 stops the generation and comes back as its own `rate_limited`
    error, not the generic failure — the review step tells the founder to wait
    and retry instead of implying their brief is the problem."""
    org_id, team_id = await _seed_org_and_team()
    await _complete_profile_and_chat(org_id, team_id, {"projectName": "Draft Co"})

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
            resp = await client.post("/api/onboarding/v2/plan/draft", headers=AUTH)
    events = _parse_sse(resp.text)
    assert events[-1] == ("error", {"message": "rate_limited"})
    # Terminal, not retried: one call, then stop.
    assert fake_groq.chat.completions.create.await_count == 1


@pytest.mark.asyncio
async def test_plan_draft_409_when_brief_incomplete(tmp_db):
    """No completed brief means nothing to draft from."""
    await _seed_org_and_team()
    with _patch_clerk():
        async with _client() as client:
            await client.post("/api/onboarding/v2/github/skip", headers=AUTH)
            resp = await client.post("/api/onboarding/v2/plan/draft", headers=AUTH)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_plan_confirm_completes_step_and_advances_to_done(tmp_db):
    """Confirm marks the drafted plan accepted; the flow advances to done."""
    org_id, team_id = await _seed_org_and_team()
    await _complete_profile_and_chat(org_id, team_id, {"projectName": "Draft Co"})
    fake_groq = _fake_groq({
        "projectName": "Draft Co",
        "milestones": [{"title": "M", "tasks": [{"title": "T", "dayOffset": 0}]}],
    })

    with _patch_clerk(), _patch_api_key(), _patch_groq(fake_groq):
        async with _client() as client:
            await client.post("/api/onboarding/v2/plan/draft", headers=AUTH)
            resp = await client.post("/api/onboarding/v2/plan/confirm", headers=AUTH)
    body = resp.json()
    assert body["planReview"] == {"confirmed": True}
    assert body["currentStep"] == "done"
    review_step = next(s for s in body["steps"] if s["id"] == "plan_review")
    assert review_step["status"] == "complete"


@pytest.mark.asyncio
async def test_plan_confirm_works_without_a_draft(tmp_db):
    """The 'continue anyway' path: confirm is safe even if drafting failed and
    no project exists — it just advances the flow."""
    org_id, team_id = await _seed_org_and_team()
    await _complete_profile_and_chat(org_id, team_id, {"projectName": "Draft Co"})

    with _patch_clerk():
        async with _client() as client:
            resp = await client.post("/api/onboarding/v2/plan/confirm", headers=AUTH)
    body = resp.json()
    assert body["planReview"] == {"confirmed": True}
    assert body["projectId"] is None
    assert body["currentStep"] == "done"


@pytest.mark.asyncio
async def test_plan_endpoints_404_when_flag_off(tmp_db):
    await _seed_org_and_team()
    with patch("src.config.Settings.is_feature_enabled", return_value=False):
        with _patch_clerk():
            async with _client() as client:
                draft = await client.post("/api/onboarding/v2/plan/draft", headers=AUTH)
                confirm = await client.post("/api/onboarding/v2/plan/confirm", headers=AUTH)
    assert draft.status_code == 404
    assert confirm.status_code == 404


# ─── repo create (repo_create flag) ─────────────────────────────────────────────
async def _seed_connection(org_id, account_type="Organization", login="octo-org"):
    """Seed an active GitHub connection with a non-expired token (so
    _get_valid_access_token returns it without a network refresh)."""
    from datetime import datetime, timedelta
    from src.database import get_db
    from src.models.github_connection import GithubConnection
    from src.services.encryption import encrypt

    async for db in app.dependency_overrides[get_db]():
        db.add(GithubConnection(
            organization_id=org_id,
            installation_id="inst_1",
            github_user_id="42",
            github_login=login,
            account_type=account_type,
            encrypted_access_token=encrypt("tok"),
            token_expires_at=datetime.utcnow() + timedelta(hours=1),
            is_active=True,
        ))
        await db.commit()
        break


def _fake_github_client(full_name="octo-org/new-repo"):
    return SimpleNamespace(create_repo=AsyncMock(return_value={"full_name": full_name}))


@pytest.mark.asyncio
async def test_state_exposes_can_create_for_org_install(tmp_db):
    org_id, _ = await _seed_org_and_team()
    await _seed_connection(org_id, account_type="Organization", login="octo-org")
    with _patch_clerk():
        async with _client() as client:
            body = (await client.get("/api/onboarding/v2/state", headers=AUTH)).json()
    assert body["repo"]["canCreate"] is True
    assert body["repo"]["ownerLogin"] == "octo-org"


@pytest.mark.asyncio
async def test_state_can_create_false_for_personal_install(tmp_db):
    org_id, _ = await _seed_org_and_team()
    await _seed_connection(org_id, account_type="User", login="octocat")
    with _patch_clerk():
        async with _client() as client:
            body = (await client.get("/api/onboarding/v2/state", headers=AUTH)).json()
    assert body["repo"]["canCreate"] is False
    assert body["repo"]["ownerLogin"] == "octocat"


@pytest.mark.asyncio
async def test_repo_create_succeeds_for_org_install(tmp_db):
    org_id, _ = await _seed_org_and_team()
    await _seed_connection(org_id, account_type="Organization", login="octo-org")
    fake = _fake_github_client("octo-org/new-repo")

    with _patch_clerk(), patch("src.routers.onboarding_v2.GithubClient", return_value=fake):
        async with _client() as client:
            resp = await client.post(
                "/api/onboarding/v2/repo/create",
                json={"name": "new-repo", "private": True},
                headers=AUTH,
            )
    assert resp.status_code == 200
    assert resp.json()["repo"]["selected"] == "octo-org/new-repo"
    fake.create_repo.assert_awaited_once_with("octo-org", "new-repo", True)


@pytest.mark.asyncio
async def test_repo_create_rejected_for_personal_install(tmp_db):
    """Personal-account installation tokens can't create repos — 422, and the
    GitHub client is never called."""
    org_id, _ = await _seed_org_and_team()
    await _seed_connection(org_id, account_type="User", login="octocat")

    with _patch_clerk():
        async with _client() as client:
            resp = await client.post(
                "/api/onboarding/v2/repo/create",
                json={"name": "new-repo", "private": True},
                headers=AUTH,
            )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "repo_create_requires_org_install"


@pytest.mark.asyncio
async def test_repo_create_409_without_connection(tmp_db):
    await _seed_org_and_team()
    with _patch_clerk():
        async with _client() as client:
            resp = await client.post(
                "/api/onboarding/v2/repo/create",
                json={"name": "new-repo", "private": True},
                headers=AUTH,
            )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_repo_create_rejects_invalid_name(tmp_db):
    org_id, _ = await _seed_org_and_team()
    await _seed_connection(org_id, account_type="Organization")
    with _patch_clerk():
        async with _client() as client:
            resp = await client.post(
                "/api/onboarding/v2/repo/create",
                json={"name": "bad name!", "private": True},
                headers=AUTH,
            )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_repo_create_404_when_flag_off(tmp_db):
    await _seed_org_and_team()
    with patch("src.config.Settings.is_feature_enabled", return_value=False):
        with _patch_clerk():
            async with _client() as client:
                resp = await client.post(
                    "/api/onboarding/v2/repo/create",
                    json={"name": "new-repo", "private": True},
                    headers=AUTH,
                )
    assert resp.status_code == 404
