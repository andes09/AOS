import uuid
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient, ASGITransport

from src.main import app


def _patch_clerk(user_id="user_1", org_id="org_abc"):
    payload = {"sub": user_id, "org_id": org_id}
    state = type("S", (), {"is_signed_in": True, "payload": payload})()
    return patch("src.auth._clerk.authenticate_request_async", new=AsyncMock(return_value=state))


async def _seed_org(clerk_org_id="org_gh_test"):
    from src.database import get_db
    from src.models.organization import Organization

    async for db in app.dependency_overrides[get_db]():
        org = Organization(
            id=uuid.uuid4(),
            clerk_org_id=clerk_org_id,
            name="Test Org",
            slug=clerk_org_id,
            use_managed_key=False,
        )
        db.add(org)
        await db.commit()
        return org.id


async def _seed_state(clerk_org_id, state="gh_state_token", minutes=10):
    from src.database import get_db
    from src.models.oauth_state import OAuthState

    async for db in app.dependency_overrides[get_db]():
        db.add(OAuthState(
            state=state,
            user_id="user_1",
            org_id=clerk_org_id,
            return_to="/onboarding",
            expires_at=datetime.utcnow() + timedelta(minutes=minutes),
        ))
        await db.commit()
        break


@pytest.mark.asyncio
async def test_github_connect_requires_auth(tmp_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/integrations/github/connect")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_github_connect_returns_auth_url(tmp_db):
    with _patch_clerk():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/integrations/github/connect",
                headers={"Authorization": "Bearer tok"},
            )
    assert resp.status_code == 200
    assert "github.com/login/oauth/authorize" in resp.json()["auth_url"]


@pytest.mark.asyncio
async def test_github_callback_invalid_state(tmp_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            "/api/integrations/github/callback",
            params={"code": "abc", "state": "nope"},
        )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_github_callback_expired_state(tmp_db):
    clerk_org_id = "org_gh_test"
    await _seed_org(clerk_org_id)
    await _seed_state(clerk_org_id, state="expired_state", minutes=-5)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            "/api/integrations/github/callback",
            params={"code": "abc", "state": "expired_state"},
        )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_github_callback_saves_connection_encrypted(tmp_db):
    clerk_org_id = "org_gh_test"
    org_id = await _seed_org(clerk_org_id)
    await _seed_state(clerk_org_id)

    mock_tokens = {"access_token": "gho_secret", "scope": "repo,read:user"}
    mock_user = {"id": 42, "login": "octocat", "avatar_url": "https://a.example/x.png"}

    with (
        patch("src.integrations.github.router.exchange_code_for_tokens", new=AsyncMock(return_value=mock_tokens)),
        patch("src.integrations.github.router.GithubClient.get_user", new=AsyncMock(return_value=mock_user)),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False
        ) as client:
            resp = await client.get(
                "/api/integrations/github/callback",
                params={"code": "auth_code", "state": "gh_state_token"},
            )

    assert resp.status_code == 307
    assert "github=connected" in resp.headers["location"]

    from sqlalchemy import select
    from src.database import get_db
    from src.models.github_connection import GithubConnection
    from src.services.encryption import decrypt

    async for db in app.dependency_overrides[get_db]():
        conn = await db.scalar(select(GithubConnection))
        assert conn is not None
        assert conn.organization_id == org_id
        assert conn.github_login == "octocat"
        assert conn.github_user_id == "42"
        assert conn.is_active is True
        assert conn.connected_by_user_id == "user_1"
        # Token must be stored encrypted, and decrypt back to the original.
        assert conn.encrypted_access_token != "gho_secret"
        assert decrypt(conn.encrypted_access_token) == "gho_secret"
        assert conn.scopes == ["repo", "read:user"]
        break


@pytest.mark.asyncio
async def test_github_callback_deactivates_old_connections(tmp_db):
    clerk_org_id = "org_gh_test"
    org_id = await _seed_org(clerk_org_id)
    await _seed_state(clerk_org_id)

    from src.database import get_db
    from src.models.github_connection import GithubConnection
    from src.services.encryption import encrypt

    async for db in app.dependency_overrides[get_db]():
        db.add(GithubConnection(
            organization_id=org_id,
            github_user_id="1",
            github_login="old-login",
            encrypted_access_token=encrypt("old_token"),
            is_active=True,
        ))
        await db.commit()
        break

    mock_tokens = {"access_token": "gho_new", "scope": "repo"}
    mock_user = {"id": 2, "login": "new-login", "avatar_url": None}

    with (
        patch("src.integrations.github.router.exchange_code_for_tokens", new=AsyncMock(return_value=mock_tokens)),
        patch("src.integrations.github.router.GithubClient.get_user", new=AsyncMock(return_value=mock_user)),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False
        ) as client:
            resp = await client.get(
                "/api/integrations/github/callback",
                params={"code": "auth_code", "state": "gh_state_token"},
            )
    assert resp.status_code == 307

    from sqlalchemy import select

    async for db in app.dependency_overrides[get_db]():
        rows = (await db.execute(select(GithubConnection))).scalars().all()
        active = [r for r in rows if r.is_active]
        assert len(rows) == 2
        assert len(active) == 1
        assert active[0].github_login == "new-login"
        break


@pytest.mark.asyncio
async def test_github_callback_error_token_redirects_with_reason(tmp_db):
    clerk_org_id = "org_gh_test"
    await _seed_org(clerk_org_id)
    await _seed_state(clerk_org_id)

    # GitHub reports bad codes in a 200 body, not an HTTP error.
    mock_tokens = {"error": "bad_verification_code"}

    with patch(
        "src.integrations.github.router.exchange_code_for_tokens",
        new=AsyncMock(return_value=mock_tokens),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False
        ) as client:
            resp = await client.get(
                "/api/integrations/github/callback",
                params={"code": "bad", "state": "gh_state_token"},
            )
    assert resp.status_code == 307
    assert "github=error" in resp.headers["location"]
    assert "bad_verification_code" in resp.headers["location"]


@pytest.mark.asyncio
async def test_github_status_disconnect_cycle(tmp_db):
    clerk_org_id = "org_abc"
    org_id = await _seed_org(clerk_org_id)

    from src.database import get_db
    from src.models.github_connection import GithubConnection
    from src.services.encryption import encrypt

    with _patch_clerk(org_id=clerk_org_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/integrations/github/status", headers={"Authorization": "Bearer tok"}
            )
            assert resp.json() == {"connected": False}

            async for db in app.dependency_overrides[get_db]():
                db.add(GithubConnection(
                    organization_id=org_id,
                    github_user_id="42",
                    github_login="octocat",
                    avatar_url="https://a.example/x.png",
                    encrypted_access_token=encrypt("tok"),
                    scopes=["repo"],
                    is_active=True,
                ))
                await db.commit()
                break

            resp = await client.get(
                "/api/integrations/github/status", headers={"Authorization": "Bearer tok"}
            )
            body = resp.json()
            assert body["connected"] is True
            assert body["login"] == "octocat"
            assert body["scopes"] == ["repo"]

            resp = await client.delete(
                "/api/integrations/github/disconnect", headers={"Authorization": "Bearer tok"}
            )
            assert resp.json() == {"disconnected": True}

            resp = await client.get(
                "/api/integrations/github/status", headers={"Authorization": "Bearer tok"}
            )
            assert resp.json() == {"connected": False}


@pytest.mark.asyncio
async def test_github_repos_maps_fields(tmp_db):
    clerk_org_id = "org_abc"
    org_id = await _seed_org(clerk_org_id)

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

    mock_repos = [{
        "id": 7,
        "full_name": "octocat/hello",
        "private": True,
        "default_branch": "main",
        "html_url": "https://github.com/octocat/hello",
        "extra_field": "ignored",
    }]

    with (
        _patch_clerk(org_id=clerk_org_id),
        patch("src.integrations.github.router.GithubClient.list_repos", new=AsyncMock(return_value=mock_repos)),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/integrations/github/repos", headers={"Authorization": "Bearer tok"}
            )
    assert resp.status_code == 200
    assert resp.json() == [{
        "id": 7,
        "fullName": "octocat/hello",
        "private": True,
        "defaultBranch": "main",
        "url": "https://github.com/octocat/hello",
    }]
