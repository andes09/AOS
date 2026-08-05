"""
Router-level tests for drift: `GET /roadmap/drift` and `POST /roadmap/reconcile`.

The service's own signal logic is covered in test_roadmap_drift.py. What's
tested here is the wiring: ownership scoping, the feature-flag posture (the GET
degrades to an empty report rather than 404ing, so the banner can mount
unconditionally; the POST 404s, because acting is not something to do quietly
while disabled), and — most importantly — that reconcile routes through the
non-destructive adjuster and not through regenerate.
"""

import uuid
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient, ASGITransport

from src.config import settings
from src.main import app
from src.database import get_db
from src.models.organization import Organization
from src.models.team import Team
from src.models.onboarding_session import OnboardingSession
from src.models.project import Project
from src.models.milestone import Milestone
from src.models.task import Task, TaskStatus
from src.models.github_connection import GithubConnection

ORG = "org_drift_router"
AUTH = {"Authorization": "Bearer tok"}


def _patch_clerk(org_id=ORG):
    state = type("S", (), {"is_signed_in": True, "payload": {"sub": "user_drift", "org_id": org_id}})()
    return patch("src.auth._clerk.authenticate_request_async", new=AsyncMock(return_value=state))


def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _enable_flag(enabled: bool = True):
    real = type(settings).is_feature_enabled

    def fake(self, flag_name: str) -> bool:
        if flag_name == "experimental.roadmap_drift":
            return enabled
        return real(self, flag_name)

    return patch.object(type(settings), "is_feature_enabled", new=fake)


async def _seed(clerk_org_id=ORG, *, stalled=True, with_milestones=True, with_connection=True):
    ids = {k: uuid.uuid4() for k in ("org", "team", "session", "project", "milestone", "task")}
    async for db in app.dependency_overrides[get_db]():
        db.add(Organization(
            id=ids["org"], clerk_org_id=clerk_org_id, name="O", slug=clerk_org_id,
            use_managed_key=False,
        ))
        db.add(Team(id=ids["team"], organization_id=ids["org"], name="T"))
        db.add(OnboardingSession(id=ids["session"], organization_id=ids["org"], status="completed"))
        db.add(Project(
            id=ids["project"], team_id=ids["team"], onboarding_session_id=ids["session"],
            name="P", purpose="hobby", github_repo_full_name="octo/app",
        ))
        if with_connection:
            db.add(GithubConnection(
                id=uuid.uuid4(), organization_id=ids["org"], installation_id="9",
                github_user_id="1", github_login="octo", encrypted_access_token="e",
                is_active=True, created_at=datetime.utcnow() - timedelta(days=90),
            ))
        await db.flush()
        if with_milestones:
            db.add(Milestone(id=ids["milestone"], project_id=ids["project"], title="Auth", sort_order=0))
            await db.flush()
            db.add(Task(
                id=ids["task"], milestone_id=ids["milestone"], title="Add login",
                status=TaskStatus.TODO.value, sort_order=0,
                scheduled_date=(date.today() - timedelta(days=20)) if stalled else None,
            ))
        await db.commit()
    return ids


# ─── GET /drift ──────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_drift_reports_a_stalled_milestone(tmp_db):
    ids = await _seed()
    with _patch_clerk(), _enable_flag(True):
        async with _client() as client:
            resp = await client.get(f"/api/projects/{ids['project']}/roadmap/drift", headers=AUTH)

    assert resp.status_code == 200
    body = resp.json()
    assert body["hasDrift"] is True
    assert "stalled_milestone" in {s["kind"] for s in body["signals"]}


@pytest.mark.asyncio
async def test_drift_is_empty_not_404_while_the_flag_is_off(tmp_db):
    """The banner mounts unconditionally and self-gates, so a disabled flag has
    to look like "no drift", not like a broken endpoint."""
    ids = await _seed()
    with _patch_clerk(), _enable_flag(False):
        async with _client() as client:
            resp = await client.get(f"/api/projects/{ids['project']}/roadmap/drift", headers=AUTH)

    assert resp.status_code == 200
    assert resp.json() == {"hasDrift": False, "signals": [], "repoConnected": False}


@pytest.mark.asyncio
async def test_drift_404s_for_another_orgs_project(tmp_db):
    await _seed(clerk_org_id="org_drift_a")
    other = await _seed(clerk_org_id="org_drift_b")

    with _patch_clerk(org_id="org_drift_a"), _enable_flag(True):
        async with _client() as client:
            resp = await client.get(f"/api/projects/{other['project']}/roadmap/drift", headers=AUTH)

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_drift_requires_auth(tmp_db):
    ids = await _seed()
    async with _client() as client:
        resp = await client.get(f"/api/projects/{ids['project']}/roadmap/drift")
    assert resp.status_code in (401, 403)


# ─── POST /reconcile ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_reconcile_calls_the_adjuster_with_drift_evidence(tmp_db):
    ids = await _seed()
    adjust = AsyncMock()

    with (
        _patch_clerk(),
        _enable_flag(True),
        patch("src.services.roadmap_adjuster.adjust_roadmap", new=adjust),
        patch.object(settings, "groq_api_key", "k"),
    ):
        async with _client() as client:
            resp = await client.post(f"/api/projects/{ids['project']}/roadmap/reconcile", headers=AUTH)

    assert resp.status_code == 200
    assert adjust.await_count == 1
    evidence = adjust.await_args.kwargs["extra_context"]
    # The evidence handed to the planner has to be concrete, not a bare flag.
    assert "Auth" in evidence
    assert "stalled" in evidence.lower()


@pytest.mark.asyncio
async def test_reconcile_never_routes_through_regenerate(tmp_db):
    """The destructive path deletes every task in the project and resets
    statuses/assignees/completed_at. Reconcile must never reach it — that would
    destroy the very history the drift evidence is derived from."""
    ids = await _seed()

    with (
        _patch_clerk(),
        _enable_flag(True),
        patch("src.services.roadmap_adjuster.adjust_roadmap", new=AsyncMock()),
        patch("src.services.roadmap_generator.regenerate_roadmap", new=AsyncMock()) as regen,
        patch("src.services.roadmap_generator.regenerate_milestone", new=AsyncMock()) as regen_milestone,
        patch.object(settings, "groq_api_key", "k"),
    ):
        async with _client() as client:
            await client.post(f"/api/projects/{ids['project']}/roadmap/reconcile", headers=AUTH)

    assert regen.await_count == 0
    assert regen_milestone.await_count == 0


@pytest.mark.asyncio
async def test_reconcile_409s_when_there_is_no_drift(tmp_db):
    """No point paying for a model call to change nothing.

    Seeded with nothing scheduled and no GitHub connection, so neither the
    stalled-milestone nor the silent-repo signal has anything to say.
    """
    ids = await _seed(stalled=False, with_connection=False)
    adjust = AsyncMock()

    with (
        _patch_clerk(),
        _enable_flag(True),
        patch("src.services.roadmap_adjuster.adjust_roadmap", new=adjust),
        patch.object(settings, "groq_api_key", "k"),
    ):
        async with _client() as client:
            resp = await client.post(f"/api/projects/{ids['project']}/roadmap/reconcile", headers=AUTH)

    assert resp.status_code == 409
    assert resp.json()["detail"] == "no_drift"
    assert adjust.await_count == 0


@pytest.mark.asyncio
async def test_reconcile_409s_without_a_roadmap(tmp_db):
    ids = await _seed(with_milestones=False)
    with _patch_clerk(), _enable_flag(True):
        async with _client() as client:
            resp = await client.post(f"/api/projects/{ids['project']}/roadmap/reconcile", headers=AUTH)

    assert resp.status_code == 409
    assert resp.json()["detail"] == "no_roadmap"


@pytest.mark.asyncio
async def test_reconcile_404s_while_the_flag_is_off(tmp_db):
    """Unlike the GET, acting is not something to do quietly while disabled."""
    ids = await _seed()
    with _patch_clerk(), _enable_flag(False):
        async with _client() as client:
            resp = await client.post(f"/api/projects/{ids['project']}/roadmap/reconcile", headers=AUTH)

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_reconcile_404s_for_another_orgs_project(tmp_db):
    await _seed(clerk_org_id="org_recon_a")
    other = await _seed(clerk_org_id="org_recon_b")

    with _patch_clerk(org_id="org_recon_a"), _enable_flag(True):
        async with _client() as client:
            resp = await client.post(f"/api/projects/{other['project']}/roadmap/reconcile", headers=AUTH)

    assert resp.status_code == 404
