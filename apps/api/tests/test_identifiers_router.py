"""Tests for /api/identifiers/* (Initiative A, Wave 1).

Uses the MagicMock-session pattern (see test_sprints_router.py / test_alerts_router.py)
because the project's SQLite-based ``tmp_db`` fixture cannot render JSONB columns
on unrelated models (developers.skill_ratings) — a pre-existing limitation.

Covers:
- POST /scan empty-corpus → zero counts
- POST /scan happy path → identifiers persisted
- POST /scan idempotent re-scan increments occurrence_count
- POST /scan with low-confidence classification reflected in summary
- PATCH /{id} updates fields
- DELETE /{id} removes row
- Non-lead role → 403
- Foreign-org team_id → 404
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from unittest.mock import MagicMock

import pytest
from httpx import AsyncClient, ASGITransport

from src.auth import get_current_org_id, get_current_user_id
from src.auth_roles import get_current_app_role
from src.main import app
from src.models.identifier import TeamIdentifier
from src.services.identifier_classifier import ClassifiedIdentifier

ORG_CLERK_ID = "org_ident_test"
ORG_ID = uuid.uuid4()
TEAM_ID = uuid.uuid4()
OTHER_ORG_ID = uuid.uuid4()
OTHER_TEAM_ID = uuid.uuid4()
IDENT_ID = uuid.uuid4()


# ---------------------------------------------------------------------------
# Mock builders
# ---------------------------------------------------------------------------


def _make_org(clerk_id=ORG_CLERK_ID, id_=ORG_ID):
    o = MagicMock()
    o.id = id_
    o.clerk_org_id = clerk_id
    o.encrypted_anthropic_key = "enc"
    return o


def _make_team(team_id=TEAM_ID, org_id=ORG_ID, tech_stack=None):
    t = MagicMock(spec=[
        "id", "organization_id", "name", "tech_stack",
        "jira_board_id", "jira_project_key",
    ])
    t.id = team_id
    t.organization_id = org_id
    t.name = "Team A"
    t.tech_stack = json.dumps(tech_stack) if tech_stack else None
    return t


def _make_identifier(
    *, id_=IDENT_ID, team_id=TEAM_ID, token="OrderService",
    skill="unknown", domain=None, confidence=0.1, source="ticket_title",
    occurrence_count=3,
):
    r = MagicMock(spec=[
        "id", "team_id", "token", "normalized_token", "skill", "domain",
        "confidence", "source", "occurrence_count", "first_seen_at", "last_seen_at",
    ])
    r.id = id_
    r.team_id = team_id
    r.token = token
    r.normalized_token = token.lower()
    r.skill = skill
    r.domain = domain
    r.confidence = confidence
    r.source = source
    r.occurrence_count = occurrence_count
    r.first_seen_at = datetime(2026, 1, 1, 12, 0, 0)
    r.last_seen_at = datetime(2026, 1, 1, 12, 0, 0)
    return r


class _FakeSession:
    """Lightweight stand-in for AsyncSession that returns canned values in order.

    ``scalar_results`` is consumed sequentially per .scalar() call.
    ``scalars_results`` is consumed sequentially per .scalars() call (each result
    will yield .all() returning a list).
    """
    def __init__(self, scalar_results=None, scalars_results=None):
        self._scalars = list(scalar_results or [])
        self._scalars_list = list(scalars_results or [])
        self.added: list = []
        self.deleted: list = []
        self.commit_calls = 0

    async def scalar(self, _q):
        if not self._scalars:
            return None
        return self._scalars.pop(0)

    async def scalars(self, _q):
        m = MagicMock()
        m.all = MagicMock(return_value=self._scalars_list.pop(0) if self._scalars_list else [])
        return m

    def add(self, obj):
        self.added.append(obj)

    async def delete(self, obj):
        self.deleted.append(obj)

    async def commit(self):
        self.commit_calls += 1

    async def refresh(self, _obj):
        pass


def _override_auth(role: str = "lead", clerk_org_id: str = ORG_CLERK_ID):
    async def _org(): return clerk_org_id
    async def _user(): return "user_test"
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


def _patch_external(monkeypatch, *, classified=None, tickets=None, epics=None):
    classified = classified if classified is not None else []
    tickets = tickets if tickets is not None else []
    epics = epics if epics is not None else []

    async def fake_jira_client(team, db): return object()
    async def fake_anthropic_key(team_id, db): return "sk-test"
    async def fake_corpus(team_id, db, jira_client, max_tickets=500):
        return tickets, epics
    async def fake_classify(tokens, team_stack, anthropic_key, batch_size=50):
        return classified

    monkeypatch.setattr("src.routers.identifiers._get_jira_client", fake_jira_client)
    monkeypatch.setattr("src.routers.identifiers._get_anthropic_key", fake_anthropic_key)
    # Wave 3: scan core was extracted to identifier_scan_service. Patch there.
    monkeypatch.setattr(
        "src.services.identifier_scan_service.fetch_bootstrap_corpus", fake_corpus
    )
    monkeypatch.setattr(
        "src.services.identifier_scan_service.classify_identifiers", fake_classify
    )


# ---------------------------------------------------------------------------
# POST /scan
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_empty_corpus_returns_zero_counts(monkeypatch):
    team = _make_team(tech_stack=["Python"])
    org = _make_org()
    # _resolve_team_in_org calls db.scalar(Team) then db.scalar(Organization)
    session = _FakeSession(scalar_results=[team, org])
    _override_auth("lead"); _override_db(session)
    _patch_external(monkeypatch, classified=[], tickets=[], epics=[])

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.post("/api/identifiers/scan", json={"teamId": str(TEAM_ID)})
    finally:
        _clear()

    assert r.status_code == 200, r.text
    assert r.json() == {
        "tokensScanned": 0,
        "tokensClassified": 0,
        "identifiersPersisted": 0,
        "lowConfidenceCount": 0,
    }


@pytest.mark.asyncio
async def test_scan_happy_path_persists_new_identifiers(monkeypatch):
    from src.services.identifier_bootstrap_source import TicketTextSource

    team = _make_team(tech_stack=["Python", "PostgreSQL"])
    org = _make_org()

    tickets = [
        TicketTextSource(
            ticket_id=str(uuid.uuid4()), jira_issue_key="PROJ-1",
            title="Refactor OrderService and TaskList",
            description="Touches dbo.tile_metrics, ms-service",
            labels=["backend"], components=["payments"],
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
    # For each classified token, the upsert path does one db.scalar(TeamIdentifier...)
    # (existing lookup). Return None for each → triggers insert path.
    session = _FakeSession(scalar_results=[team, org, None, None])
    _override_auth("lead"); _override_db(session)
    _patch_external(monkeypatch, classified=classified, tickets=tickets, epics=[])

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.post("/api/identifiers/scan", json={"teamId": str(TEAM_ID)})
    finally:
        _clear()

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["identifiersPersisted"] == 2
    assert body["tokensClassified"] == 2
    assert body["lowConfidenceCount"] == 0
    # Two new TeamIdentifier rows added.
    new_rows = [o for o in session.added if isinstance(o, TeamIdentifier)]
    assert len(new_rows) == 2
    assert {r.token for r in new_rows} == {"OrderService", "dbo.tile_metrics"}
    assert session.commit_calls >= 1


@pytest.mark.asyncio
async def test_scan_idempotent_rescan_increments_occurrence_count(monkeypatch):
    from src.services.identifier_bootstrap_source import TicketTextSource

    team = _make_team(tech_stack=["Python"])
    org = _make_org()
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
    # Existing row found by db.scalar(TeamIdentifier...) — upsert hits UPDATE branch.
    existing = _make_identifier(token="OrderService", occurrence_count=5, skill="unknown")
    session = _FakeSession(scalar_results=[team, org, existing])
    _override_auth("lead"); _override_db(session)
    _patch_external(monkeypatch, classified=classified, tickets=tickets, epics=[])

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.post("/api/identifiers/scan", json={"teamId": str(TEAM_ID)})
    finally:
        _clear()

    assert r.status_code == 200, r.text
    # No new TeamIdentifier inserted.
    assert not any(isinstance(o, TeamIdentifier) for o in session.added)
    # Existing row's occurrence_count incremented (was 5, +1 from this scan).
    assert existing.occurrence_count == 6
    # Re-classification refines the label.
    assert existing.skill == "Python"
    assert existing.domain == "backend"
    assert existing.confidence == 0.9


@pytest.mark.asyncio
async def test_scan_low_confidence_reflected_in_summary(monkeypatch):
    from src.services.identifier_bootstrap_source import TicketTextSource

    team = _make_team(tech_stack=["Python"])
    org = _make_org()
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
    session = _FakeSession(scalar_results=[team, org, None])
    _override_auth("lead"); _override_db(session)
    _patch_external(monkeypatch, classified=classified, tickets=tickets, epics=[])

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.post("/api/identifiers/scan", json={"teamId": str(TEAM_ID)})
    finally:
        _clear()

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["lowConfidenceCount"] == 1
    assert body["identifiersPersisted"] == 1


# ---------------------------------------------------------------------------
# PATCH / DELETE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_updates_fields():
    team = _make_team()
    org = _make_org()
    row = _make_identifier()
    # _resolve_identifier_in_org: scalar(TeamIdentifier) → scalar(Team) → scalar(Org).
    session = _FakeSession(scalar_results=[row, team, org])
    _override_auth("lead"); _override_db(session)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.patch(
                f"/api/identifiers/{IDENT_ID}",
                json={"skill": "Python", "domain": "backend", "confidence": 0.95},
            )
    finally:
        _clear()

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["skill"] == "Python"
    assert body["domain"] == "backend"
    assert body["confidence"] == 0.95
    assert row.skill == "Python"
    assert row.domain == "backend"
    assert row.confidence == 0.95
    assert session.commit_calls == 1


@pytest.mark.asyncio
async def test_delete_removes_row():
    team = _make_team()
    org = _make_org()
    row = _make_identifier()
    session = _FakeSession(scalar_results=[row, team, org])
    _override_auth("lead"); _override_db(session)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.delete(f"/api/identifiers/{IDENT_ID}")
    finally:
        _clear()

    assert r.status_code == 204
    assert session.deleted == [row]
    assert session.commit_calls == 1


# ---------------------------------------------------------------------------
# AuthZ guards
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_lead_role_forbidden():
    session = _FakeSession()
    _override_auth("developer"); _override_db(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.post("/api/identifiers/scan", json={"teamId": str(TEAM_ID)})
    finally:
        _clear()
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_foreign_org_team_returns_404(monkeypatch):
    # Team belongs to a different org → org.clerk_org_id mismatch → 404.
    team = _make_team(team_id=OTHER_TEAM_ID, org_id=OTHER_ORG_ID)
    other_org = _make_org(clerk_id="org_other", id_=OTHER_ORG_ID)
    session = _FakeSession(scalar_results=[team, other_org])
    _override_auth("lead", clerk_org_id=ORG_CLERK_ID); _override_db(session)
    _patch_external(monkeypatch)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.post("/api/identifiers/scan", json={"teamId": str(OTHER_TEAM_ID)})
    finally:
        _clear()
    assert r.status_code == 404
