"""Tests for velocity dashboard endpoints: burndown, capacity, health-score."""
import uuid
import pytest
from datetime import date
from unittest.mock import MagicMock
from httpx import AsyncClient, ASGITransport
from src.models.sprint import SprintStatus

ORG_CLERK_ID = "org_vel_dash"
ORG_ID = uuid.uuid4()
TEAM_ID = uuid.uuid4()
DEV_A_ID = uuid.uuid4()
DEV_B_ID = uuid.uuid4()


def _make_org():
    o = MagicMock(); o.id = ORG_ID; o.clerk_org_id = ORG_CLERK_ID; return o

def _make_team():
    t = MagicMock(); t.id = TEAM_ID; t.organization_id = ORG_ID; t.sprint_length_days = 14; return t

def _make_sprint(committed=40.0, delivered=12.0):
    s = MagicMock()
    s.id = uuid.uuid4(); s.team_id = TEAM_ID
    s.name = "Sprint 12"
    s.start_date = date(2026, 3, 10); s.end_date = date(2026, 3, 24)
    s.committed_points = committed; s.delivered_points = delivered
    s.status = SprintStatus.ACTIVE
    return s

def _make_tickets(sprint_id):
    def _t(completed, pts):
        t = MagicMock(); t.sprint_id = sprint_id
        t.estimated_points = pts; t.completed = completed; return t
    return [_t(True, 8.0), _t(True, 4.0), _t(False, 10.0), _t(False, 6.0), _t(False, 12.0)]

def _make_developer(dev_id, name):
    d = MagicMock(); d.id = dev_id; d.name = name
    d.team_id = TEAM_ID; d.is_active = True; return d


# --- burndown ---

@pytest.mark.asyncio
async def test_burndown_returns_three_series():
    from src.main import app
    org = _make_org(); team = _make_team(); sprint = _make_sprint()
    tickets = _make_tickets(sprint.id)
    session = MagicMock()
    call_idx = 0
    scalar_results = [org, team, sprint]
    async def fake_scalar(q):
        nonlocal call_idx; val = scalar_results[call_idx]; call_idx += 1; return val
    async def fake_scalars(q):
        r = MagicMock(); r.all.return_value = tickets; return r
    session.scalar = fake_scalar; session.scalars = fake_scalars
    async def override_db(): yield session
    async def override_org(): return ORG_CLERK_ID
    from src.auth import get_current_org_id
    from src.database import get_db
    app.dependency_overrides[get_current_org_id] = override_org
    app.dependency_overrides[get_db] = override_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/velocity/burndown?team_id={TEAM_ID}")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    data = response.json()
    assert "ideal" in data
    assert "actual" in data
    assert "predicted" in data
    assert isinstance(data["is_at_risk"], bool)
    assert len(data["ideal"]) > 0
    assert "date" in data["ideal"][0]
    assert "points" in data["ideal"][0]


@pytest.mark.asyncio
async def test_burndown_returns_404_when_no_active_sprint():
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
            response = await client.get(f"/api/velocity/burndown?team_id={TEAM_ID}")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 404


# --- capacity ---

@pytest.mark.asyncio
async def test_sprint_capacity_returns_developer_list():
    from src.main import app
    org = _make_org(); team = _make_team(); sprint = _make_sprint()
    dev_a = _make_developer(DEV_A_ID, "Alice")
    dev_b = _make_developer(DEV_B_ID, "Bob")
    session = MagicMock()
    call_idx = 0
    scalar_results = [org, team, sprint]
    async def fake_scalar(q):
        nonlocal call_idx; val = scalar_results[call_idx]; call_idx += 1; return val
    async def fake_scalars(q):
        r = MagicMock(); r.all.return_value = [dev_a, dev_b]; return r
    session.scalar = fake_scalar; session.scalars = fake_scalars
    async def override_db(): yield session
    async def override_org(): return ORG_CLERK_ID
    from src.auth import get_current_org_id
    from src.database import get_db
    app.dependency_overrides[get_current_org_id] = override_org
    app.dependency_overrides[get_db] = override_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/velocity/capacity?team_id={TEAM_ID}")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    data = response.json()
    assert "sprint_id" in data
    assert len(data["capacity"]) == 2
    names = {item["name"] for item in data["capacity"]}
    assert names == {"Alice", "Bob"}


@pytest.mark.asyncio
async def test_sprint_capacity_returns_404_when_no_active_sprint():
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
            response = await client.get(f"/api/velocity/capacity?team_id={TEAM_ID}")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 404


# --- health-score ---

@pytest.mark.asyncio
async def test_health_score_returns_score_and_reasons():
    from src.main import app
    org = _make_org(); team = _make_team(); sprint = _make_sprint(committed=40.0, delivered=12.0)
    tickets = _make_tickets(sprint.id)
    session = MagicMock()
    call_idx = 0
    scalar_results = [org, team, sprint]
    async def fake_scalar(q):
        nonlocal call_idx; val = scalar_results[call_idx]; call_idx += 1; return val
    async def fake_scalars(q):
        r = MagicMock(); r.all.return_value = tickets; return r
    session.scalar = fake_scalar; session.scalars = fake_scalars
    async def override_db(): yield session
    async def override_org(): return ORG_CLERK_ID
    from src.auth import get_current_org_id
    from src.database import get_db
    app.dependency_overrides[get_current_org_id] = override_org
    app.dependency_overrides[get_db] = override_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/velocity/health-score?team_id={TEAM_ID}")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    data = response.json()
    assert 0 <= data["score"] <= 100
    assert data["trend"] in ("up", "down", "stable")
    assert len(data["reasons"]) == 3
