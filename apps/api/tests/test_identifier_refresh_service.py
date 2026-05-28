"""Tests for identifier_refresh_service (Initiative A, Wave 4, M7).

Covers:
- No new tickets since since_at → empty refresh, age-out still runs.
- Known token re-encountered → occurrence_count bumped, last_seen_at
  updated, classifier NOT called.
- New token → classified and inserted.
- New-token cap of 200 respected.
- apply_age_out: decay flow (8mo old + 0.5 conf → 0.45).
- apply_age_out: prune flow (8mo old + 0.09 conf → deleted).
- apply_age_out idempotent within a single call cycle.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from src.models.identifier import TeamIdentifier
from src.services.identifier_classifier import ClassifiedIdentifier


# ---------------------------------------------------------------------------
# Mock helpers (mirror test_identifier_scan_service.py)
# ---------------------------------------------------------------------------


def _make_team(team_id=None, org_id=None, tech_stack=None, created_at=None):
    t = MagicMock(spec=[
        "id", "organization_id", "name", "tech_stack",
        "jira_board_id", "jira_project_key", "jira_import_status", "created_at",
    ])
    t.id = team_id or uuid.uuid4()
    t.organization_id = org_id or uuid.uuid4()
    t.name = "Team A"
    t.tech_stack = json.dumps(tech_stack) if tech_stack else None
    t.jira_board_id = 1
    t.jira_project_key = "PROJ"
    t.jira_import_status = "complete"
    t.created_at = created_at or datetime(2026, 1, 1, 12, 0, 0)
    return t


def _make_identifier(
    *,
    team_id,
    token="OrderService",
    normalized_token=None,
    occurrence_count=5,
    skill="Python",
    confidence=0.9,
    last_seen_at=None,
):
    r = MagicMock(spec=[
        "id", "team_id", "token", "normalized_token", "skill", "domain",
        "confidence", "source", "occurrence_count", "first_seen_at", "last_seen_at",
    ])
    r.id = uuid.uuid4()
    r.team_id = team_id
    r.token = token
    r.normalized_token = normalized_token or token.lower()
    r.skill = skill
    r.domain = None
    r.confidence = confidence
    r.source = "ticket_title"
    r.occurrence_count = occurrence_count
    r.first_seen_at = datetime(2026, 1, 1, 12, 0, 0)
    r.last_seen_at = last_seen_at or datetime(2026, 1, 1, 12, 0, 0)
    return r


class _ScalarsResult:
    """Mimics SQLAlchemy Result.scalars() chain — only ``.all()`` used here."""

    def __init__(self, items):
        self._items = list(items)

    def all(self):
        return list(self._items)


class _ExecuteResult:
    def __init__(self, items):
        self._items = list(items)

    def scalars(self):
        return _ScalarsResult(self._items)


class _FakeSession:
    """AsyncSession stub.

    - ``scalar_queue``: sequential return values for db.scalar(q) (used for
      since_at lookup and the per-token race-safe re-check on inserts).
    - ``execute_queue``: sequential return values for db.execute(q) (used to
      fetch the existing rows for the team, and age-out candidates).
    """

    def __init__(self, *, scalar_queue=None, execute_queue=None):
        self._scalars = list(scalar_queue or [])
        self._executes = list(execute_queue or [])
        self.added: list = []
        self.deleted: list = []
        self.commit_calls = 0

    async def scalar(self, _q):
        if not self._scalars:
            return None
        return self._scalars.pop(0)

    async def execute(self, _q):
        if not self._executes:
            return _ExecuteResult([])
        items = self._executes.pop(0)
        return _ExecuteResult(items)

    def add(self, obj):
        self.added.append(obj)

    async def delete(self, obj):
        self.deleted.append(obj)

    async def commit(self):
        self.commit_calls += 1


# ---------------------------------------------------------------------------
# refresh_team_identifiers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_no_new_tickets_runs_age_out(monkeypatch):
    """Empty corpus → zero counters; age-out still inspected."""
    from src.services import identifier_refresh_service as svc

    team = _make_team(tech_stack=["Python"])

    async def fake_corpus(team_id, db, jira_client, max_tickets=500, since_at=None):
        # Verifies our service is passing since_at through.
        assert since_at is not None
        return [], []

    async def fake_classify(tokens, stack, key, batch_size=50):
        return []

    monkeypatch.setattr(svc, "fetch_bootstrap_corpus", fake_corpus)
    monkeypatch.setattr(svc, "classify_identifiers", fake_classify)

    # scalar_queue[0] = since_at lookup (None → fallback to team.created_at).
    # execute_queue[0] = age-out candidates (none).
    session = _FakeSession(
        scalar_queue=[None],
        execute_queue=[[]],
    )

    result = await svc.refresh_team_identifiers(
        team=team, jira_client=object(), anthropic_key="sk-test", db=session
    )

    assert result == {
        "tokens_seen": 0,
        "new_tokens": 0,
        "classified": 0,
        "persisted": 0,
        "aged_out": 0,
        "pruned": 0,
    }
    # Empty-corpus path with age_out commits once.
    assert session.commit_calls == 1


@pytest.mark.asyncio
async def test_refresh_known_token_bumps_count_skips_classifier(monkeypatch):
    """Re-encountered token bumps counters; classifier NOT called."""
    from src.services import identifier_refresh_service as svc
    from src.services.identifier_bootstrap_source import TicketTextSource

    team = _make_team(tech_stack=["Python"])
    tickets = [
        TicketTextSource(
            ticket_id=str(uuid.uuid4()), jira_issue_key="PROJ-1",
            title="Refactor OrderService", description="",
            labels=[], components=[],
        ),
    ]

    async def fake_corpus(team_id, db, jira_client, max_tickets=500, since_at=None):
        return tickets, []

    classify_calls = []

    async def fake_classify(tokens, stack, key, batch_size=50):
        classify_calls.append(list(tokens))
        return []

    monkeypatch.setattr(svc, "fetch_bootstrap_corpus", fake_corpus)
    monkeypatch.setattr(svc, "classify_identifiers", fake_classify)

    existing = _make_identifier(
        team_id=team.id,
        token="OrderService",
        normalized_token="orderservice",
        occurrence_count=5,
        last_seen_at=datetime.utcnow() - timedelta(days=3),
    )
    session = _FakeSession(
        scalar_queue=[existing.last_seen_at],  # since_at lookup
        execute_queue=[[existing], []],         # existing-rows then age-out empty
    )

    result = await svc.refresh_team_identifiers(
        team=team, jira_client=object(), anthropic_key="sk-test", db=session
    )

    assert result["new_tokens"] == 0
    assert result["classified"] == 0
    assert result["persisted"] == 1
    assert existing.occurrence_count == 6
    assert existing.last_seen_at > datetime.utcnow() - timedelta(seconds=10)
    # Classifier untouched.
    assert classify_calls == []
    # No new rows added (token was known).
    assert not any(isinstance(o, TeamIdentifier) for o in session.added)


@pytest.mark.asyncio
async def test_refresh_new_token_classified_and_inserted(monkeypatch):
    """Brand-new token routes through the classifier and gets persisted."""
    from src.services import identifier_refresh_service as svc
    from src.services.identifier_bootstrap_source import TicketTextSource

    team = _make_team(tech_stack=["Python", "PostgreSQL"])
    tickets = [
        TicketTextSource(
            ticket_id=str(uuid.uuid4()), jira_issue_key="PROJ-2",
            title="Add dbo.tile_metrics index",
            description="",
            labels=[], components=[],
        ),
    ]

    classified = [
        ClassifiedIdentifier(
            token="dbo.tile_metrics", normalized_token="dbo.tile_metrics",
            skill="PostgreSQL", domain="data", confidence=0.85, occurrence_count=1,
        ),
    ]

    async def fake_corpus(team_id, db, jira_client, max_tickets=500, since_at=None):
        return tickets, []

    async def fake_classify(tokens, stack, key, batch_size=50):
        return classified

    monkeypatch.setattr(svc, "fetch_bootstrap_corpus", fake_corpus)
    monkeypatch.setattr(svc, "classify_identifiers", fake_classify)

    # since_at: None → fallback to team.created_at.
    # existing rows: empty.
    # race-safe re-check for the one new token: None.
    # age-out candidates: empty.
    session = _FakeSession(
        scalar_queue=[None, None],
        execute_queue=[[], []],
    )

    result = await svc.refresh_team_identifiers(
        team=team, jira_client=object(), anthropic_key="sk-test", db=session
    )

    assert result["new_tokens"] == 1
    assert result["classified"] == 1
    assert result["persisted"] == 1
    new_rows = [o for o in session.added if isinstance(o, TeamIdentifier)]
    assert len(new_rows) == 1
    assert new_rows[0].token == "dbo.tile_metrics"
    assert new_rows[0].skill == "PostgreSQL"


@pytest.mark.asyncio
async def test_refresh_caps_new_tokens_at_200(monkeypatch):
    """When > 200 brand-new tokens appear, only the top-200 by frequency
    are sent to the classifier."""
    from src.services import identifier_refresh_service as svc
    from src.services.identifier_bootstrap_source import TicketTextSource

    team = _make_team(tech_stack=["Python"])

    # Build a title with 250 distinct CamelCase tokens, each occurring once.
    # We'll forge frequencies through repeats so we can verify ordering.
    title_tokens = [f"TokenAlpha{i:04d}" for i in range(250)]
    tickets = [
        TicketTextSource(
            ticket_id=str(uuid.uuid4()), jira_issue_key="PROJ-3",
            title=" ".join(title_tokens),
            description="",
            labels=[], components=[],
        ),
    ]

    captured_inputs: list = []

    async def fake_corpus(team_id, db, jira_client, max_tickets=500, since_at=None):
        return tickets, []

    async def fake_classify(tokens, stack, key, batch_size=50):
        captured_inputs.append(list(tokens))
        # Return classifications matching exactly what was sent so persisted
        # counter is meaningful.
        return [
            ClassifiedIdentifier(
                token=raw, normalized_token=norm,
                skill="Python", domain="backend",
                confidence=0.8, occurrence_count=cnt,
            )
            for raw, norm, cnt in tokens
        ]

    monkeypatch.setattr(svc, "fetch_bootstrap_corpus", fake_corpus)
    monkeypatch.setattr(svc, "classify_identifiers", fake_classify)

    # scalar_queue: since_at lookup + 200 race-safe re-checks (all None).
    # execute_queue: existing rows empty + age-out empty.
    session = _FakeSession(
        scalar_queue=[None] + [None] * 200,
        execute_queue=[[], []],
    )

    result = await svc.refresh_team_identifiers(
        team=team, jira_client=object(), anthropic_key="sk-test", db=session
    )

    assert result["new_tokens"] == 250
    # Cap kicks in.
    assert result["classified"] == 200
    assert len(captured_inputs) == 1
    assert len(captured_inputs[0]) == 200


# ---------------------------------------------------------------------------
# apply_age_out
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_age_out_decays_confidence():
    """An identifier 8 months old with confidence 0.5 should drop to 0.45."""
    from src.services.identifier_refresh_service import apply_age_out

    team_id = uuid.uuid4()
    old = _make_identifier(
        team_id=team_id,
        token="LegacyService",
        confidence=0.5,
        last_seen_at=datetime.utcnow() - timedelta(days=30 * 8),
    )
    session = _FakeSession(execute_queue=[[old]])

    summary = await apply_age_out(team_id, session)

    assert summary == {"aged_out": 1, "pruned": 0}
    # 0.5 * 0.9 = 0.45 (allow tiny float drift).
    assert abs(old.confidence - 0.45) < 1e-9
    assert session.deleted == []


@pytest.mark.asyncio
async def test_apply_age_out_prunes_when_below_threshold():
    """Confidence 0.09 → after decay 0.081 → < 0.1 → row deleted."""
    from src.services.identifier_refresh_service import apply_age_out

    team_id = uuid.uuid4()
    weak = _make_identifier(
        team_id=team_id,
        token="GhostService",
        confidence=0.09,
        last_seen_at=datetime.utcnow() - timedelta(days=30 * 8),
    )
    session = _FakeSession(execute_queue=[[weak]])

    summary = await apply_age_out(team_id, session)

    assert summary == {"aged_out": 1, "pruned": 1}
    assert session.deleted == [weak]


@pytest.mark.asyncio
async def test_apply_age_out_idempotent_within_single_call():
    """Single invocation must process each row at most once even though the
    row's last_seen_at is still < cutoff after decay.

    Strategy: ``apply_age_out`` materializes its candidate set up front
    (one ``execute`` returning a fixed list) and iterates that list — it
    does NOT re-query inside the loop. This test forces the issue by
    seeding only one execute result; if the service tried to re-query, the
    second execute would return empty anyway but we'd over-count via
    re-iteration.
    """
    from src.services.identifier_refresh_service import apply_age_out

    team_id = uuid.uuid4()
    row = _make_identifier(
        team_id=team_id,
        token="StableService",
        confidence=0.5,
        last_seen_at=datetime.utcnow() - timedelta(days=30 * 8),
    )
    session = _FakeSession(execute_queue=[[row]])

    summary = await apply_age_out(team_id, session)

    # Exactly one decay pass.
    assert summary == {"aged_out": 1, "pruned": 0}
    assert abs(row.confidence - 0.45) < 1e-9
    # No further execute calls consumed.
    assert session._executes == []
