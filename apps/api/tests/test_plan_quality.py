"""Tests for plan-quality telemetry (Initiative A, Wave 4 — SA-15).

MagicMock-session pattern (cf. test_identifiers_router.py). No `tmp_db` because
the project's SQLite fixture cannot render JSONB columns on unrelated tables.

Covers:
1. compute_sprint_override_rate: 0 overrides + 10 assignments → 0.0
2. compute_sprint_override_rate: 3 overrides + 10 assignments → 0.3
3. compute_sprint_override_rate: overrides_by_reason aggregates correctly,
   null reason_code → "unspecified"
4. persist_plan_quality writes both Sprint columns and commits
5. get_trailing_override_rates returns oldest→newest and limits to N

Note: the former items 6-7 (HTTP tests for GET /api/exec/plan-quality/{team_id})
were removed when the Exec Dashboard router (src/routers/exec.py) was deleted;
this file now only exercises the plan_quality service, which is still used by
src/integrations/jira/sync.py.
"""
from __future__ import annotations

import uuid
from datetime import date
from unittest.mock import MagicMock

import pytest

from src.services.plan_quality import (
    compute_sprint_override_rate,
    get_trailing_override_rates,
    persist_plan_quality,
)


TEAM_ID = uuid.uuid4()
SPRINT_ID = uuid.uuid4()


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _make_override(reason_code: str | None):
    o = MagicMock(spec=["reason_code"])
    o.reason_code = reason_code
    return o


def _make_assignment():
    return MagicMock(spec=["id"])


def _make_sprint(*, id_=None, name="Sprint 1", end_date=None,
                 plan_override_rate=None, plan_overrides_by_reason=None,
                 team_id=TEAM_ID):
    s = MagicMock(spec=[
        "id", "team_id", "name", "end_date",
        "plan_override_rate", "plan_overrides_by_reason",
    ])
    s.id = id_ or uuid.uuid4()
    s.team_id = team_id
    s.name = name
    s.end_date = end_date
    s.plan_override_rate = plan_override_rate
    s.plan_overrides_by_reason = plan_overrides_by_reason
    return s


class _FakeSession:
    """Lightweight AsyncSession stand-in returning canned values in order."""

    def __init__(self, scalar_results=None, scalars_results=None):
        self._scalars = list(scalar_results or [])
        self._scalars_list = list(scalars_results or [])
        self.added: list = []
        self.commit_calls = 0

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

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commit_calls += 1

    async def refresh(self, _obj):
        pass


# ---------------------------------------------------------------------------
# 1. compute_sprint_override_rate: empty
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compute_zero_overrides_with_assignments_returns_zero():
    overrides: list = []
    assignments = [_make_assignment() for _ in range(10)]
    session = _FakeSession(scalars_results=[overrides, assignments])

    result = await compute_sprint_override_rate(SPRINT_ID, session)

    assert result["override_rate"] == 0.0
    assert result["override_count"] == 0
    assert result["total_assignments"] == 10
    assert result["overrides_by_reason"] == {}


# ---------------------------------------------------------------------------
# 2. compute_sprint_override_rate: 3/10 -> 0.3
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compute_three_overrides_ten_assignments_returns_point_three():
    overrides = [
        _make_override("skill_fit"),
        _make_override("capacity"),
        _make_override("pto"),
    ]
    assignments = [_make_assignment() for _ in range(10)]
    session = _FakeSession(scalars_results=[overrides, assignments])

    result = await compute_sprint_override_rate(SPRINT_ID, session)

    assert result["override_rate"] == 0.3
    assert result["override_count"] == 3
    assert result["total_assignments"] == 10


# ---------------------------------------------------------------------------
# 3. overrides_by_reason aggregation + null → "unspecified"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compute_aggregates_overrides_by_reason_with_unspecified():
    overrides = [
        _make_override("skill_fit"),
        _make_override("skill_fit"),
        _make_override("capacity"),
        _make_override(None),
        _make_override(None),
    ]
    assignments = [_make_assignment() for _ in range(8)]
    session = _FakeSession(scalars_results=[overrides, assignments])

    result = await compute_sprint_override_rate(SPRINT_ID, session)

    assert result["overrides_by_reason"] == {
        "skill_fit": 2,
        "capacity": 1,
        "unspecified": 2,
    }
    assert result["override_count"] == 5
    assert result["total_assignments"] == 8


# ---------------------------------------------------------------------------
# 3b. Edge: zero assignments → override_rate 0.0 (avoid div-by-zero)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compute_zero_assignments_avoids_division_by_zero():
    overrides = [_make_override("other")]
    assignments: list = []
    session = _FakeSession(scalars_results=[overrides, assignments])

    result = await compute_sprint_override_rate(SPRINT_ID, session)

    assert result["override_rate"] == 0.0
    assert result["override_count"] == 1
    assert result["total_assignments"] == 0


# ---------------------------------------------------------------------------
# 4. persist_plan_quality writes both columns + commits
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persist_plan_quality_writes_both_columns_and_commits():
    sprint = _make_sprint(id_=SPRINT_ID)
    overrides = [_make_override("skill_fit"), _make_override(None)]
    assignments = [_make_assignment() for _ in range(4)]
    # scalar order: sprint lookup
    # scalars order: overrides, assignments
    session = _FakeSession(
        scalar_results=[sprint],
        scalars_results=[overrides, assignments],
    )

    await persist_plan_quality(SPRINT_ID, session)

    assert sprint.plan_override_rate == 0.5
    assert sprint.plan_overrides_by_reason == {"skill_fit": 1, "unspecified": 1}
    assert session.commit_calls == 1


# ---------------------------------------------------------------------------
# 5. get_trailing_override_rates: oldest→newest, limit N
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trailing_rates_returns_oldest_to_newest():
    # Service queries newest-first and reverses → simulate that ordering.
    sprint_new = _make_sprint(
        name="Sprint 3", end_date=date(2026, 3, 1),
        plan_override_rate=0.4,
        plan_overrides_by_reason={"capacity": 4},
    )
    sprint_mid = _make_sprint(
        name="Sprint 2", end_date=date(2026, 2, 1),
        plan_override_rate=0.2,
        plan_overrides_by_reason={"skill_fit": 2},
    )
    sprint_old = _make_sprint(
        name="Sprint 1", end_date=date(2026, 1, 1),
        plan_override_rate=0.1,
        plan_overrides_by_reason={"pto": 1},
    )
    session = _FakeSession(scalars_results=[[sprint_new, sprint_mid, sprint_old]])

    rows = await get_trailing_override_rates(TEAM_ID, session, n_sprints=8)

    assert [r["sprint_name"] for r in rows] == ["Sprint 1", "Sprint 2", "Sprint 3"]
    assert [r["override_rate"] for r in rows] == [0.1, 0.2, 0.4]
    assert rows[0]["overrides_by_reason"] == {"pto": 1}
