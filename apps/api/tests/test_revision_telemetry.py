"""Tests for Scope Cop revision-acceptance telemetry (Initiative B, Wave 4 — SB-14).

MagicMock-session pattern (cf. test_plan_quality.py). No `tmp_db` because the
project's SQLite fixture cannot render JSONB columns on unrelated tables.

Covers:
1. is_accepted_verbatim: matching suggested keys → True; tweaked → False
2. classify_revision: verbatim vs edited
3. compute_acceptance_for_rows: rate math (verbatim + edited) / proposed
4. get_revision_acceptance_rates: buckets by sprint window, oldest→newest

Note: the former items 5-7 (HTTP tests for GET /api/exec/revision-acceptance/{team_id})
were removed when the Exec Dashboard router (src/routers/exec.py) was deleted;
this file now only exercises the revision_telemetry service.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from unittest.mock import MagicMock

import pytest

from src.services.revision_telemetry import (
    classify_revision,
    compute_acceptance_for_rows,
    get_revision_acceptance_rates,
    is_accepted_verbatim,
)


TEAM_ID = uuid.uuid4()


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
