"""Tests for the skill_ratings field on /api/teams/setup (Initiative A, Wave 2).

Uses Pydantic-only unit tests plus the MagicMock-session pattern (see
test_identifiers_router.py) because the project's SQLite-based ``tmp_db``
fixture cannot render JSONB columns on the developers model — a pre-existing
limitation.

Covers:
1. MemberSetupIn with valid skill_ratings → accepted; persisted to
   Developer.skill_ratings.
2. MemberSetupIn with no skill_ratings → accepted; Developer.skill_ratings is
   None.
3. MemberSetupIn with skill_ratings value 1.5 → 422.
"""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from httpx import AsyncClient, ASGITransport
from pydantic import ValidationError

from src.auth import get_current_org_id, get_current_user_id
from src.main import app
from src.models.developer import Developer
from src.routers.teams import MemberSetupIn

ORG_CLERK_ID = "org_skill_ratings_test"
ORG_ID = uuid.uuid4()
TEAM_ID = uuid.uuid4()


# ---------------------------------------------------------------------------
# Pydantic validator unit tests
# ---------------------------------------------------------------------------


def _valid_member_payload(**overrides):
    base = {
        "name": "Alex",
        "email": "alex@example.com",
        "role": "backend",
        "custom_role": None,
        "seniority": "Mid",
        "capacity_hours_per_week": 32,
        "domain_strengths": ["api"],
        "meeting_hours_bucket": "3to6",
    }
    base.update(overrides)
    return base


def test_member_setup_in_accepts_valid_skill_ratings():
    m = MemberSetupIn(**_valid_member_payload(skill_ratings={"Python": 0.8, "SQL": 0.0, "TS": 1.0}))
    assert m.skill_ratings == {"Python": 0.8, "SQL": 0.0, "TS": 1.0}


def test_member_setup_in_accepts_missing_skill_ratings():
    m = MemberSetupIn(**_valid_member_payload())
    assert m.skill_ratings is None


def test_member_setup_in_rejects_skill_rating_above_one():
    with pytest.raises(ValidationError) as exc_info:
        MemberSetupIn(**_valid_member_payload(skill_ratings={"Python": 1.5}))
    assert "skill_ratings values must be between 0.0 and 1.0" in str(exc_info.value)


def test_member_setup_in_rejects_skill_rating_below_zero():
    with pytest.raises(ValidationError) as exc_info:
        MemberSetupIn(**_valid_member_payload(skill_ratings={"Python": -0.1}))
    assert "skill_ratings values must be between 0.0 and 1.0" in str(exc_info.value)


# ---------------------------------------------------------------------------
# End-to-end: POST /api/teams/setup persistence path
# ---------------------------------------------------------------------------


def _make_org(clerk_id=ORG_CLERK_ID, id_=ORG_ID):
    o = MagicMock()
    o.id = id_
    o.clerk_org_id = clerk_id
    return o


def _make_team(team_id=TEAM_ID, org_id=ORG_ID):
    t = MagicMock(spec=[
        "id", "organization_id", "name", "size_tier", "methodology",
        "tech_stack", "sprint_length_days", "profile_setup_at",
    ])
    t.id = team_id
    t.organization_id = org_id
    t.name = "Team"
    return t


class _FakeSession:
    def __init__(self, scalar_results=None):
        self._scalars = list(scalar_results or [])
        self.added: list = []
        self.commit_calls = 0
        self.flush_calls = 0

    async def scalar(self, _q):
        if not self._scalars:
            return None
        return self._scalars.pop(0)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flush_calls += 1

    async def commit(self):
        self.commit_calls += 1


def _override_auth(clerk_org_id: str = ORG_CLERK_ID):
    async def _org(): return clerk_org_id
    async def _user(): return "user_test"
    app.dependency_overrides[get_current_org_id] = _org
    app.dependency_overrides[get_current_user_id] = _user


def _override_db(session):
    from src.database import get_db
    async def _gen(): yield session
    app.dependency_overrides[get_db] = _gen


def _clear():
    app.dependency_overrides.clear()


def _camel_member(**overrides):
    base = {
        "name": "Alex",
        "email": "alex@example.com",
        "role": "backend",
        "customRole": None,
        "seniority": "Mid",
        "capacityHoursPerWeek": 32,
        "domainStrengths": ["api"],
        "meetingHoursBucket": "3to6",
    }
    base.update(overrides)
    return base


def _team_setup_body(members):
    return {
        "name": "Team",
        "sizeTier": "6-10",
        "cadence": "2-week",
        "methodology": "Scrum",
        "techStack": ["Python"],
        "members": members,
    }


@pytest.mark.asyncio
async def test_setup_persists_skill_ratings_to_developer():
    org = _make_org()
    team = _make_team()
    # team_setup calls db.scalar(Organization) then db.scalar(Team).
    session = _FakeSession(scalar_results=[org, team])
    _override_auth(); _override_db(session)

    body = _team_setup_body([
        _camel_member(skillRatings={"Python": 0.7, "SQL": 0.3}),
    ])

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.post("/api/teams/setup", json=body)
    finally:
        _clear()

    assert r.status_code == 200, r.text
    devs = [o for o in session.added if isinstance(o, Developer)]
    assert len(devs) == 1
    assert devs[0].skill_ratings == {"Python": 0.7, "SQL": 0.3}
    assert session.commit_calls >= 1


@pytest.mark.asyncio
async def test_setup_missing_skill_ratings_leaves_developer_null():
    org = _make_org()
    team = _make_team()
    session = _FakeSession(scalar_results=[org, team])
    _override_auth(); _override_db(session)

    body = _team_setup_body([_camel_member()])  # no skillRatings key

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.post("/api/teams/setup", json=body)
    finally:
        _clear()

    assert r.status_code == 200, r.text
    devs = [o for o in session.added if isinstance(o, Developer)]
    assert len(devs) == 1
    assert devs[0].skill_ratings is None


@pytest.mark.asyncio
async def test_setup_rejects_skill_ratings_value_above_one():
    # No DB calls should happen because validation runs before the handler.
    session = _FakeSession(scalar_results=[])
    _override_auth(); _override_db(session)

    body = _team_setup_body([_camel_member(skillRatings={"Python": 1.5})])

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.post("/api/teams/setup", json=body)
    finally:
        _clear()

    assert r.status_code == 422
    assert "skill_ratings values must be between 0.0 and 1.0" in r.text
