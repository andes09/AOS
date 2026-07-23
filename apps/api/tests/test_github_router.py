import uuid
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import httpx
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
    assert "github.com/apps/" in resp.json()["auth_url"]


@pytest.mark.asyncio
async def test_github_callback_invalid_state(tmp_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            "/api/integrations/github/callback",
            params={"installation_id": 123, "state": "nope"},
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
            params={"installation_id": 123, "state": "expired_state"},
        )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_github_callback_setup_action_request_redirects_pending(tmp_db):
    clerk_org_id = "org_gh_test"
    await _seed_org(clerk_org_id)
    await _seed_state(clerk_org_id)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False
    ) as client:
        resp = await client.get(
            "/api/integrations/github/callback",
            params={"installation_id": 123, "setup_action": "request", "state": "gh_state_token"},
        )
    assert resp.status_code == 307
    assert "github=error" in resp.headers["location"]
    assert "reason=installation_pending" in resp.headers["location"]


@pytest.mark.asyncio
async def test_github_callback_saves_connection_encrypted(tmp_db):
    clerk_org_id = "org_gh_test"
    org_id = await _seed_org(clerk_org_id)
    await _seed_state(clerk_org_id)

    mock_installation = {
        "account": {"id": 42, "login": "octocat", "avatar_url": "https://a.example/x.png"},
        "permissions": {"contents": "read", "metadata": "read"},
    }
    mock_token_data = {"token": "ghs_secret", "expires_at": "2099-01-01T00:00:00Z"}

    with (
        patch("src.integrations.github.router.get_installation", new=AsyncMock(return_value=mock_installation)),
        patch(
            "src.integrations.github.router.get_installation_access_token",
            new=AsyncMock(return_value=mock_token_data),
        ),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False
        ) as client:
            resp = await client.get(
                "/api/integrations/github/callback",
                params={"installation_id": 123, "setup_action": "install", "state": "gh_state_token"},
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
        assert conn.installation_id == "123"
        assert conn.github_login == "octocat"
        assert conn.github_user_id == "42"
        assert conn.is_active is True
        assert conn.connected_by_user_id == "user_1"
        # Token must be stored encrypted, and decrypt back to the original.
        assert conn.encrypted_access_token != "ghs_secret"
        assert decrypt(conn.encrypted_access_token) == "ghs_secret"
        assert conn.scopes == ["contents", "metadata"]
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

    mock_installation = {
        "account": {"id": 2, "login": "new-login", "avatar_url": None},
        "permissions": {"contents": "read"},
    }
    mock_token_data = {"token": "ghs_new", "expires_at": "2099-01-01T00:00:00Z"}

    with (
        patch("src.integrations.github.router.get_installation", new=AsyncMock(return_value=mock_installation)),
        patch(
            "src.integrations.github.router.get_installation_access_token",
            new=AsyncMock(return_value=mock_token_data),
        ),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False
        ) as client:
            resp = await client.get(
                "/api/integrations/github/callback",
                params={"installation_id": 456, "setup_action": "install", "state": "gh_state_token"},
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

    with patch(
        "src.integrations.github.router.get_installation",
        new=AsyncMock(side_effect=httpx.HTTPError("boom")),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False
        ) as client:
            resp = await client.get(
                "/api/integrations/github/callback",
                params={"installation_id": 789, "setup_action": "install", "state": "gh_state_token"},
            )
    assert resp.status_code == 307
    assert "github=error" in resp.headers["location"]
    assert "reason=token_exchange_failed" in resp.headers["location"]


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
                    installation_id="inst_1",
                    github_user_id="42",
                    github_login="octocat",
                    avatar_url="https://a.example/x.png",
                    encrypted_access_token=encrypt("tok"),
                    scopes=["contents"],
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
            assert body["scopes"] == ["contents"]
            assert body["needsReconnect"] is False

            resp = await client.delete(
                "/api/integrations/github/disconnect", headers={"Authorization": "Bearer tok"}
            )
            assert resp.json() == {"disconnected": True}

            resp = await client.get(
                "/api/integrations/github/status", headers={"Authorization": "Bearer tok"}
            )
            assert resp.json() == {"connected": False}


@pytest.mark.asyncio
async def test_github_status_needs_reconnect_for_legacy_connection(tmp_db):
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
            encrypted_access_token=encrypt("legacy_oauth_tok"),
            is_active=True,
        ))
        await db.commit()
        break

    with _patch_clerk(org_id=clerk_org_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/integrations/github/status", headers={"Authorization": "Bearer tok"}
            )
    assert resp.json()["needsReconnect"] is True


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
            installation_id="inst_1",
            github_user_id="42",
            github_login="octocat",
            encrypted_access_token=encrypt("tok"),
            token_expires_at=datetime.utcnow() + timedelta(hours=1),
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


@pytest.mark.asyncio
async def test_github_repos_refreshes_expired_token(tmp_db):
    clerk_org_id = "org_abc"
    org_id = await _seed_org(clerk_org_id)

    from src.database import get_db
    from src.models.github_connection import GithubConnection
    from src.services.encryption import decrypt, encrypt

    async for db in app.dependency_overrides[get_db]():
        db.add(GithubConnection(
            organization_id=org_id,
            installation_id="inst_1",
            github_user_id="42",
            github_login="octocat",
            encrypted_access_token=encrypt("stale_tok"),
            token_expires_at=datetime.utcnow() - timedelta(minutes=5),
            is_active=True,
        ))
        await db.commit()
        break

    mock_token_data = {"token": "fresh_tok", "expires_at": "2099-01-01T00:00:00Z"}

    with (
        _patch_clerk(org_id=clerk_org_id),
        patch(
            "src.integrations.github.router.get_installation_access_token",
            new=AsyncMock(return_value=mock_token_data),
        ),
        patch("src.integrations.github.router.GithubClient.list_repos", new=AsyncMock(return_value=[])),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/integrations/github/repos", headers={"Authorization": "Bearer tok"}
            )
    assert resp.status_code == 200

    from sqlalchemy import select

    async for db in app.dependency_overrides[get_db]():
        conn = await db.scalar(select(GithubConnection))
        assert decrypt(conn.encrypted_access_token) == "fresh_tok"
        assert conn.token_expires_at > datetime.utcnow()
        break
