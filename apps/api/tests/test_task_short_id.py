"""
Tests for Task.short_id allocation (src/services/task_ids.py) and its wiring
into the roadmap router's quick-add endpoint — see
docs/plans/2026-07-20-github-task-autocomplete.md.
"""

import uuid

import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch

from src.main import app
from src.database import get_db
from src.models.organization import Organization
from src.models.team import Team
from src.models.onboarding_session import OnboardingSession
from src.models.project import Project
from src.models.milestone import Milestone

ORG = "org_short_id_test"
USER = "user_short_id"
AUTH = {"Authorization": "Bearer tok"}


def _patch_clerk(user_id=USER, org_id=ORG):
    payload = {"sub": user_id, "org_id": org_id}
    state = type("S", (), {"is_signed_in": True, "payload": payload})()
    return patch("src.auth._clerk.authenticate_request_async", new=AsyncMock(return_value=state))


def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _seed_project(clerk_org_id=ORG, slug=None):
    org_id, team_id, session_id, project_id, milestone_id = (
        uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    )
    async for db in app.dependency_overrides[get_db]():
        db.add(Organization(
            id=org_id, clerk_org_id=clerk_org_id, name="Test Org",
            slug=slug or clerk_org_id, use_managed_key=False,
        ))
        db.add(Team(id=team_id, organization_id=org_id, name="Default"))
        db.add(OnboardingSession(
            id=session_id, organization_id=org_id, status="completed",
        ))
        db.add(Project(
            id=project_id, team_id=team_id, onboarding_session_id=session_id,
            name="Seeded", purpose="hobby",
        ))
        await db.flush()
        db.add(Milestone(id=milestone_id, project_id=project_id, title="M0", sort_order=0))
        await db.commit()
        return org_id, project_id, milestone_id


@pytest.mark.asyncio
async def test_create_task_assigns_short_id(tmp_db):
    org_id, project_id, _ = await _seed_project(slug="aos-test")
    with _patch_clerk():
        async with _client() as client:
            resp = await client.post(
                f"/api/projects/{project_id}/roadmap/tasks",
                json={"title": "Wire up billing"},
                headers=AUTH,
            )
    assert resp.status_code == 201
    body = resp.json()
    assert body["shortId"] is not None
    assert body["shortId"].startswith("AOSTEST-")


@pytest.mark.asyncio
async def test_create_task_short_ids_increment_and_never_collide(tmp_db):
    org_id, project_id, _ = await _seed_project(slug="aos-test")
    with _patch_clerk():
        async with _client() as client:
            first = await client.post(
                f"/api/projects/{project_id}/roadmap/tasks",
                json={"title": "First"},
                headers=AUTH,
            )
            second = await client.post(
                f"/api/projects/{project_id}/roadmap/tasks",
                json={"title": "Second"},
                headers=AUTH,
            )
    first_id, second_id = first.json()["shortId"], second.json()["shortId"]
    assert first_id != second_id
    first_seq = int(first_id.rsplit("-", 1)[1])
    second_seq = int(second_id.rsplit("-", 1)[1])
    assert second_seq == first_seq + 1


@pytest.mark.asyncio
async def test_short_id_prefix_falls_back_to_task_for_non_alnum_slug(tmp_db):
    # Org slugs are validated at creation time in the real app, but the
    # prefix derivation must still degrade gracefully rather than emit a
    # short_id with an empty prefix like "-1".
    org_id, project_id, _ = await _seed_project(clerk_org_id="org_weird", slug="---")
    with _patch_clerk(org_id="org_weird"):
        async with _client() as client:
            resp = await client.post(
                f"/api/projects/{project_id}/roadmap/tasks",
                json={"title": "Task"},
                headers=AUTH,
            )
    assert resp.json()["shortId"] == "TASK-1"


@pytest.mark.asyncio
async def test_organization_next_task_seq_advances(tmp_db):
    org_id, project_id, _ = await _seed_project(slug="aos-test")
    with _patch_clerk():
        async with _client() as client:
            await client.post(
                f"/api/projects/{project_id}/roadmap/tasks", json={"title": "A"}, headers=AUTH,
            )
            await client.post(
                f"/api/projects/{project_id}/roadmap/tasks", json={"title": "B"}, headers=AUTH,
            )

    from sqlalchemy import select

    async for db in app.dependency_overrides[get_db]():
        org = await db.scalar(select(Organization).where(Organization.id == org_id))
        assert org.next_task_seq == 2
        break


@pytest.mark.asyncio
async def test_allocate_short_ids_batch_is_contiguous_and_atomic():
    """Unit-level check of the batch-reservation helper itself: `count`
    short_ids reserved in one call must be contiguous and must advance
    next_task_seq by exactly `count`."""
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from src.database import Base
    from src.services.task_ids import allocate_short_ids

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: Organization.__table__.create(sync_conn, checkfirst=True)
        )
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as db:
        org = Organization(
            id=uuid.uuid4(), clerk_org_id="c1", name="Org", slug="myorg", use_managed_key=False,
        )
        db.add(org)
        await db.commit()

        ids = await allocate_short_ids(org, 3, db)
        assert ids == ["MYORG-1", "MYORG-2", "MYORG-3"]
        assert org.next_task_seq == 3

        more = await allocate_short_ids(org, 2, db)
        assert more == ["MYORG-4", "MYORG-5"]
        assert org.next_task_seq == 5
    await engine.dispose()
