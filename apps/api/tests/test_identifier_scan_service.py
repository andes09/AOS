"""Tests for the extracted identifier_scan_service (Initiative A, Wave 3).

Covers:
- run_team_scan end-to-end with mocked Anthropic + mocked Jira corpus
- Empty corpus → zero-count summary, no DB writes
- Idempotent re-scan increments occurrence_count, refreshes label
- Low-confidence classifications counted in summary
- /import-history schedules the background scan (BackgroundTasks.add_task)
- Background scan swallows exceptions (does not propagate)
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from src.auth import get_current_org_id, get_current_user_id
from src.main import app
from src.models.identifier import TeamIdentifier
from src.services.identifier_classifier import ClassifiedIdentifier


# ---------------------------------------------------------------------------
# Mock helpers (mirror test_identifiers_router.py)
# ---------------------------------------------------------------------------


def _make_team(team_id=None, org_id=None, tech_stack=None):
    t = MagicMock(spec=[
        "id", "organization_id", "name", "tech_stack",
        "jira_board_id", "jira_project_key", "jira_import_status",
    ])
    t.id = team_id or uuid.uuid4()
    t.organization_id = org_id or uuid.uuid4()
    t.name = "Team A"
    t.tech_stack = json.dumps(tech_stack) if tech_stack else None
    t.jira_board_id = 1
    t.jira_project_key = "PROJ"
    t.jira_import_status = "complete"
    return t


def _make_identifier(*, team_id, token="OrderService", occurrence_count=5, skill="unknown"):
    r = MagicMock(spec=[
        "id", "team_id", "token", "normalized_token", "skill", "domain",
        "confidence", "source", "occurrence_count", "first_seen_at", "last_seen_at",
    ])
    r.id = uuid.uuid4()
    r.team_id = team_id
    r.token = token
    r.normalized_token = token.lower()
    r.skill = skill
    r.domain = None
    r.confidence = 0.1
    r.source = "ticket_title"
    r.occurrence_count = occurrence_count
    r.first_seen_at = datetime(2026, 1, 1, 12, 0, 0)
    r.last_seen_at = datetime(2026, 1, 1, 12, 0, 0)
    return r


class _FakeSession:
    """AsyncSession stub — sequential scalar() returns."""
    def __init__(self, scalar_results=None):
        self._scalars = list(scalar_results or [])
        self.added: list = []
        self.commit_calls = 0

    async def scalar(self, _q):
        if not self._scalars:
            return None
        return self._scalars.pop(0)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commit_calls += 1


# ---------------------------------------------------------------------------
# run_team_scan core behavior
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_team_scan_empty_corpus_returns_zero(monkeypatch):
    from src.services import identifier_scan_service as svc

    team = _make_team(tech_stack=["Python"])

    async def fake_corpus(team_id, db, jira_client, max_tickets=500):
        return [], []

    async def fake_classify(tokens, stack, key, batch_size=50):
        return []

    monkeypatch.setattr(svc, "fetch_bootstrap_corpus", fake_corpus)
    monkeypatch.setattr(svc, "classify_identifiers", fake_classify)

    session = _FakeSession()
    result = await svc.run_team_scan(
        team=team, jira_client=object(), anthropic_key="sk-test", db=session
    )
    assert result == {
        "tokens_scanned": 0,
        "tokens_classified": 0,
        "identifiers_persisted": 0,
        "low_confidence_count": 0,
    }
    assert session.added == []
    # Empty path returns early — no commit.
    assert session.commit_calls == 0


@pytest.mark.asyncio
async def test_run_team_scan_persists_new_identifiers(monkeypatch):
    from src.services import identifier_scan_service as svc
    from src.services.identifier_bootstrap_source import TicketTextSource

    team = _make_team(tech_stack=["Python", "PostgreSQL"])
    tickets = [
        TicketTextSource(
            ticket_id=str(uuid.uuid4()), jira_issue_key="PROJ-1",
            title="Refactor OrderService", description="Touches dbo.tile_metrics",
            labels=[], components=[],
        ),
    ]
    classified = [
        ClassifiedIdentifier(
            token="OrderService", normalized_token="orderservice",
            skill="Python", domain="backend", confidence=0.9, occurrence_count=1,
        ),
        ClassifiedIdentifier(
            token="dbo.tile_metrics", normalized_token="dbo.tile_metrics",
            skill="PostgreSQL", domain="data", confidence=0.85, occurrence_count=1,
        ),
    ]

    async def fake_corpus(team_id, db, jira_client, max_tickets=500):
        return tickets, []

    async def fake_classify(tokens, stack, key, batch_size=50):
        return classified

    monkeypatch.setattr(svc, "fetch_bootstrap_corpus", fake_corpus)
    monkeypatch.setattr(svc, "classify_identifiers", fake_classify)

    # Two upsert lookups, both miss → insert.
    session = _FakeSession(scalar_results=[None, None])
    result = await svc.run_team_scan(
        team=team, jira_client=object(), anthropic_key="sk-test", db=session
    )
    assert result["identifiers_persisted"] == 2
    assert result["tokens_classified"] == 2
    assert result["low_confidence_count"] == 0
    new_rows = [o for o in session.added if isinstance(o, TeamIdentifier)]
    assert {r.token for r in new_rows} == {"OrderService", "dbo.tile_metrics"}
    assert session.commit_calls == 1


@pytest.mark.asyncio
async def test_run_team_scan_idempotent_increments_count(monkeypatch):
    from src.services import identifier_scan_service as svc
    from src.services.identifier_bootstrap_source import TicketTextSource

    team = _make_team(tech_stack=["Python"])
    tickets = [
        TicketTextSource(
            ticket_id=str(uuid.uuid4()), jira_issue_key="PROJ-1",
            title="OrderService", description="", labels=[], components=[],
        ),
    ]
    classified = [
        ClassifiedIdentifier(
            token="OrderService", normalized_token="orderservice",
            skill="Python", domain="backend", confidence=0.9, occurrence_count=1,
        ),
    ]

    async def fake_corpus(team_id, db, jira_client, max_tickets=500):
        return tickets, []

    async def fake_classify(tokens, stack, key, batch_size=50):
        return classified

    monkeypatch.setattr(svc, "fetch_bootstrap_corpus", fake_corpus)
    monkeypatch.setattr(svc, "classify_identifiers", fake_classify)

    existing = _make_identifier(team_id=team.id, token="OrderService", occurrence_count=5)
    session = _FakeSession(scalar_results=[existing])
    result = await svc.run_team_scan(
        team=team, jira_client=object(), anthropic_key="sk-test", db=session
    )
    assert result["identifiers_persisted"] == 1
    assert not any(isinstance(o, TeamIdentifier) for o in session.added)
    assert existing.occurrence_count == 6
    assert existing.skill == "Python"
    assert existing.confidence == 0.9


@pytest.mark.asyncio
async def test_run_team_scan_low_confidence_counted(monkeypatch):
    from src.services import identifier_scan_service as svc
    from src.services.identifier_bootstrap_source import TicketTextSource

    team = _make_team(tech_stack=["Python"])
    tickets = [
        TicketTextSource(
            ticket_id=str(uuid.uuid4()), jira_issue_key="PROJ-1",
            title="OrderService", description="", labels=[], components=[],
        ),
    ]
    classified = [
        ClassifiedIdentifier(
            token="OrderService", normalized_token="orderservice",
            skill="unknown", domain=None, confidence=0.2, occurrence_count=1,
        ),
    ]

    async def fake_corpus(team_id, db, jira_client, max_tickets=500):
        return tickets, []

    async def fake_classify(tokens, stack, key, batch_size=50):
        return classified

    monkeypatch.setattr(svc, "fetch_bootstrap_corpus", fake_corpus)
    monkeypatch.setattr(svc, "classify_identifiers", fake_classify)

    session = _FakeSession(scalar_results=[None])
    result = await svc.run_team_scan(
        team=team, jira_client=object(), anthropic_key="sk-test", db=session
    )
    assert result["low_confidence_count"] == 1
    assert result["identifiers_persisted"] == 1


# ---------------------------------------------------------------------------
# /import-history schedules the background scan
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_import_history_schedules_identifier_scan_bg(monkeypatch):
    """The endpoint must enqueue the scan via BackgroundTasks and NOT block on it.

    We mock everything heavy (DB, Jira, import) and assert that
    BackgroundTasks.add_task was called with our scan helper.
    """
    from src.routers import onboarding as onboarding_module

    org_id = uuid.uuid4()
    team = _make_team(org_id=org_id)
    org = MagicMock()
    org.id = org_id
    org.clerk_org_id = "org_test"

    async def fake_resolve(clerk_org_id, db):
        return org, team

    async def fake_jira(_org, _db):
        return object()

    async def fake_import(team, jira_client, sprint_count, db):
        team.jira_import_status = "complete"

    monkeypatch.setattr(onboarding_module, "_resolve_org_and_team", fake_resolve)
    monkeypatch.setattr(onboarding_module, "_get_jira_client", fake_jira)
    monkeypatch.setattr(onboarding_module, "import_jira_sprint_history", fake_import)

    # Track add_task calls.
    add_task_calls: list = []
    real_add_task = None  # placeholder

    def spy_add_task(self_obj, func, *args, **kwargs):
        add_task_calls.append((func, args, kwargs))

    monkeypatch.setattr(
        "fastapi.BackgroundTasks.add_task", spy_add_task
    )

    # Override the FastAPI session dep with a no-op session.
    class _NoopSession:
        async def commit(self): pass
        async def flush(self): pass
        async def rollback(self): pass
        async def close(self): pass

    async def _get_db_override():
        yield _NoopSession()

    from src.database import get_db
    app.dependency_overrides[get_db] = _get_db_override
    app.dependency_overrides[get_current_org_id] = lambda: "org_test"
    app.dependency_overrides[get_current_user_id] = lambda: "user_test"

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.post("/api/onboarding/import-history", json={"sprintCount": 3})
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 202, r.text
    assert len(add_task_calls) == 1
    func, args, _kw = add_task_calls[0]
    assert func is onboarding_module._run_identifier_scan_bg
    # args = (team.id, org.id)
    assert args == (team.id, org.id)


# ---------------------------------------------------------------------------
# Background scan swallows failures
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_background_scan_swallows_exceptions(monkeypatch, caplog):
    """A failing scan must not propagate — onboarding completion is critical UX."""
    from src.routers import onboarding as onboarding_module

    team_id = uuid.uuid4()
    org_id = uuid.uuid4()

    # AsyncSessionLocal returns a context manager whose .scalar() raises.
    class _BoomSession:
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass
        async def scalar(self, _q):
            raise RuntimeError("DB explosion")

    monkeypatch.setattr(onboarding_module, "AsyncSessionLocal", lambda: _BoomSession())

    # Must not raise.
    await onboarding_module._run_identifier_scan_bg(team_id, org_id)
    # Should have logged the failure.
    assert any("identifier_scan_bg: failed" in rec.getMessage() for rec in caplog.records)
