import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch
from src.main import app


def _patch_clerk(org_id="org_abc", org_slug="my-org"):
    payload = {"sub": "user_1", "org_id": org_id, "org_slug": org_slug}
    state = type("S", (), {"is_signed_in": True, "payload": payload})()
    return patch("src.auth._clerk.authenticate_request_async", new=AsyncMock(return_value=state))


@pytest.mark.asyncio
async def test_provision_org_creates_org_and_team(tmp_db):
    """First call creates org + default team, returns 201."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with _patch_clerk():
            resp = await client.post(
                "/api/organizations",
                json={"name": "My Org"},
                headers={"Authorization": "Bearer tok"},
            )
    assert resp.status_code == 201
    body = resp.json()
    assert body["orgId"]
    assert body["teamId"]
    assert body["isNew"] is True


@pytest.mark.asyncio
async def test_provision_org_is_idempotent(tmp_db):
    """Second call for the same clerk_org_id returns 200 with isNew=False."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with _patch_clerk():
            await client.post(
                "/api/organizations",
                json={"name": "My Org"},
                headers={"Authorization": "Bearer tok"},
            )
            resp = await client.post(
                "/api/organizations",
                json={"name": "My Org"},
                headers={"Authorization": "Bearer tok"},
            )
    assert resp.status_code == 200
    assert resp.json()["isNew"] is False


@pytest.mark.asyncio
async def test_provision_org_requires_auth():
    """No token → 403."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/organizations", json={"name": "X"})
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_provision_org_requires_org_context(tmp_db):
    """Token without org_id claim → 403."""
    payload = {"sub": "user_1"}  # no org_id
    state = type("S", (), {"is_signed_in": True, "payload": payload})()
    with patch("src.auth._clerk.authenticate_request_async", new=AsyncMock(return_value=state)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/organizations",
                json={"name": "X"},
                headers={"Authorization": "Bearer tok"},
            )
    assert resp.status_code == 403
