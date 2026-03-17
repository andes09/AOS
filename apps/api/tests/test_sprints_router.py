"""Tests for GET /api/sprints/current"""
import uuid
import pytest
from datetime import date, datetime
from unittest.mock import MagicMock, AsyncMock
from httpx import AsyncClient, ASGITransport

ORG_CLERK_ID = "org_sprint_test"
ORG_ID = uuid.uuid4()
TEAM_ID = uuid.uuid4()
SPRINT_ID = uuid.uuid4()


def _make_org():
    o = MagicMock(); o.id = ORG_ID; o.clerk_org_id = ORG_CLERK_ID; return o

def _make_team():
    t = MagicMock(); t.id = TEAM_ID; t.organization_id = ORG_ID; t.sprint_length_days = 14; return t

def _make_sprint(status="active"):
    from src.models.sprint import SprintStatus
    s = MagicMock()
    s.id = SPRINT_ID
    s.team_id = TEAM_ID
    s.name = "Sprint 12"
    s.start_date = date(2026, 3, 10)
    s.end_date = date(2026, 3, 24)
    s.committed_points = 40.0
    s.delivered_points = 12.0
    s.status = SprintStatus.ACTIVE
    return s


@pytest.mark.asyncio
async def test_current_sprint_returns_active_sprint():
    from src.main import app
    org = _make_org(); team = _make_team(); sprint = _make_sprint()
    session = MagicMock()
    call_idx = 0
    scalar_results = [org, team, sprint]
    async def fake_scalar(q):
        nonlocal call_idx; val = scalar_results[call_idx]; call_idx += 1; return val
    session.scalar = fake_scalar
    async def override_db(): yield session
    async def override_org(): return ORG_CLERK_ID
    from src.auth import get_current_org_id
    from src.database import get_db
    app.dependency_overrides[get_current_org_id] = override_org
    app.dependency_overrides[get_db] = override_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/sprints/current?team_id={TEAM_ID}")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Sprint 12"
    assert data["committed_points"] == 40.0
    assert data["delivered_points"] == 12.0
    assert data["status"] == "active"


@pytest.mark.asyncio
async def test_current_sprint_returns_404_when_no_active_sprint():
    from src.main import app
    org = _make_org(); team = _make_team()
    session = MagicMock()
    call_idx = 0
    scalar_results = [org, team, None]
    async def fake_scalar(q):
        nonlocal call_idx; val = scalar_results[call_idx]; call_idx += 1; return val
    session.scalar = fake_scalar
    async def override_db(): yield session
    async def override_org(): return ORG_CLERK_ID
    from src.auth import get_current_org_id
    from src.database import get_db
    app.dependency_overrides[get_current_org_id] = override_org
    app.dependency_overrides[get_db] = override_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/sprints/current?team_id={TEAM_ID}")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_current_sprint_returns_401_without_auth():
    from src.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/sprints/current?team_id={TEAM_ID}")
    assert response.status_code == 401
