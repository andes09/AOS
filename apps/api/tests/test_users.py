import sqlite3
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from httpx import AsyncClient, ASGITransport

from src.database import Base, get_db
from src.main import app

# users.py's raw-SQL cleanup (_wipe_team_data, org teardown) binds team_id/org_id as
# Python uuid.UUID objects. asyncpg adapts these natively in production; stdlib sqlite3
# doesn't, so register an adapter for this test's in-memory SQLite engine. Must match
# SQLAlchemy's own emulated-UUID bind format on non-native dialects (32-char hex, no
# dashes — see sqlalchemy.sql.sqltypes.Uuid.bind_processor) or ORM-written rows (dashless
# hex) won't match raw text() DELETE ... WHERE id = :param comparisons (dashed str()).
sqlite3.register_adapter(uuid.UUID, lambda u: u.hex)

ORG = "org_users_test"
USER = "user_users_test"

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


def _patch_clerk(user_id=USER, org_id=ORG):
    payload = {"sub": user_id, "org_id": org_id}
    state = type("S", (), {"is_signed_in": True, "payload": payload})()
    return patch("src.auth._clerk.authenticate_request_async", new=AsyncMock(return_value=state))


def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


AUTH = {"Authorization": "Bearer tok"}


@pytest.fixture
async def fk_enforced_db():
    """Same as conftest's tmp_db, but with SQLite FK enforcement turned on.

    Plain SQLite silently ignores FK violations, which would let this test
    pass even without the fix. Enabling the pragma makes the missing
    onboarding_sessions/github_connections cleanup raise an IntegrityError,
    the same failure mode Postgres produces in production.
    """
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_fk(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db():
        async with Session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.pop(get_db, None)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


async def _seed_org_team_developer(clerk_org_id=ORG, clerk_user_id=USER):
    from src.models.organization import Organization
    from src.models.team import Team
    from src.models.developer import Developer

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
        await db.flush()
        developer = Developer(
            id=uuid.uuid4(),
            team_id=team.id,
            clerk_user_id=clerk_user_id,
            name="Test Dev",
            app_role="admin",
        )
        db.add(developer)
        await db.commit()
        return org.id, team.id, developer.id


async def _seed_onboarding_and_github(org_id):
    from src.models.onboarding_session import OnboardingSession
    from src.models.github_connection import GithubConnection
    from src.services.encryption import encrypt

    async for db in app.dependency_overrides[get_db]():
        db.add(OnboardingSession(organization_id=org_id))
        db.add(GithubConnection(
            organization_id=org_id,
            github_user_id="42",
            github_login="octocat",
            encrypted_access_token=encrypt("tok"),
        ))
        await db.commit()
        break


@pytest.mark.asyncio
async def test_delete_account_wipes_onboarding_and_github_rows(fk_enforced_db):
    org_id, _, _ = await _seed_org_team_developer()
    await _seed_onboarding_and_github(org_id)

    with _patch_clerk(), patch("src.auth._clerk.users.delete_async", new=AsyncMock()):
        async with _client() as client:
            resp = await client.delete("/api/users/me", headers=AUTH)

    assert resp.status_code == 200
    assert resp.json() == {"deleted": True}

    from src.models.organization import Organization
    from src.models.onboarding_session import OnboardingSession
    from src.models.github_connection import GithubConnection

    async for db in app.dependency_overrides[get_db]():
        assert (await db.scalar(select(Organization).where(Organization.id == org_id))) is None
        assert (
            await db.scalar(select(OnboardingSession).where(OnboardingSession.organization_id == org_id))
        ) is None
        assert (
            await db.scalar(select(GithubConnection).where(GithubConnection.organization_id == org_id))
        ) is None
        break
