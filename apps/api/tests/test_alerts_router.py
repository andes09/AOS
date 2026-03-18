"""Tests for GET /api/alerts and PATCH /api/alerts/{id}/dismiss."""
import uuid
import pytest
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock
from httpx import AsyncClient, ASGITransport
from src.models.alert import AlertType
from src.models.sprint import SprintStatus

ORG_CLERK_ID = "org_alerts_test"
ORG_ID = uuid.uuid4()
TEAM_ID = uuid.uuid4()
SPRINT_ID = uuid.uuid4()
ALERT_ID = uuid.uuid4()


def _make_org():
    o = MagicMock(); o.id = ORG_ID; o.clerk_org_id = ORG_CLERK_ID; return o

def _make_team():
    t = MagicMock(); t.id = TEAM_ID; t.organization_id = ORG_ID; t.sprint_length_days = 14; return t

def _make_sprint():
    s = MagicMock(); s.id = SPRINT_ID; s.team_id = TEAM_ID; s.status = SprintStatus.ACTIVE; return s

def _make_alert(dismissed=False):
    a = MagicMock()
    a.id = ALERT_ID
    a.sprint_id = SPRINT_ID
    a.team_id = TEAM_ID
    a.type = AlertType.stalled_ticket
    a.description = "PROJ-42 has not moved in 3 days."
    a.recommended_action = "Follow up with assignee or reassign."
    a.dismissed = dismissed
    a.created_at = datetime(2026, 3, 15, 10, 0, 0)
    return a


@pytest.mark.asyncio
async def test_get_alerts_returns_active_alerts():
    from src.main import app
    org = _make_org(); team = _make_team(); sprint = _make_sprint(); alert = _make_alert()
    session = MagicMock()
    call_idx = 0
    scalar_results = [org, team, sprint]
    async def fake_scalar(q):
        nonlocal call_idx; val = scalar_results[call_idx]; call_idx += 1; return val
    async def fake_scalars(q):
        r = MagicMock(); r.all.return_value = [alert]; return r
    session.scalar = fake_scalar; session.scalars = fake_scalars
    async def override_db(): yield session
    async def override_org(): return ORG_CLERK_ID
    from src.auth import get_current_org_id
    from src.database import get_db
    app.dependency_overrides[get_current_org_id] = override_org
    app.dependency_overrides[get_db] = override_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/alerts?team_id={TEAM_ID}")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["type"] == "stalled_ticket"
    assert data[0]["id"] == str(ALERT_ID)
    assert data[0]["title"] == "Stalled Ticket"
    assert "description" in data[0]
    assert "recommendedAction" in data[0]


@pytest.mark.asyncio
async def test_get_alerts_returns_empty_when_no_active_sprint():
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
            response = await client.get(f"/api/alerts?team_id={TEAM_ID}")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_dismiss_alert_returns_200():
    from src.main import app
    org = _make_org(); team = _make_team(); alert = _make_alert()
    session = MagicMock()
    call_idx = 0
    scalar_results = [org, team, alert]
    async def fake_scalar(q):
        nonlocal call_idx; val = scalar_results[call_idx]; call_idx += 1; return val
    session.scalar = fake_scalar
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    async def override_db(): yield session
    async def override_org(): return ORG_CLERK_ID
    from src.auth import get_current_org_id
    from src.database import get_db
    app.dependency_overrides[get_current_org_id] = override_org
    app.dependency_overrides[get_db] = override_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.patch(f"/api/alerts/{ALERT_ID}/dismiss?team_id={TEAM_ID}")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["dismissed"] is True


@pytest.mark.asyncio
async def test_dismiss_alert_returns_404_for_unknown_alert():
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
            response = await client.patch(f"/api/alerts/{ALERT_ID}/dismiss?team_id={TEAM_ID}")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_alerts_returns_401_without_auth():
    from src.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/alerts?team_id={TEAM_ID}")
    assert response.status_code == 401
