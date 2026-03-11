import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from src.main import app


@pytest.mark.asyncio
async def test_protected_route_requires_auth():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_health_does_not_require_auth():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_get_current_org_id_returns_org_id():
    from src.auth import get_current_org_id
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="valid-token")
    with patch("src.auth.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get = AsyncMock(return_value=MagicMock(
            status_code=200,
            json=lambda: {"sub": "user_abc", "org_id": "org_clerk_123"},
        ))
        result = await get_current_org_id(credentials)
    assert result == "org_clerk_123"


@pytest.mark.asyncio
async def test_get_current_org_id_raises_403_when_no_org_in_token():
    from src.auth import get_current_org_id
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="personal-token")
    with patch("src.auth.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get = AsyncMock(return_value=MagicMock(
            status_code=200,
            json=lambda: {"sub": "user_abc"},  # no org_id
        ))
        with pytest.raises(HTTPException) as exc_info:
            await get_current_org_id(credentials)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_get_current_org_id_raises_401_on_bad_token():
    from src.auth import get_current_org_id
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="bad-token")
    with patch("src.auth.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get = AsyncMock(return_value=MagicMock(
            status_code=401,
            json=lambda: {},
        ))
        with pytest.raises(HTTPException) as exc_info:
            await get_current_org_id(credentials)
    assert exc_info.value.status_code == 401
