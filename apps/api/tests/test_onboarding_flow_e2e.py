"""
End-to-end test covering the full beta onboarding flow:
  callback → boards → board-selection → team-members → confirm-team

Also covers regression cases:
  - boards project-fallback 401 → 502
  - board-selection Celery down → in-process fallback
  - team-members Jira 502 → structured error
"""
import uuid
import pytest
from datetime import datetime, timedelta
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, MagicMock, patch

from src.main import app
from src.auth import get_current_user_id, get_current_org_id
from src.database import get_db


ORG_CLERK_ID = "org_e2e_onboarding"


def _patch_clerk(org_id=ORG_CLERK_ID, user_id="user_e2e"):
    payload = {"sub": user_id, "org_id": org_id}
    state = type("S", (), {"is_signed_in": True, "payload": payload})()
    return patch("src.auth._clerk.authenticate_request_async", new=AsyncMock(return_value=state))


async def _seed_org_team_conn(db, org_clerk_id=ORG_CLERK_ID):
    """Seed Organization + Team + active JiraConnection. Returns (org, team, conn)."""
    from src.models.organization import Organization
    from src.models.team import Team
    from src.models.jira_connection import JiraConnection

    org = Organization(
        id=uuid.uuid4(),
        clerk_org_id=org_clerk_id,
        name="E2E Org",
        slug=org_clerk_id,
        use_managed_key=False,
    )
    team = Team(
        id=uuid.uuid4(),
        organization_id=org.id,
        name="E2E Team",
        sprint_length_days=14,
    )
    conn = JiraConnection(
        id=uuid.uuid4(),
        organization_id=org.id,
        jira_cloud_id="cloud_e2e",
        jira_cloud_url="https://e2e.atlassian.net",
        encrypted_access_token="enc_token",
        encrypted_refresh_token="enc_refresh",
        is_active=True,
    )
    db.add_all([org, team, conn])
    await db.commit()
    return org, team, conn


# ---------------------------------------------------------------------------
# Step 1+2: OAuth callback creates JiraConnection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_callback_creates_jira_connection(tmp_db):
    """GET /callback with valid state creates JiraConnection for the org."""
    from src.models.organization import Organization
    from src.models.oauth_state import OAuthState
    from src.models.jira_connection import JiraConnection
    from sqlalchemy import select

    org_clerk_id = "org_cb_e2e"
    fake_state = "state_e2e_cb"

    async for db in app.dependency_overrides[get_db]():
        org = Organization(id=uuid.uuid4(), clerk_org_id=org_clerk_id,
                           name="CB Org", slug=org_clerk_id, use_managed_key=False)
        db.add(org)
        db.add(OAuthState(state=fake_state, user_id="user_1", org_id=org_clerk_id,
                          return_to="/onboarding",
                          expires_at=datetime.utcnow() + timedelta(minutes=10)))
        await db.commit()
        org_id = org.id
        break

    mock_tokens = {"access_token": "at_e2e", "refresh_token": "rt_e2e", "expires_in": 3600}
    mock_resources = [{"id": "cloud_e2e", "url": "https://e2e.atlassian.net"}]
    with (
        patch("src.integrations.jira.router.exchange_code_for_tokens", new=AsyncMock(return_value=mock_tokens)),
        patch("src.integrations.jira.router.get_accessible_resources", new=AsyncMock(return_value=mock_resources)),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test",
                               follow_redirects=False) as client:
            resp = await client.get("/api/integrations/jira/callback",
                                    params={"code": "code_e2e", "state": fake_state})

    assert resp.status_code == 307
    assert "connection_id=" in resp.headers["location"]

    async for db in app.dependency_overrides[get_db]():
        conn = await db.scalar(select(JiraConnection).where(JiraConnection.organization_id == org_id))
        assert conn is not None
        break


# ---------------------------------------------------------------------------
# Step 3: Boards endpoint returns list
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_boards_returns_list(tmp_db):
    """GET /boards returns non-empty list when JiraClient.get_boards succeeds."""
    async for db in app.dependency_overrides[get_db]():
        _, _, conn = await _seed_org_team_conn(db)
        conn_id = str(conn.id)
        break

    mock_client = MagicMock()
    mock_client.get_boards = AsyncMock(return_value=[
        {"id": 1, "name": "Team Board", "type": "scrum", "location": {"projectKey": "E2E"}},
    ])

    with (
        _patch_clerk(),
        patch("src.integrations.jira.router.decrypt", return_value="fake_access_token"),
        patch("src.integrations.jira.router.JiraClient", return_value=mock_client),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/integrations/jira/boards",
                params={"connection_id": conn_id},
                headers={"Authorization": "Bearer tok"},
            )

    assert resp.status_code == 200
    boards = resp.json()
    assert len(boards) >= 1
    assert boards[0]["name"] == "Team Board"


# ---------------------------------------------------------------------------
# Regression: boards project-fallback 401 → 502
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_boards_project_fallback_401_raises_502(tmp_db):
    """When project fallback returns 401, the endpoint raises 502."""
    from httpx import Response as HttpxResponse

    async for db in app.dependency_overrides[get_db]():
        _, _, conn = await _seed_org_team_conn(db, "org_boards_401")
        conn_id = str(conn.id)
        break

    # Simulate 401 response on get_projects
    fake_resp = MagicMock()
    fake_resp.status_code = 401
    proj_exc = Exception("Unauthorized")
    proj_exc.response = fake_resp

    mock_client = MagicMock()
    mock_client.get_boards = AsyncMock(return_value=[])  # agile returns nothing
    mock_client.get_projects = AsyncMock(side_effect=proj_exc)

    def _patch_clerk_401(org_id="org_boards_401", user_id="user_e2e"):
        payload = {"sub": user_id, "org_id": org_id}
        state = type("S", (), {"is_signed_in": True, "payload": payload})()
        return patch("src.auth._clerk.authenticate_request_async", new=AsyncMock(return_value=state))

    with (
        _patch_clerk_401(),
        patch("src.integrations.jira.router.decrypt", return_value="fake_access_token"),
        patch("src.integrations.jira.router.JiraClient", return_value=mock_client),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/integrations/jira/boards",
                params={"connection_id": conn_id},
                headers={"Authorization": "Bearer tok"},
            )

    assert resp.status_code == 502
    assert "auth/scope" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Step 4: board-selection with Celery down → in-process fallback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_board_selection_celery_fallback(tmp_db):
    """When Celery is down, board-selection falls back to in-process sync."""
    async for db in app.dependency_overrides[get_db]():
        _, team, conn = await _seed_org_team_conn(db)
        conn_id = str(conn.id)
        team_id = str(team.id)
        break

    run_in_process_calls = []

    def fake_run_in_process(tid):
        run_in_process_calls.append(tid)

    with (
        _patch_clerk(),
        patch("src.integrations.jira.sync.sync_jira_team") as mock_task,
        patch("src.integrations.jira.router._run_sync_in_process", new=fake_run_in_process),
    ):
        mock_task.delay = MagicMock(side_effect=Exception("Celery broker down"))
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/integrations/jira/board-selection",
                json={"connection_id": conn_id, "board_id": "99", "project_key": "E2E"},
                headers={"Authorization": "Bearer tok"},
            )

    assert resp.status_code == 200
    assert resp.json()["saved"] is True
    # In-process fallback was triggered
    assert team_id in run_in_process_calls


# ---------------------------------------------------------------------------
# Regression: team-members Jira 502 → structured error
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_team_members_jira_502(tmp_db):
    """When Jira get_users fails, endpoint returns 502 with detail."""
    async for db in app.dependency_overrides[get_db]():
        _, _, conn = await _seed_org_team_conn(db)
        conn_id = str(conn.id)
        break

    mock_client = MagicMock()
    mock_client.get_users = AsyncMock(side_effect=Exception("Jira 502"))

    with (
        _patch_clerk(),
        patch("src.integrations.jira.router.decrypt", return_value="fake_access_token"),
        patch("src.integrations.jira.router.JiraClient", return_value=mock_client),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/integrations/jira/team-members",
                params={"connection_id": conn_id},
                headers={"Authorization": "Bearer tok"},
            )

    assert resp.status_code == 502
    assert "Failed to fetch Jira users" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Step 5+6: team-members returns seeded devs; confirm-team sets completed_at
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_team_members_and_confirm_team(tmp_db):
    """
    Seed a developer with a jira_account_id; mock get_users to [] so no pg_insert
    runs; verify the seeded dev is returned. Then confirm-team sets completed_at.
    """
    from src.models.developer import Developer
    from sqlalchemy import select

    async for db in app.dependency_overrides[get_db]():
        org, team, conn = await _seed_org_team_conn(db)
        dev = Developer(
            id=uuid.uuid4(),
            team_id=team.id,
            name="Alice Dev",
            email="alice@e2e.test",
            jira_account_id="jira-alice",
            is_active=True,
            app_role="developer",
        )
        db.add(dev)
        await db.commit()
        conn_id = str(conn.id)
        org_id = org.id
        break

    # Mock get_users to [] — avoids pg_insert (SQLite-incompatible)
    mock_client = MagicMock()
    mock_client.get_users = AsyncMock(return_value=[])

    with (
        _patch_clerk(),
        patch("src.integrations.jira.router.decrypt", return_value="fake_access_token"),
        patch("src.integrations.jira.router.JiraClient", return_value=mock_client),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            members_resp = await client.get(
                "/api/integrations/jira/team-members",
                params={"connection_id": conn_id},
                headers={"Authorization": "Bearer tok"},
            )

    assert members_resp.status_code == 200
    members = members_resp.json()
    assert any(m["name"] == "Alice Dev" for m in members)

    # confirm-team
    with _patch_clerk():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            confirm_resp = await client.post(
                "/api/onboarding/confirm-team",
                json={"members": [{"name": "Alice Dev", "jiraAccountId": "jira-alice"}]},
                headers={"Authorization": "Bearer tok"},
            )

    assert confirm_resp.status_code == 200
    body = confirm_resp.json()
    assert body["upserted"] >= 1
    assert body["completedAt"] is not None

    async for db in app.dependency_overrides[get_db]():
        from src.models.organization import Organization
        refreshed = await db.get(Organization, org_id)
        assert refreshed.onboarding_completed_at is not None
        break
