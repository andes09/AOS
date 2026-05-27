"""Unit tests for src/services/override_analyzer.py (M8c).

Uses the project's MagicMock-session pattern (no tmp_db) because skill_ratings
and skill_vector are JSONB columns that the SQLite-based ``tmp_db`` fixture
cannot render reliably.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from src.services import override_analyzer as oa
from src.models.recalibration_proposal import RecalibrationProposal


TEAM_ID = uuid.uuid4()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_override(*, original_dev=None, new_dev=None, reason="skill_fit", days_ago=1, ticket_id=None):
    o = MagicMock()
    o.id = uuid.uuid4()
    o.original_developer_id = original_dev
    o.new_developer_id = new_dev
    o.reason_code = reason
    o.ticket_id = ticket_id or uuid.uuid4()
    o.created_at = datetime.utcnow() - timedelta(days=days_ago)
    return o


def _make_analysis(*, ticket_id, skill_vector=None, matched_identifiers=None):
    a = MagicMock()
    a.ticket_id = ticket_id
    a.skill_vector = skill_vector or {}
    a.matched_identifiers = matched_identifiers or []
    return a


def _make_dev(*, id_=None, skill_ratings=None):
    d = MagicMock()
    d.id = id_ or uuid.uuid4()
    d.skill_ratings = skill_ratings
    return d


def _make_identifier(*, id_=None, skill="Java"):
    i = MagicMock()
    i.id = id_ or uuid.uuid4()
    i.skill = skill
    return i


class FakeSession:
    """Async session that returns canned scalar / scalars results in sequence."""

    def __init__(self, *, execute_results=None, scalars_lists=None):
        self._execute_results = list(execute_results or [])
        self._scalars_lists = list(scalars_lists or [])
        self.added: list = []
        self.commit_calls = 0

    async def execute(self, _q):
        # `.all()` of a SELECT(SprintPlanOverride, Ticket.id) returns Row-like tuples.
        rows = self._execute_results.pop(0) if self._execute_results else []
        m = MagicMock()
        m.all = MagicMock(return_value=rows)
        return m

    async def scalars(self, _q):
        m = MagicMock()
        m.all = MagicMock(return_value=self._scalars_lists.pop(0) if self._scalars_lists else [])
        return m

    async def scalar(self, _q):
        return None

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commit_calls += 1


# ---------------------------------------------------------------------------
# detect_patterns
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detect_two_overrides_no_proposal():
    dev_id = uuid.uuid4()
    t1, t2 = uuid.uuid4(), uuid.uuid4()
    overrides = [
        (_make_override(original_dev=dev_id, ticket_id=t1), t1),
        (_make_override(original_dev=dev_id, ticket_id=t2), t2),
    ]
    analyses = [
        _make_analysis(ticket_id=t1, skill_vector={"SQL": 0.9}),
        _make_analysis(ticket_id=t2, skill_vector={"SQL": 0.9}),
    ]
    session = FakeSession(
        execute_results=[overrides],
        scalars_lists=[analyses],  # only analyses; no developers needed
    )
    candidates = await oa.detect_patterns(str(TEAM_ID), session)
    assert candidates == []


@pytest.mark.asyncio
async def test_detect_three_overrides_emits_skill_rating_proposal():
    dev_id = uuid.uuid4()
    t1, t2, t3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    overrides = [
        (_make_override(original_dev=dev_id, ticket_id=t1), t1),
        (_make_override(original_dev=dev_id, ticket_id=t2), t2),
        (_make_override(original_dev=dev_id, ticket_id=t3), t3),
    ]
    analyses = [
        _make_analysis(ticket_id=t1, skill_vector={"SQL": 0.9}),
        _make_analysis(ticket_id=t2, skill_vector={"SQL": 0.8}),
        _make_analysis(ticket_id=t3, skill_vector={"SQL": 0.7}),
    ]
    dev = _make_dev(id_=dev_id, skill_ratings={"SQL": 0.7})
    session = FakeSession(
        execute_results=[overrides],
        scalars_lists=[analyses, [dev]],  # 1) analyses 2) devs by id
    )
    candidates = await oa.detect_patterns(str(TEAM_ID), session)

    assert len(candidates) == 1
    c = candidates[0]
    assert c["kind"] == "skill_rating"
    assert c["developer_id"] == str(dev_id)
    assert c["skill"] == "SQL"
    assert c["current_value"] == pytest.approx(0.7)
    assert c["suggested_value"] == pytest.approx(0.4)
    assert len(c["evidence"]) == 3


@pytest.mark.asyncio
async def test_detect_identifier_skill_proposal():
    """3 reassigns to a target dev whose top skill differs from the identifier's skill."""
    ident_id = uuid.uuid4()
    target_dev_id = uuid.uuid4()
    t1, t2, t3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    overrides = [
        (_make_override(new_dev=target_dev_id, ticket_id=t1), t1),
        (_make_override(new_dev=target_dev_id, ticket_id=t2), t2),
        (_make_override(new_dev=target_dev_id, ticket_id=t3), t3),
    ]
    analyses = [
        _make_analysis(ticket_id=t1, matched_identifiers=[str(ident_id)]),
        _make_analysis(ticket_id=t2, matched_identifiers=[str(ident_id)]),
        _make_analysis(ticket_id=t3, matched_identifiers=[str(ident_id)]),
    ]
    target_dev = _make_dev(id_=target_dev_id, skill_ratings={"Java": 0.9, "SQL": 0.2})
    identifier = _make_identifier(id_=ident_id, skill="SQL")

    session = FakeSession(
        execute_results=[overrides],
        # Order matches the analyzer's reads:
        # 1) analyses (TicketSkillAnalysis)
        # 2) identifiers by id (dev fetch for skill_rating is skipped because
        #    no original_developer_id is present on these overrides)
        # 3) target developers by id
        scalars_lists=[analyses, [identifier], [target_dev]],
    )
    candidates = await oa.detect_patterns(str(TEAM_ID), session)

    assert len(candidates) == 1
    c = candidates[0]
    assert c["kind"] == "identifier_skill"
    assert c["identifier_id"] == str(ident_id)
    assert c["skill"] == "SQL"
    assert c["suggested_skill"] == "Java"
    assert len(c["evidence"]) == 3


# ---------------------------------------------------------------------------
# persist_proposals
# ---------------------------------------------------------------------------


def _make_existing_proposal(*, kind, status_="pending", decided_at=None, **kw):
    p = MagicMock()
    p.kind = kind
    p.status = status_
    p.decided_at = decided_at
    p.developer_id = kw.get("developer_id")
    p.identifier_id = kw.get("identifier_id")
    p.skill = kw.get("skill")
    p.suggested_skill = kw.get("suggested_skill")
    return p


@pytest.mark.asyncio
async def test_persist_skips_when_pending_proposal_exists():
    dev_id = uuid.uuid4()
    existing = _make_existing_proposal(
        kind="skill_rating",
        status_="pending",
        developer_id=dev_id,
        skill="SQL",
    )
    session = FakeSession(scalars_lists=[[existing]])

    candidates = [{
        "kind": "skill_rating",
        "developer_id": str(dev_id),
        "skill": "SQL",
        "current_value": 0.7,
        "suggested_value": 0.4,
        "evidence": ["e1", "e2", "e3"],
    }]
    inserted = await oa.persist_proposals(str(TEAM_ID), candidates, session)
    assert inserted == 0
    assert not any(isinstance(o, RecalibrationProposal) for o in session.added)


@pytest.mark.asyncio
async def test_persist_skips_when_recently_dismissed():
    dev_id = uuid.uuid4()
    existing = _make_existing_proposal(
        kind="skill_rating",
        status_="dismissed",
        decided_at=datetime.utcnow() - timedelta(days=5),  # within 30-day cooldown
        developer_id=dev_id,
        skill="SQL",
    )
    session = FakeSession(scalars_lists=[[existing]])

    candidates = [{
        "kind": "skill_rating",
        "developer_id": str(dev_id),
        "skill": "SQL",
        "current_value": 0.7,
        "suggested_value": 0.4,
        "evidence": ["e1"],
    }]
    inserted = await oa.persist_proposals(str(TEAM_ID), candidates, session)
    assert inserted == 0


@pytest.mark.asyncio
async def test_persist_inserts_fresh_candidates():
    dev_id = uuid.uuid4()
    # Stale dismissed (>30 days ago) should NOT block.
    existing = _make_existing_proposal(
        kind="skill_rating",
        status_="dismissed",
        decided_at=datetime.utcnow() - timedelta(days=45),
        developer_id=dev_id,
        skill="SQL",
    )
    session = FakeSession(scalars_lists=[[existing]])

    candidates = [{
        "kind": "skill_rating",
        "developer_id": str(dev_id),
        "skill": "SQL",
        "current_value": 0.7,
        "suggested_value": 0.4,
        "evidence": ["e1", "e2", "e3"],
    }]
    inserted = await oa.persist_proposals(str(TEAM_ID), candidates, session)
    assert inserted == 1
    new_rows = [o for o in session.added if isinstance(o, RecalibrationProposal)]
    assert len(new_rows) == 1
    assert new_rows[0].kind == "skill_rating"
    assert new_rows[0].skill == "SQL"
    assert session.commit_calls == 1
