import uuid
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
    assert [s["status"] for s in body["steps"]] == ["current", "pending", "pending", "pending"]
    assert [s["id"] for s in body["steps"]] == ["github_connect", "profile", "purpose", "idea_chat"]
    assert body["github"] == {"connected": False, "login": None, "skipped": False}
    assert body["profile"] == {"name": None, "phone": None, "complete": False}
    assert body["purpose"] == {"value": None, "complete": False}
    assert body["ideaChat"]["status"] == "not_started"
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
    assert [s["status"] for s in body["steps"]] == ["complete", "current", "pending", "pending"]


@pytest.mark.asyncio
async def test_github_connection_completes_step(tmp_db):
    org_id, _ = await _seed_org_and_team()

    from src.database import get_db
    from src.models.github_connection import GithubConnection
    from src.services.encryption import encrypt

    async for db in app.dependency_overrides[get_db]():
        db.add(GithubConnection(
            organization_id=org_id,
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
    assert body["currentStep"] == "profile"


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
    assert body["currentStep"] == "idea_chat"
    assert [s["status"] for s in body["steps"]] == ["complete", "complete", "complete", "current"]


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
