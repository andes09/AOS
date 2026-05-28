"""Tests for Scope Cop revision-acceptance telemetry (Initiative B, Wave 4 — SB-14).

MagicMock-session pattern (cf. test_plan_quality.py). No `tmp_db` because the
project's SQLite fixture cannot render JSONB columns on unrelated tables.

Covers:
1. is_accepted_verbatim: matching suggested keys → True; tweaked → False
2. classify_revision: verbatim vs edited
3. compute_acceptance_for_rows: rate math (verbatim + edited) / proposed
4. get_revision_acceptance_rates: buckets by sprint window, oldest→newest
5. GET /api/exec/revision-acceptance/{team_id} returns the trailing list
6. Foreign-org team_id → 404
7. Feature flag disabled → 404
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient, ASGITransport

from src.auth import get_current_org_id, get_current_user_id
from src.auth_roles import get_current_app_role
from src.config import settings
from src.main import app
from src.services.revision_telemetry import (
    classify_revision,
    compute_acceptance_for_rows,
    get_revision_acceptance_rates,
    is_accepted_verbatim,
)


ORG_CLERK_ID = "org_rev_test"
ORG_ID = uuid.uuid4()
TEAM_ID = uuid.uuid4()
OTHER_ORG_ID = uuid.uuid4()
OTHER_TEAM_ID = uuid.uuid4()


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _make_revision(suggested: dict, applied: dict, applied_at: datetime | None = None):
    r = MagicMock(spec=["suggested_revision", "applied_revision", "applied_at"])
    r.suggested_revision = suggested
    r.applied_revision = applied
    r.applied_at = applied_at
    return r


def _make_sprint(*, id_=None, name="Sprint 1", start_date=None, end_date=None,
                 team_id=TEAM_ID):
    s = MagicMock(spec=["id", "team_id", "name", "start_date", "end_date"])
    s.id = id_ or uuid.uuid4()
    s.team_id = team_id
    s.name = name
    s.start_date = start_date
    s.end_date = end_date
    return s


def _make_team(team_id=TEAM_ID, org_id=ORG_ID):
    t = MagicMock(spec=["id", "organization_id", "name"])
    t.id = team_id
    t.organization_id = org_id
    t.name = "Team A"
    return t


def _make_org(clerk_id=ORG_CLERK_ID, id_=ORG_ID):
    o = MagicMock(spec=["id", "clerk_org_id"])
    o.id = id_
    o.clerk_org_id = clerk_id
    return o


class _FakeSession:
    """Lightweight AsyncSession stand-in returning canned values in order."""

    def __init__(self, scalar_results=None, scalars_results=None):
        self._scalars = list(scalar_results or [])
        self._scalars_list = list(scalars_results or [])

    async def scalar(self, _q):
        if not self._scalars:
            return None
        return self._scalars.pop(0)

    async def scalars(self, _q):
        m = MagicMock()
        m.all = MagicMock(
            return_value=self._scalars_list.pop(0) if self._scalars_list else []
        )
        return m


def _override_auth(role: str = "lead", clerk_org_id: str = ORG_CLERK_ID):
    async def _org(): return clerk_org_id
    async def _user(): return "user_test"
    async def _role(): return role
    app.dependency_overrides[get_current_org_id] = _org
    app.dependency_overrides[get_current_user_id] = _user
    app.dependency_overrides[get_current_app_role] = _role


def _override_db(session):
    from src.database import get_db
    async def _gen():
        yield session
    app.dependency_overrides[get_db] = _gen


def _clear():
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 1. is_accepted_verbatim
# ---------------------------------------------------------------------------


def test_verbatim_when_applied_matches_suggested_keys():
    suggested = {"title": "Fix login", "story_points": 3}
    applied = {"title": "Fix login", "story_points": 3}
    assert is_accepted_verbatim(suggested, applied) is True


def test_verbatim_ignores_trailing_whitespace():
    suggested = {"title": "Fix login"}
    applied = {"title": "Fix login  "}
    assert is_accepted_verbatim(suggested, applied) is True


def test_not_verbatim_when_user_tweaks_a_suggested_key():
    suggested = {"title": "Fix login", "description": "as user I want..."}
    applied = {"title": "Fix the login bug", "description": "as user I want..."}
    assert is_accepted_verbatim(suggested, applied) is False


def test_not_verbatim_when_suggestion_empty():
    assert is_accepted_verbatim({}, {"title": "x"}) is False


def test_verbatim_ignores_extra_applied_keys():
    # User added a field Scope Cop didn't suggest — still verbatim on suggested.
    suggested = {"title": "Fix login"}
    applied = {"title": "Fix login", "labels": ["bug"]}
    assert is_accepted_verbatim(suggested, applied) is True


# ---------------------------------------------------------------------------
# 2. classify_revision
# ---------------------------------------------------------------------------


def test_classify_verbatim_and_edited():
    assert classify_revision({"title": "a"}, {"title": "a"}) == "accepted_verbatim"
    assert classify_revision({"title": "a"}, {"title": "b"}) == "edited"


# ---------------------------------------------------------------------------
# 3. compute_acceptance_for_rows: rate math
# ---------------------------------------------------------------------------


def test_acceptance_rate_counts_verbatim_plus_edited():
    rows = [
        _make_revision({"title": "a"}, {"title": "a"}),       # verbatim
        _make_revision({"title": "b"}, {"title": "b-edited"}),  # edited
        _make_revision({"title": "c"}, {"title": "c"}),       # verbatim
    ]
    stats = compute_acceptance_for_rows(rows)
    assert stats["proposed"] == 3
    assert stats["accepted_verbatim"] == 2
    assert stats["edited"] == 1
    # both verbatim + edited landed → 3/3
    assert stats["acceptance_rate"] == 1.0


def test_acceptance_rate_zero_when_no_rows():
    stats = compute_acceptance_for_rows([])
    assert stats == {
        "proposed": 0,
        "accepted_verbatim": 0,
        "edited": 0,
        "acceptance_rate": 0.0,
    }


# ---------------------------------------------------------------------------
# 4. get_revision_acceptance_rates: buckets by sprint window, oldest→newest
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_buckets_revisions_into_sprint_windows():
    sprint_new = _make_sprint(
        name="Sprint 2",
        start_date=date(2026, 2, 1),
        end_date=date(2026, 2, 14),
    )
    sprint_old = _make_sprint(
        name="Sprint 1",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 14),
    )
    # In Sprint 1 window: one verbatim, one edited.
    rev_old_verbatim = _make_revision(
        {"title": "x"}, {"title": "x"}, applied_at=datetime(2026, 1, 5, 10)
    )
    rev_old_edited = _make_revision(
        {"title": "y"}, {"title": "y-tweaked"}, applied_at=datetime(2026, 1, 10, 9)
    )
    # In Sprint 2 window: one verbatim.
    rev_new_verbatim = _make_revision(
        {"title": "z"}, {"title": "z"}, applied_at=datetime(2026, 2, 3, 14)
    )
    # Outside any window — ignored.
    rev_orphan = _make_revision(
        {"title": "q"}, {"title": "q"}, applied_at=datetime(2025, 12, 1, 0)
    )

    # Service: scalars(Sprint) newest-first, then scalars(TicketRevision).
    session = _FakeSession(
        scalars_results=[
            [sprint_new, sprint_old],
            [rev_old_verbatim, rev_old_edited, rev_new_verbatim, rev_orphan],
        ]
    )

    rows = await get_revision_acceptance_rates(TEAM_ID, session, n_sprints=8)

    # oldest → newest
    assert [r["sprint_name"] for r in rows] == ["Sprint 1", "Sprint 2"]
    assert rows[0]["proposed"] == 2
    assert rows[0]["accepted_verbatim"] == 1
    assert rows[0]["edited"] == 1
    assert rows[0]["acceptance_rate"] == 1.0
    assert rows[1]["proposed"] == 1
    assert rows[1]["accepted_verbatim"] == 1
    assert rows[1]["acceptance_rate"] == 1.0


@pytest.mark.asyncio
async def test_sprint_with_no_revisions_is_zero():
    sprint = _make_sprint(
        name="Empty", start_date=date(2026, 3, 1), end_date=date(2026, 3, 14)
    )
    session = _FakeSession(scalars_results=[[sprint], []])
    rows = await get_revision_acceptance_rates(TEAM_ID, session, n_sprints=8)
    assert len(rows) == 1
    assert rows[0]["proposed"] == 0
    assert rows[0]["acceptance_rate"] == 0.0


# ---------------------------------------------------------------------------
# 5. GET /api/exec/revision-acceptance/{team_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_revision_acceptance_endpoint_returns_trailing_list():
    team = _make_team()
    org = _make_org()
    sprint = _make_sprint(
        name="S1", start_date=date(2026, 1, 1), end_date=date(2026, 1, 14)
    )
    rev = _make_revision(
        {"title": "a"}, {"title": "a"}, applied_at=datetime(2026, 1, 5)
    )
    # Endpoint flow:
    #   _resolve_team_in_org → scalar(Team), scalar(Organization)
    #   get_revision_acceptance_rates → scalars(Sprint), scalars(TicketRevision)
    session = _FakeSession(
        scalar_results=[team, org],
        scalars_results=[[sprint], [rev]],
    )
    _override_auth("lead"); _override_db(session)
    # exec_dashboard flag is enabled in the local test env (config/features/local.yaml).

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.get(f"/api/exec/revision-acceptance/{TEAM_ID}")
    finally:
        _clear()

    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body, list)
    assert len(body) == 1
    assert body[0]["sprintName"] == "S1"
    assert body[0]["proposed"] == 1
    assert body[0]["acceptedVerbatim"] == 1
    assert body[0]["acceptanceRate"] == 1.0


# ---------------------------------------------------------------------------
# 6. Foreign-org team → 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_revision_acceptance_foreign_org_returns_404():
    team = _make_team(team_id=OTHER_TEAM_ID, org_id=OTHER_ORG_ID)
    other_org = _make_org(clerk_id="org_other", id_=OTHER_ORG_ID)
    session = _FakeSession(scalar_results=[team, other_org])
    _override_auth("lead", clerk_org_id=ORG_CLERK_ID); _override_db(session)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.get(f"/api/exec/revision-acceptance/{OTHER_TEAM_ID}")
    finally:
        _clear()

    assert r.status_code == 404


# ---------------------------------------------------------------------------
# 7. Feature flag disabled → 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_revision_acceptance_feature_disabled_returns_404():
    _override_auth("lead"); _override_db(_FakeSession())

    def _fake(self, flag_name):  # noqa: ANN001
        return False

    try:
        with patch.object(type(settings), "is_feature_enabled", new=_fake):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
                r = await c.get(f"/api/exec/revision-acceptance/{TEAM_ID}")
    finally:
        _clear()

    assert r.status_code == 404
