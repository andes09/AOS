"""
Tests for velocity API endpoints.

Auth and DB are fully mocked — no real connections required.
Pattern: patch get_current_org_id to return a fixed clerk_org_id,
         patch get_db to return a mock AsyncSession.
"""
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

ORG_CLERK_ID = "org_clerk_abc"
ORG_ID = uuid.uuid4()
TEAM_ID = uuid.uuid4()
DEV_A_ID = uuid.uuid4()
DEV_B_ID = uuid.uuid4()


def _make_org():
    org = MagicMock()
    org.id = ORG_ID
    org.clerk_org_id = ORG_CLERK_ID
    return org


def _make_team():
    team = MagicMock()
    team.id = TEAM_ID
    team.organization_id = ORG_ID
    team.sprint_length_days = 10
    return team


def _make_developer(dev_id, name):
    dev = MagicMock()
    dev.id = dev_id
    dev.name = name
    dev.team_id = TEAM_ID
    dev.is_active = True
    return dev


def _make_profile(dev_id, ticket_type, sprint_count, mean_days, std_dev):
    p = MagicMock()
    p.developer_id = dev_id
    p.team_id = TEAM_ID
    p.ticket_type = ticket_type
    p.domain = "backend"
    p.sprint_count = sprint_count
    p.mean_completion_days = mean_days
    p.std_dev = std_dev
    return p


# ---------------------------------------------------------------------------
# GET /api/teams/{team_id}/velocity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_team_velocity_returns_profiles():
    from src.main import app

    org = _make_org()
    team = _make_team()
    dev_a = _make_developer(DEV_A_ID, "Alice")
    dev_b = _make_developer(DEV_B_ID, "Bob")
    profile_a = _make_profile(DEV_A_ID, "story", sprint_count=5, mean_days=3.0, std_dev=0.5)
    profile_b = _make_profile(DEV_B_ID, "bug", sprint_count=1, mean_days=1.5, std_dev=None)

    session = MagicMock()
    call_idx = 0
    scalar_results = [org, team]
    scalars_results = [[dev_a, dev_b], [profile_a, profile_b]]

    async def fake_scalar(query):
        nonlocal call_idx
        val = scalar_results[call_idx]
        call_idx += 1
        return val

    si = 0

    async def fake_scalars(query):
        nonlocal si
        mock_result = MagicMock()
        mock_result.all.return_value = scalars_results[si]
        si += 1
        return mock_result

    session.scalar = fake_scalar
    session.scalars = fake_scalars

    async def override_db():
        yield session

    async def override_org():
        return ORG_CLERK_ID

    from src.auth import get_current_org_id
    from src.database import get_db
    app.dependency_overrides[get_current_org_id] = override_org
    app.dependency_overrides[get_db] = override_db

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/teams/{TEAM_ID}/velocity")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["team_id"] == str(TEAM_ID)
    assert len(data["profiles"]) == 2

    alice = next(p for p in data["profiles"] if p["name"] == "Alice")
    assert alice["sprint_count"] == 5
    assert alice["is_sufficient_data"] is True
    assert alice["confidence_score"] is not None
    assert "story" in alice["mean_completion_days"]

    bob = next(p for p in data["profiles"] if p["name"] == "Bob")
    assert bob["sprint_count"] == 1
    assert bob["is_sufficient_data"] is False
    assert bob["confidence_score"] is None


@pytest.mark.asyncio
async def test_team_velocity_returns_401_without_auth():
    from src.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/teams/{TEAM_ID}/velocity")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_team_velocity_returns_404_when_team_not_in_org():
    from src.main import app

    org = _make_org()

    session = MagicMock()
    call_idx = 0
    scalar_results = [org, None]  # team not found

    async def fake_scalar(query):
        nonlocal call_idx
        val = scalar_results[call_idx]
        call_idx += 1
        return val

    session.scalar = fake_scalar

    async def override_db():
        yield session

    async def override_org():
        return ORG_CLERK_ID

    from src.auth import get_current_org_id
    from src.database import get_db
    app.dependency_overrides[get_current_org_id] = override_org
    app.dependency_overrides[get_db] = override_db

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/teams/{TEAM_ID}/velocity")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_team_velocity_includes_developer_with_no_profile_rows():
    from src.main import app

    org = _make_org()
    team = _make_team()
    dev_a = _make_developer(DEV_A_ID, "Alice")  # has profile rows
    dev_b = _make_developer(DEV_B_ID, "Bob")    # has NO profile rows

    profile_a = _make_profile(DEV_A_ID, "story", sprint_count=5, mean_days=3.0, std_dev=0.5)

    session = MagicMock()
    call_idx = 0
    scalar_results = [org, team]
    scalars_results = [[dev_a, dev_b], [profile_a]]  # only Alice has a profile row

    async def fake_scalar(query):
        nonlocal call_idx
        val = scalar_results[call_idx]
        call_idx += 1
        return val

    si = 0

    async def fake_scalars(query):
        nonlocal si
        mock_result = MagicMock()
        mock_result.all.return_value = scalars_results[si]
        si += 1
        return mock_result

    session.scalar = fake_scalar
    session.scalars = fake_scalars

    async def override_db():
        yield session

    async def override_org():
        return ORG_CLERK_ID

    from src.auth import get_current_org_id
    from src.database import get_db
    app.dependency_overrides[get_current_org_id] = override_org
    app.dependency_overrides[get_db] = override_db

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/teams/{TEAM_ID}/velocity")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert len(data["profiles"]) == 2

    bob = next(p for p in data["profiles"] if p["name"] == "Bob")
    assert bob["sprint_count"] == 0
    assert bob["is_sufficient_data"] is False
    assert bob["confidence_score"] is None
    assert bob["mean_completion_days"] == {}


# ---------------------------------------------------------------------------
# GET /api/teams/{team_id}/velocity/{developer_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_developer_velocity_returns_single_profile():
    from src.main import app

    org = _make_org()
    team = _make_team()
    dev_a = _make_developer(DEV_A_ID, "Alice")
    profile_a = _make_profile(DEV_A_ID, "story", sprint_count=4, mean_days=2.5, std_dev=0.3)

    session = MagicMock()
    call_idx = 0
    scalar_results = [org, team, dev_a]

    async def fake_scalar(query):
        nonlocal call_idx
        val = scalar_results[call_idx]
        call_idx += 1
        return val

    async def fake_scalars(query):
        mock_result = MagicMock()
        mock_result.all.return_value = [profile_a]
        return mock_result

    session.scalar = fake_scalar
    session.scalars = fake_scalars

    async def override_db():
        yield session

    async def override_org():
        return ORG_CLERK_ID

    from src.auth import get_current_org_id
    from src.database import get_db
    app.dependency_overrides[get_current_org_id] = override_org
    app.dependency_overrides[get_db] = override_db

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/teams/{TEAM_ID}/velocity/{DEV_A_ID}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["developer_id"] == str(DEV_A_ID)
    assert data["name"] == "Alice"
    assert data["sprint_count"] == 4
    assert data["is_sufficient_data"] is True
    assert "story" in data["mean_completion_days"]


@pytest.mark.asyncio
async def test_developer_velocity_returns_404_for_unknown_developer():
    from src.main import app

    org = _make_org()
    team = _make_team()

    session = MagicMock()
    call_idx = 0
    scalar_results = [org, team, None]  # developer not found

    async def fake_scalar(query):
        nonlocal call_idx
        val = scalar_results[call_idx]
        call_idx += 1
        return val

    session.scalar = fake_scalar

    async def override_db():
        yield session

    async def override_org():
        return ORG_CLERK_ID

    from src.auth import get_current_org_id
    from src.database import get_db
    app.dependency_overrides[get_current_org_id] = override_org
    app.dependency_overrides[get_db] = override_db

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/teams/{TEAM_ID}/velocity/{DEV_A_ID}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/teams/{team_id}/capacity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_team_capacity_returns_developer_availability():
    from src.main import app
    from datetime import date

    org = _make_org()
    team = _make_team()
    dev_a = _make_developer(DEV_A_ID, "Alice")
    dev_b = _make_developer(DEV_B_ID, "Bob")

    active_sprint = MagicMock()
    active_sprint.start_date = date(2026, 3, 10)
    active_sprint.end_date = date(2026, 3, 20)

    session = MagicMock()
    call_idx = 0
    scalar_results = [org, team, active_sprint]

    async def fake_scalar(query):
        nonlocal call_idx
        val = scalar_results[call_idx]
        call_idx += 1
        return val

    async def fake_scalars(query):
        mock_result = MagicMock()
        mock_result.all.return_value = [dev_a, dev_b]
        return mock_result

    session.scalar = fake_scalar
    session.scalars = fake_scalars

    async def override_db():
        yield session

    async def override_org():
        return ORG_CLERK_ID

    from src.auth import get_current_org_id
    from src.database import get_db
    app.dependency_overrides[get_current_org_id] = override_org
    app.dependency_overrides[get_db] = override_db

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/teams/{TEAM_ID}/capacity")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["team_id"] == str(TEAM_ID)
    assert len(data["capacity"]) == 2
    # No PTO or meetings in DB yet → full availability
    for item in data["capacity"]:
        assert item["availability_ratio"] == 1.0
        assert item["name"] in ("Alice", "Bob")


@pytest.mark.asyncio
async def test_team_capacity_falls_back_to_team_default_when_no_active_sprint():
    from src.main import app

    org = _make_org()
    team = _make_team()  # sprint_length_days = 10
    dev_a = _make_developer(DEV_A_ID, "Alice")

    session = MagicMock()
    call_idx = 0
    scalar_results = [org, team, None]  # no active sprint

    async def fake_scalar(query):
        nonlocal call_idx
        val = scalar_results[call_idx]
        call_idx += 1
        return val

    async def fake_scalars(query):
        mock_result = MagicMock()
        mock_result.all.return_value = [dev_a]
        return mock_result

    session.scalar = fake_scalar
    session.scalars = fake_scalars

    async def override_db():
        yield session

    async def override_org():
        return ORG_CLERK_ID

    from src.auth import get_current_org_id
    from src.database import get_db
    app.dependency_overrides[get_current_org_id] = override_org
    app.dependency_overrides[get_db] = override_db

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/teams/{TEAM_ID}/capacity")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["sprint_length_days"] == 10
