"""Tests for POST /api/onboarding/reset."""
import uuid
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch

from src.main import app
from src.auth import get_current_user_id, get_current_org_id
from src.auth_roles import get_current_app_role
from src.database import get_db


def _override_auth(role: str = "admin", clerk_org_id: str = "org_reset_test"):
    async def _org(): return clerk_org_id
    async def _user(): return "user_reset"
    async def _role(): return role
    app.dependency_overrides[get_current_org_id] = _org
    app.dependency_overrides[get_current_user_id] = _user
    app.dependency_overrides[get_current_app_role] = _role


def _clear():
    for key in [get_current_org_id, get_current_user_id, get_current_app_role]:
        app.dependency_overrides.pop(key, None)


@pytest.mark.asyncio
async def test_reset_onboarding(tmp_db):
    """Reset deactivates Jira connections and clears board/onboarding fields."""
    from datetime import datetime
    from src.models.organization import Organization
    from src.models.team import Team
    from src.models.jira_connection import JiraConnection

    clerk_org_id = "org_reset_test"
    org_id = uuid.uuid4()
    team_id = uuid.uuid4()

    async for db in app.dependency_overrides[get_db]():
        org = Organization(
            id=org_id,
            clerk_org_id=clerk_org_id,
            name="Reset Test Org",
            slug=clerk_org_id,
            use_managed_key=False,
            onboarding_completed_at=datetime(2026, 1, 1),
        )
        db.add(org)
        team = Team(
            id=team_id,
            organization_id=org_id,
            name="Reset Team",
            jira_board_id="board-123",
            jira_project_key="RST",
        )
        db.add(team)
        conn = JiraConnection(
            id=uuid.uuid4(),
            organization_id=org_id,
            jira_cloud_id="cloud-abc",
            jira_cloud_url="https://test.atlassian.net",
            encrypted_access_token="tok",
            encrypted_refresh_token="rt",
            is_active=True,
        )
        db.add(conn)
        await db.commit()

    _override_auth(role="admin", clerk_org_id=clerk_org_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/onboarding/reset",
                headers={"Authorization": "Bearer tok"},
            )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

        async for db in app.dependency_overrides[get_db]():
            from sqlalchemy import select
            refreshed_org = await db.get(Organization, org_id)
            assert refreshed_org.onboarding_completed_at is None

            refreshed_team = await db.get(Team, team_id)
            assert refreshed_team.jira_board_id is None
            assert refreshed_team.jira_project_key is None

            conn_row = (await db.execute(
                select(JiraConnection).where(JiraConnection.organization_id == org_id)
            )).scalar_one_or_none()
            assert conn_row is not None
            assert conn_row.is_active is False
    finally:
        _clear()


@pytest.mark.asyncio
async def test_reset_requires_admin(tmp_db):
    """Non-admin role should get 403."""
    clerk_org_id = "org_reset_test"
    _override_auth(role="lead", clerk_org_id=clerk_org_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/onboarding/reset",
                headers={"Authorization": "Bearer tok"},
            )
        assert resp.status_code == 403
    finally:
        _clear()
