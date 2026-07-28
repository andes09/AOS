"""
Tests for the Import Artifacts feature (artifact_import.py) — analyzing a
pasted/uploaded plan into a project brief + proposed roadmap, and applying an
accepted subset of that roadmap into real Project/Milestone/Task rows.

Groq is faked the same way test_roadmap_generator.py/test_projects.py do it
(the client is instantiated in roadmap_generator.py, which is where
artifact_import.py's `_call_planner` call actually lives).
"""

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.config import settings
from src.main import app

ORG = "org_import_test"
USER = "user_import"
AUTH = {"Authorization": "Bearer tok"}


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
            id=uuid.uuid4(), clerk_org_id=clerk_org_id, name="Test Org", slug=clerk_org_id,
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


class _FakeToolCall:
    def __init__(self, name, payload):
        self.function = SimpleNamespace(name=name, arguments=json.dumps(payload))


def _fake_groq(payload, tool_name="analyze_project_artifact"):
    tool_calls = [_FakeToolCall(tool_name, payload)]
    message = SimpleNamespace(tool_calls=tool_calls)
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=message)],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=200),
    )
    fake_completions = SimpleNamespace(create=AsyncMock(return_value=response))
    return SimpleNamespace(chat=SimpleNamespace(completions=fake_completions))


def _patch_groq(fake):
    return patch("src.services.roadmap_generator.AsyncOpenAI", return_value=fake)


def _patch_api_key():
    return patch("src.services.idea_interview.resolve_api_key", new=AsyncMock(return_value="sk-test"))


def _enable_flag(enabled: bool = True):
    """Override settings.is_feature_enabled('experimental.import_artifacts').

    Patches the class method (Settings is a frozen Pydantic model, so
    instance-level patch.object on the instance raises AttributeError) — same
    idiom as test_teams_create.py's `_enable_flag`.
    """
    real = type(settings).is_feature_enabled

    def fake(self, flag_name: str) -> bool:
        if flag_name == "experimental.import_artifacts":
            return enabled
        return real(self, flag_name)

    return patch.object(type(settings), "is_feature_enabled", new=fake)


_ANALYSIS_PAYLOAD = {
    "projectName": "Trail Buddy",
    "problemStatement": "Hikers lose track of trail conditions",
    "targetAudience": "Weekend hikers",
    "coreFeatures": ["Trail status feed", "Offline maps"],
    "summary": "Two weeks to a hikeable MVP.",
    "milestones": [
        {
            "title": "Foundations",
            "description": "Set up the skeleton",
            "tasks": [
                {"title": "Init repo", "dayOffset": 0},
                {"title": "Pick stack", "description": "Keep it boring", "dayOffset": 1, "parallel": True},
            ],
        },
        {
            "title": "Core loop",
            "tasks": [{"title": "Build map view", "dayOffset": 3, "startTime": "09:30", "durationMinutes": 60}],
        },
    ],
}


# ─── feature flag gate ──────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_router_404s_when_flag_disabled(tmp_db):
    await _seed_org_and_team()
    with _enable_flag(False), _patch_clerk():
        async with _client() as client:
            resp = await client.get("/api/onboarding/v2/import", headers=AUTH)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_router_reachable_when_flag_enabled(tmp_db):
    await _seed_org_and_team()
    with _enable_flag(True), _patch_clerk():
        async with _client() as client:
            resp = await client.get("/api/onboarding/v2/import", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["analyzed"] is False


# ─── analyze: pasted text ───────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_analyze_from_pasted_text(tmp_db):
    await _seed_org_and_team()
    fake = _fake_groq(_ANALYSIS_PAYLOAD)
    with _patch_clerk(), _patch_groq(fake), _patch_api_key():
        async with _client() as client:
            resp = await client.post(
                "/api/onboarding/v2/import/analyze",
                data={"text": "We are building Trail Buddy, an app for hikers..."},
                headers=AUTH,
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body["analyzed"] is True
    assert body["projectName"] == "Trail Buddy"
    assert body["summary"] == "Two weeks to a hikeable MVP."
    assert len(body["milestones"]) == 2
    assert body["milestones"][0]["title"] == "Foundations"
    assert body["milestones"][1]["tasks"][0]["startTime"] == "09:30"
    assert body["truncated"] is False
    # missingFields reflects the brief merged from the analysis (scope/timeline
    # weren't in the payload, so they should still be reported missing).
    assert "scope" in body["missingFields"]

    # GET /import returns the same persisted result afterwards.
    with _patch_clerk():
        async with _client() as client:
            resp = await client.get("/api/onboarding/v2/import", headers=AUTH)
    assert resp.json()["analyzed"] is True
    assert resp.json()["projectName"] == "Trail Buddy"


@pytest.mark.asyncio
async def test_analyze_requires_some_content(tmp_db):
    await _seed_org_and_team()
    with _patch_clerk():
        async with _client() as client:
            resp = await client.post("/api/onboarding/v2/import/analyze", data={}, headers=AUTH)
    assert resp.status_code == 422


# ─── analyze: file types ────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_analyze_from_txt_file(tmp_db):
    await _seed_org_and_team()
    fake = _fake_groq(_ANALYSIS_PAYLOAD)
    with _patch_clerk(), _patch_groq(fake), _patch_api_key():
        async with _client() as client:
            resp = await client.post(
                "/api/onboarding/v2/import/analyze",
                files={"files": ("plan.txt", b"Our plan for Trail Buddy...", "text/plain")},
                headers=AUTH,
            )
    assert resp.status_code == 200
    assert resp.json()["analyzed"] is True


@pytest.mark.asyncio
async def test_analyze_from_markdown_file(tmp_db):
    await _seed_org_and_team()
    fake = _fake_groq(_ANALYSIS_PAYLOAD)
    with _patch_clerk(), _patch_groq(fake), _patch_api_key():
        async with _client() as client:
            resp = await client.post(
                "/api/onboarding/v2/import/analyze",
                files={"files": ("plan.md", b"# Trail Buddy\n\nA hiking app.", "text/markdown")},
                headers=AUTH,
            )
    assert resp.status_code == 200
    assert resp.json()["analyzed"] is True


@pytest.mark.asyncio
async def test_analyze_from_pdf_file(tmp_db):
    await _seed_org_and_team()
    fake = _fake_groq(_ANALYSIS_PAYLOAD)
    fake_page = SimpleNamespace(extract_text=lambda: "Our plan for Trail Buddy, a hiking app.")
    fake_reader = SimpleNamespace(pages=[fake_page])
    with (
        _patch_clerk(),
        _patch_groq(fake),
        _patch_api_key(),
        patch("pypdf.PdfReader", return_value=fake_reader),
    ):
        async with _client() as client:
            resp = await client.post(
                "/api/onboarding/v2/import/analyze",
                files={"files": ("plan.pdf", b"%PDF-1.4 fake bytes", "application/pdf")},
                headers=AUTH,
            )
    assert resp.status_code == 200
    assert resp.json()["analyzed"] is True


@pytest.mark.asyncio
async def test_analyze_pdf_with_no_extractable_text_422s(tmp_db):
    """A scanned/image-only PDF yields ~0 extracted chars — 422 with a clear
    message instead of sending near-empty content to the model."""
    await _seed_org_and_team()
    fake_page = SimpleNamespace(extract_text=lambda: "")
    fake_reader = SimpleNamespace(pages=[fake_page])
    with _patch_clerk(), patch("pypdf.PdfReader", return_value=fake_reader):
        async with _client() as client:
            resp = await client.post(
                "/api/onboarding/v2/import/analyze",
                files={"files": ("scanned.pdf", b"%PDF-1.4 fake bytes", "application/pdf")},
                headers=AUTH,
            )
    assert resp.status_code == 422
    assert "couldn't extract" in resp.json()["detail"].lower() or "scanned" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_analyze_from_docx_file(tmp_db):
    await _seed_org_and_team()
    fake = _fake_groq(_ANALYSIS_PAYLOAD)
    fake_paragraph = SimpleNamespace(text="Our plan for Trail Buddy, a hiking app.")
    fake_document = SimpleNamespace(paragraphs=[fake_paragraph])
    with (
        _patch_clerk(),
        _patch_groq(fake),
        _patch_api_key(),
        patch("docx.Document", return_value=fake_document),
    ):
        async with _client() as client:
            resp = await client.post(
                "/api/onboarding/v2/import/analyze",
                files={
                    "files": (
                        "plan.docx",
                        b"fake docx bytes",
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    )
                },
                headers=AUTH,
            )
    assert resp.status_code == 200
    assert resp.json()["analyzed"] is True


# ─── analyze: rejections ────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_analyze_rejects_unsupported_content_type(tmp_db):
    await _seed_org_and_team()
    with _patch_clerk():
        async with _client() as client:
            resp = await client.post(
                "/api/onboarding/v2/import/analyze",
                files={"files": ("plan.png", b"\x89PNG\r\n", "image/png")},
                headers=AUTH,
            )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_analyze_rejects_oversized_file(tmp_db):
    await _seed_org_and_team()
    oversized = b"x" * (10 * 1024 * 1024 + 1)
    with _patch_clerk():
        async with _client() as client:
            resp = await client.post(
                "/api/onboarding/v2/import/analyze",
                files={"files": ("plan.txt", oversized, "text/plain")},
                headers=AUTH,
            )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_analyze_rejects_too_many_files(tmp_db):
    await _seed_org_and_team()
    files = [("files", (f"plan{i}.txt", b"some text", "text/plain")) for i in range(6)]
    with _patch_clerk():
        async with _client() as client:
            resp = await client.post("/api/onboarding/v2/import/analyze", files=files, headers=AUTH)
    assert resp.status_code == 422


# ─── apply ───────────────────────────────────────────────────────────────────────
async def _analyze(client, payload=_ANALYSIS_PAYLOAD):
    fake = _fake_groq(payload)
    with _patch_groq(fake), _patch_api_key():
        resp = await client.post(
            "/api/onboarding/v2/import/analyze", data={"text": "some plan text"}, headers=AUTH
        )
    assert resp.status_code == 200
    return resp.json()


@pytest.mark.asyncio
async def test_apply_requires_prior_analysis(tmp_db):
    await _seed_org_and_team()
    with _patch_clerk():
        async with _client() as client:
            resp = await client.post(
                "/api/onboarding/v2/import/apply",
                json={"acceptedMilestoneIndexes": [0]},
                headers=AUTH,
            )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "no_proposed_roadmap"


@pytest.mark.asyncio
async def test_apply_requires_nonempty_accepted_indexes(tmp_db):
    await _seed_org_and_team()
    with _patch_clerk():
        async with _client() as client:
            await _analyze(client)
            resp = await client.post(
                "/api/onboarding/v2/import/apply",
                json={"acceptedMilestoneIndexes": []},
                headers=AUTH,
            )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_apply_creates_only_accepted_milestones(tmp_db):
    org_id, team_id = await _seed_org_and_team()
    with _patch_clerk():
        async with _client() as client:
            await _analyze(client)
            # Reject milestone 0 ("Foundations"), accept only milestone 1 ("Core loop").
            resp = await client.post(
                "/api/onboarding/v2/import/apply",
                json={"acceptedMilestoneIndexes": [1]},
                headers=AUTH,
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ideaChat"]["status"] == "completed"

    from sqlalchemy import select
    from src.database import get_db
    from src.models.milestone import Milestone
    from src.models.project import Project
    from src.models.task import Task

    async for db in app.dependency_overrides[get_db]():
        project = await db.scalar(select(Project).where(Project.team_id == team_id))
        assert project is not None
        assert project.name == "Trail Buddy"

        milestones = (
            await db.execute(select(Milestone).where(Milestone.project_id == project.id))
        ).scalars().all()
        assert len(milestones) == 1
        assert milestones[0].title == "Core loop"

        tasks = (
            await db.execute(select(Task).where(Task.milestone_id == milestones[0].id))
        ).scalars().all()
        assert len(tasks) == 1
        assert tasks[0].title == "Build map view"
        assert tasks[0].duration_minutes == 60
        assert tasks[0].scheduled_time is not None
        assert tasks[0].scheduled_time.strftime("%H:%M") == "09:30"
        break


@pytest.mark.asyncio
async def test_apply_with_brief_overrides_fills_missing_fields(tmp_db):
    await _seed_org_and_team()
    with _patch_clerk():
        async with _client() as client:
            analyzed = await _analyze(client)
            assert "scope" in analyzed["missingFields"]

            resp = await client.post(
                "/api/onboarding/v2/import/apply",
                json={
                    "acceptedMilestoneIndexes": [0, 1],
                    "briefOverrides": {"scope": "MVP: trail status feed only", "timeline": "3 weeks"},
                },
                headers=AUTH,
            )
    assert resp.status_code == 200
    assert resp.json()["ideaChat"]["brief"]["scope"] == "MVP: trail status feed only"
    assert resp.json()["ideaChat"]["brief"]["timeline"] == "3 weeks"


@pytest.mark.asyncio
async def test_apply_out_of_range_indexes_ignored_but_needs_at_least_one_valid(tmp_db):
    await _seed_org_and_team()
    with _patch_clerk():
        async with _client() as client:
            await _analyze(client)
            resp = await client.post(
                "/api/onboarding/v2/import/apply",
                json={"acceptedMilestoneIndexes": [99]},
                headers=AUTH,
            )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_repo_select_before_and_after_apply(tmp_db):
    """Repo selection before the import Project exists only stashes the value
    on the session; once /apply has run, PUT /repo stamps the Project too
    (mirrors the equivalent onboarding_v2.py-level test)."""
    await _seed_org_and_team()
    with _patch_clerk():
        async with _client() as client:
            # Before analysis/apply: no Project exists yet.
            resp = await client.put(
                "/api/onboarding/v2/repo", json={"repoFullName": "octocat/hello-world"}, headers=AUTH
            )
            assert resp.json()["repo"]["selected"] == "octocat/hello-world"

            await _analyze(client)
            apply_resp = await client.post(
                "/api/onboarding/v2/import/apply",
                json={"acceptedMilestoneIndexes": [0]},
                headers=AUTH,
            )
            assert apply_resp.status_code == 200

    from sqlalchemy import select
    from src.database import get_db
    from src.models.project import Project

    async for db in app.dependency_overrides[get_db]():
        project = await db.scalar(select(Project))
        # /apply itself copies session.selected_github_repo_full_name onto the
        # new Project defensively, even though repo-select normally comes
        # after build_plan in the step order.
        assert project.github_repo_full_name == "octocat/hello-world"
        break

    with _patch_clerk():
        async with _client() as client:
            # Now that the Project exists, PUT /repo again must stamp it too.
            resp = await client.put(
                "/api/onboarding/v2/repo", json={"repoFullName": "octocat/other-repo"}, headers=AUTH
            )
            assert resp.json()["repo"]["selected"] == "octocat/other-repo"

    async for db in app.dependency_overrides[get_db]():
        project = await db.scalar(select(Project))
        assert project.github_repo_full_name == "octocat/other-repo"
        break
