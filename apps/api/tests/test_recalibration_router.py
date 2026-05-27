"""Tests for /api/recalibration/* (M8c, Initiative A Wave 5).

MagicMock-session pattern (no tmp_db).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import MagicMock

import pytest
from httpx import AsyncClient, ASGITransport

from src.auth import get_current_org_id, get_current_user_id
from src.auth_roles import get_current_app_role
from src.main import app


ORG_CLERK_ID = "org_recalib_test"
ORG_ID = uuid.uuid4()
TEAM_ID = uuid.uuid4()
OTHER_ORG_ID = uuid.uuid4()
OTHER_TEAM_ID = uuid.uuid4()
PROPOSAL_ID = uuid.uuid4()
DEV_ID = uuid.uuid4()
IDENT_ID = uuid.uuid4()
LEAD_USER_ID = "user_lead_clerk"
LEAD_DEV_ID = uuid.uuid4()


def _make_org(clerk_id=ORG_CLERK_ID, id_=ORG_ID):
    o = MagicMock()
    o.id = id_
    o.clerk_org_id = clerk_id
    return o


def _make_team(team_id=TEAM_ID, org_id=ORG_ID):
    t = MagicMock()
    t.id = team_id
    t.organization_id = org_id
    return t


def _make_proposal(
    *, kind="skill_rating", status_="pending",
    developer_id=DEV_ID, identifier_id=None, skill="SQL",
    suggested_value=0.4, current_value=0.7, suggested_skill=None,
):
    p = MagicMock()
    p.id = PROPOSAL_ID
    p.team_id = TEAM_ID
    p.kind = kind
    p.status = status_
    p.developer_id = developer_id
    p.identifier_id = identifier_id
    p.skill = skill
    p.current_value = current_value
    p.suggested_value = suggested_value
    p.suggested_skill = suggested_skill
    p.evidence = ["o1", "o2", "o3"]
    p.decided_at = None
    p.decided_by = None
    p.created_at = datetime(2026, 1, 1, 12, 0, 0)
    return p


def _make_dev(skill_ratings=None):
    d = MagicMock()
    d.id = DEV_ID
    d.clerk_user_id = LEAD_USER_ID
    d.skill_ratings = skill_ratings if skill_ratings is not None else {"SQL": 0.7}
    return d


def _make_identifier(skill="SQL"):
    i = MagicMock()
    i.id = IDENT_ID
    i.skill = skill
    return i


class FakeSession:
    """Async session with sequenced .scalar() / .scalars() / .execute() results."""

    def __init__(self, *, scalar_results=None, scalars_lists=None):
        self._scalar_results = list(scalar_results or [])
        self._scalars_lists = list(scalars_lists or [])
        self.added: list = []
        self.commit_calls = 0

    async def scalar(self, _q):
        return self._scalar_results.pop(0) if self._scalar_results else None

    async def scalars(self, _q):
        m = MagicMock()
        m.all = MagicMock(return_value=self._scalars_lists.pop(0) if self._scalars_lists else [])
        return m

    async def execute(self, _q):
        m = MagicMock()
        m.all = MagicMock(return_value=[])
        m.scalar_one_or_none = MagicMock(return_value=None)
        return m

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commit_calls += 1


def _override_auth(role="lead", clerk_org_id=ORG_CLERK_ID, user_id=LEAD_USER_ID):
    async def _org(): return clerk_org_id
    async def _user(): return user_id
    async def _role(): return role
    app.dependency_overrides[get_current_org_id] = _org
    app.dependency_overrides[get_current_user_id] = _user
    app.dependency_overrides[get_current_app_role] = _role


def _override_db(session):
    from src.database import get_db
    async def _gen(): yield session
    app.dependency_overrides[get_db] = _gen


def _clear():
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /scan/{team_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_returns_count(monkeypatch):
    team = _make_team()
    org = _make_org()
    session = FakeSession(scalar_results=[team, org])
    _override_auth("lead"); _override_db(session)

    async def fake_detect_and_persist(team_id, db):
        return 4
    monkeypatch.setattr(
        "src.routers.recalibration.detect_and_persist", fake_detect_and_persist
    )

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.post(f"/api/recalibration/scan/{TEAM_ID}")
    finally:
        _clear()
    assert r.status_code == 200, r.text
    assert r.json() == {"inserted": 4}


# ---------------------------------------------------------------------------
# GET /proposals/{team_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_pending_proposals():
    team = _make_team()
    org = _make_org()
    proposals = [_make_proposal()]
    session = FakeSession(scalar_results=[team, org], scalars_lists=[proposals])
    _override_auth("lead"); _override_db(session)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.get(f"/api/recalibration/proposals/{TEAM_ID}")
    finally:
        _clear()
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body, list)
    assert len(body) == 1
    assert body[0]["kind"] == "skill_rating"
    assert body[0]["skill"] == "SQL"
    assert body[0]["status"] == "pending"


# ---------------------------------------------------------------------------
# POST /proposals/{id}/approve — skill_rating
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approve_mutates_skill_ratings_and_marks_approved():
    proposal = _make_proposal()
    team = _make_team()
    org = _make_org()
    dev = _make_dev(skill_ratings={"SQL": 0.7, "Python": 0.8})
    actor_dev = MagicMock(); actor_dev.id = LEAD_DEV_ID

    # _resolve_proposal_in_org: proposal, team, org
    # approve handler: Developer (target)
    # _resolve_actor_developer_id: actor Developer
    session = FakeSession(scalar_results=[proposal, team, org, dev, actor_dev])
    _override_auth("lead"); _override_db(session)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.post(f"/api/recalibration/proposals/{PROPOSAL_ID}/approve")
    finally:
        _clear()

    assert r.status_code == 200, r.text
    # Developer mutated
    assert dev.skill_ratings["SQL"] == pytest.approx(0.4)
    assert dev.skill_ratings["Python"] == pytest.approx(0.8)  # untouched
    # Proposal updated
    assert proposal.status == "approved"
    assert proposal.decided_at is not None
    assert proposal.decided_by == LEAD_DEV_ID
    assert session.commit_calls == 1


# ---------------------------------------------------------------------------
# POST /proposals/{id}/dismiss
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dismiss_marks_dismissed_no_mutation():
    proposal = _make_proposal()
    team = _make_team()
    org = _make_org()
    actor_dev = MagicMock(); actor_dev.id = LEAD_DEV_ID

    session = FakeSession(scalar_results=[proposal, team, org, actor_dev])
    _override_auth("lead"); _override_db(session)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.post(f"/api/recalibration/proposals/{PROPOSAL_ID}/dismiss")
    finally:
        _clear()

    assert r.status_code == 200, r.text
    assert proposal.status == "dismissed"
    assert proposal.decided_at is not None
    assert proposal.decided_by == LEAD_DEV_ID
    assert session.commit_calls == 1


# ---------------------------------------------------------------------------
# AuthZ guards
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_lead_role_forbidden():
    session = FakeSession()
    _override_auth("developer"); _override_db(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.post(f"/api/recalibration/scan/{TEAM_ID}")
    finally:
        _clear()
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_foreign_org_team_returns_404():
    team = _make_team(team_id=OTHER_TEAM_ID, org_id=OTHER_ORG_ID)
    other_org = _make_org(clerk_id="org_other", id_=OTHER_ORG_ID)
    session = FakeSession(scalar_results=[team, other_org])
    _override_auth("lead", clerk_org_id=ORG_CLERK_ID); _override_db(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.get(f"/api/recalibration/proposals/{OTHER_TEAM_ID}")
    finally:
        _clear()
    assert r.status_code == 404
