import pytest
import uuid
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch, MagicMock
from src.main import app


def _patch_clerk(user_id="user_1", org_id="org_abc"):
    payload = {"sub": user_id, "org_id": org_id}
    state = type("S", (), {"is_signed_in": True, "payload": payload})()
    return patch("src.auth._clerk.authenticate_request_async", new=AsyncMock(return_value=state))


def _patch_no_org(user_id="user_1"):
    payload = {"sub": user_id}  # no org_id
    state = type("S", (), {"is_signed_in": True, "payload": payload})()
    return patch("src.auth._clerk.authenticate_request_async", new=AsyncMock(return_value=state))


@pytest.mark.asyncio
async def test_jira_connect_requires_auth():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/integrations/jira/connect")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_jira_connect_requires_org_context():
    with _patch_no_org():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/integrations/jira/connect",
                headers={"Authorization": "Bearer tok"},
            )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_jira_connect_returns_auth_url():
    with _patch_clerk():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/integrations/jira/connect",
                headers={"Authorization": "Bearer tok"},
            )
    assert resp.status_code == 200
    body = resp.json()
    assert "auth_url" in body
    assert "auth.atlassian.com" in body["auth_url"]


@pytest.mark.asyncio
async def test_jira_callback_invalid_state():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            "/api/integrations/jira/callback",
            params={"code": "abc123", "state": "nonexistent_state"},
        )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_jira_callback_stores_real_org_id(tmp_db):
    """Callback resolves org_id from state and saves JiraConnection with real organization_id."""
    from src.integrations.jira import router as jira_router
    import uuid

    # Pre-seed an org and the state entry
    org_clerk_id = "org_test_123"
    fake_state = "test_state_token"
    jira_router._oauth_states[fake_state] = {"user_id": "user_1", "org_id": org_clerk_id}

    from src.database import get_db
    from src.models.organization import Organization

    async for db in app.dependency_overrides[get_db]():
        org = Organization(
            id=uuid.uuid4(),
            clerk_org_id=org_clerk_id,
            name="Test Org",
            slug=org_clerk_id,
            use_managed_key=False,
        )
        db.add(org)
        await db.commit()
        org_id = org.id
        break

    mock_tokens = {
        "access_token": "at_test",
        "refresh_token": "rt_test",
        "expires_in": 3600,
        "scope": "read:issue:jira write:sprint:jira-software offline_access",
    }
    mock_resources = [{"id": "cloud_abc", "url": "https://mysite.atlassian.net"}]

    with (
        patch("src.integrations.jira.router.exchange_code_for_tokens", new=AsyncMock(return_value=mock_tokens)),
        patch("src.integrations.jira.router.get_accessible_resources", new=AsyncMock(return_value=mock_resources)),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            follow_redirects=False,
        ) as client:
            resp = await client.get(
                "/api/integrations/jira/callback",
                params={"code": "auth_code", "state": fake_state},
            )

    # Should redirect to frontend
    assert resp.status_code == 307
    location = resp.headers["location"]
    assert "connection_id=" in location

    # Verify JiraConnection was saved with real org_id
    from src.models.jira_connection import JiraConnection
    from sqlalchemy import select
    async for db in app.dependency_overrides[get_db]():
        conn = await db.scalar(select(JiraConnection).where(JiraConnection.organization_id == org_id))
        assert conn is not None
        assert str(conn.organization_id) != "00000000-0000-0000-0000-000000000000"
        break


@pytest.mark.asyncio
async def test_board_selection_saves_to_team(tmp_db):
    """POST /board-selection saves board_id and project_key to the team."""
    from src.models.organization import Organization
    from src.models.team import Team
    from src.models.jira_connection import JiraConnection
    from src.database import get_db
    from sqlalchemy import select
    import uuid

    org_id = uuid.uuid4()
    team_id = uuid.uuid4()
    conn_id = uuid.uuid4()

    async for db in app.dependency_overrides[get_db]():
        org = Organization(id=org_id, clerk_org_id="org_bs", name="BS Org", slug="org_bs", use_managed_key=False)
        team = Team(id=team_id, organization_id=org_id, name="BS Team", sprint_length_days=14)
        conn = JiraConnection(
            id=conn_id,
            organization_id=org_id,
            jira_cloud_id="cloud_bs",
            jira_cloud_url="https://bs.atlassian.net",
            encrypted_access_token="enc_at",
            encrypted_refresh_token="enc_rt",
            is_active=True,
        )
        db.add_all([org, team, conn])
        await db.commit()
        break

    with _patch_clerk(org_id="org_bs"):
        # Patch at the sync module level since the router imports lazily
        with patch("src.integrations.jira.sync.sync_jira_team") as mock_task:
            mock_task.delay = MagicMock()
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/integrations/jira/board-selection",
                    json={"connection_id": str(conn_id), "board_id": "42", "project_key": "PROJ"},
                    headers={"Authorization": "Bearer tok"},
                )
    assert resp.status_code == 200
    assert resp.json()["saved"] is True

    async for db in app.dependency_overrides[get_db]():
        team = await db.get(Team, team_id)
        assert team.jira_board_id == "42"
        assert team.jira_project_key == "PROJ"
        break
