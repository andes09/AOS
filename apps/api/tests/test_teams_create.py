"""Tests for POST /api/teams.

Covers the M5 "per-team Jira project + Omada team management" contract used
by the omada-simulator stage-2 matrix.

We deliberately do NOT reuse the shared ``tmp_db`` fixture from
``tests/conftest.py``: it creates every table in ``Base.metadata`` which
fails under SQLite because several unrelated tables use Postgres-specific
``JSONB`` columns. These tests only need 4 simple tables, so we build a
local async-SQLite engine that creates exactly those.
"""
import uuid
from contextlib import contextmanager
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.auth import get_current_org_id, get_current_user_id
from src.config import settings
from src.database import Base, get_db
from src.main import app
from src.models.developer import Developer
from src.models.organization import Organization
from src.models.team import Team
from src.models.team_access import TeamAccessGrant


# Tables this suite needs (avoids JSONB tables that break SQLite).
_REQUIRED_TABLES = [
    Organization.__table__,
    Team.__table__,
    Developer.__table__,
    TeamAccessGrant.__table__,
]


@pytest_asyncio.fixture
async def teams_db():
    """Async-SQLite engine with only the tables this suite needs."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: Base.metadata.create_all(
            sync_conn, tables=_REQUIRED_TABLES
        ))

    Session = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db():
        async with Session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.pop(get_db, None)
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: Base.metadata.drop_all(
            sync_conn, tables=_REQUIRED_TABLES
        ))
    await engine.dispose()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@contextmanager
def _as_user(org_id: str = "org_abc", user_id: str = "user_1"):
    """Override the FastAPI auth deps so requests act as ``user_id`` in ``org_id``.

    This avoids tripping over the local ``clerk_auth`` flag path that would
    otherwise require seeding an admin Developer row.
    """
    app.dependency_overrides[get_current_org_id] = lambda: org_id
    app.dependency_overrides[get_current_user_id] = lambda: user_id
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_current_org_id, None)
        app.dependency_overrides.pop(get_current_user_id, None)


async def _seed_org(clerk_org_id: str, name: str = "My Org") -> uuid.UUID:
    """Create an Organization row via the test session and return its id."""
    org_id = uuid.uuid4()
    async for db in app.dependency_overrides[get_db]():
        db.add(Organization(
            id=org_id,
            clerk_org_id=clerk_org_id,
            name=name,
            slug=clerk_org_id,
            use_managed_key=False,
        ))
        await db.commit()
        break
    return org_id


def _enable_flag(enabled: bool = True):
    """Override settings.is_feature_enabled('allow_team_creation_via_api').

    Patches the class method (BaseSettings is a frozen Pydantic model, so
    instance-level patching via ``patch.object`` raises AttributeError).
    """
    real = type(settings).is_feature_enabled

    def fake(self, flag_name: str) -> bool:
        if flag_name == "allow_team_creation_via_api":
            return enabled
        return real(self, flag_name)

    return patch.object(type(settings), "is_feature_enabled", new=fake)


# ---------------------------------------------------------------------------
# POST /api/teams
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_team_when_feature_disabled_returns_403(teams_db):
    await _seed_org("org_abc")
    with _enable_flag(False), _as_user():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/teams",
                json={
                    "name": "Sim BAL OMAD",
                    "developers": [{"name": "Alex", "role": "engineer"}],
                },
                headers={"Authorization": "Bearer tok"},
            )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Team creation via API is disabled in this environment."


@pytest.mark.asyncio
async def test_create_team_succeeds_when_feature_enabled(teams_db):
    await _seed_org("org_abc")
    with _enable_flag(True), _as_user():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/teams",
                json={
                    "name": "Sim BAL OMAD",
                    "developers": [
                        {"name": "Alex", "role": "engineer"},
                        {"name": "Jordan", "role": "engineer"},
                    ],
                },
                headers={"Authorization": "Bearer tok"},
            )
    assert resp.status_code == 201
    body = resp.json()
    assert body["teamId"]
    assert body["name"] == "Sim BAL OMAD"
    assert body["isNew"] is True
    assert len(body["developers"]) == 2
    names = sorted(d["name"] for d in body["developers"])
    assert names == ["Alex", "Jordan"]
    for d in body["developers"]:
        assert d["developerId"]


@pytest.mark.asyncio
async def test_create_team_idempotent_on_name(teams_db):
    await _seed_org("org_abc")
    body_json = {
        "name": "Sim BAL OMAD",
        "developers": [{"name": "Alex", "role": "engineer"}],
    }
    with _enable_flag(True), _as_user():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            first = await client.post(
                "/api/teams", json=body_json, headers={"Authorization": "Bearer tok"}
            )
            second = await client.post(
                "/api/teams", json=body_json, headers={"Authorization": "Bearer tok"}
            )
    assert first.status_code == 201
    assert first.json()["isNew"] is True
    assert second.status_code == 200
    assert second.json()["isNew"] is False
    assert second.json()["teamId"] == first.json()["teamId"]


@pytest.mark.asyncio
async def test_create_team_idempotent_on_developer_names(teams_db):
    await _seed_org("org_abc")
    body_json = {
        "name": "Sim BAL OMAD",
        "developers": [
            {"name": "Alex", "role": "engineer"},
            {"name": "Jordan", "role": "engineer"},
        ],
    }
    with _enable_flag(True), _as_user():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            first = await client.post(
                "/api/teams", json=body_json, headers={"Authorization": "Bearer tok"}
            )
            second = await client.post(
                "/api/teams", json=body_json, headers={"Authorization": "Bearer tok"}
            )

    team_id = uuid.UUID(first.json()["teamId"])
    async for db in app.dependency_overrides[get_db]():
        rows = (await db.scalars(
            select(Developer).where(Developer.team_id == team_id)
        )).all()
        break
    assert len(rows) == 2
    # Same developer IDs across both responses.
    first_dev_ids = sorted(d["developerId"] for d in first.json()["developers"])
    second_dev_ids = sorted(d["developerId"] for d in second.json()["developers"])
    assert first_dev_ids == second_dev_ids
