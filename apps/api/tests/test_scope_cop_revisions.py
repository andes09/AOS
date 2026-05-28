"""Tests for /api/scope-cop/tickets/* (Initiative B, Wave 2 / SB-7).

Single-ticket revision endpoints. Uses the MagicMock-session + dependency
override pattern from ``tests/test_recalibration_router.py`` (the ``tmp_db``
SQLite fixture is unusable here because ``ticket_analyses`` carries JSONB).

The Jira client (``_get_jira_client``) and the Scope Cop service
(``analyze_tickets``) are patched at the router module namespace.

Coverage:
1. PATCH happy path — not stale → ``update_issue`` called with correctly mapped
   fields, a ``TicketRevision`` row added, scoring re-run.
2. PATCH stale → 409, no ``update_issue``, no audit row.
3. revision-preview returns the cached suggestion when present (no fresh run).
4. revision-preview runs a fresh analysis when no cached suggestion exists.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient, ASGITransport

from src.auth import get_current_org_id, get_current_user_id
from src.auth_roles import get_current_app_role
from src.database import get_db
from src.main import app
from src.models.ticket_revision import TicketRevision
import src.routers.scope_cop_revisions as rev_mod


ORG_CLERK_ID = "org_rev_test"
ORG_ID = uuid.uuid4()
TEAM_ID = uuid.uuid4()
TICKET_KEY = "PROJ-123"


# ---------------------------------------------------------------------------
# Doubles
# ---------------------------------------------------------------------------


def _make_team():
    t = MagicMock()
    t.id = TEAM_ID
    t.organization_id = ORG_ID
    return t


def _make_analysis_row(suggested_revision):
    row = MagicMock()
    row.team_id = TEAM_ID
    row.ticket_key = TICKET_KEY
    row.suggested_revision = suggested_revision
    return row


def _make_result(**overrides):
    r = MagicMock()
    r.ticket_key = TICKET_KEY
    r.ticket_title = "Updated title"
    r.readiness_score = 82
    r.status = "ready"
    r.issues = []
    r.suggestions = []
    r.stack_alignment = 3
    r.matched_identifier_count = 2
    r.suggested_revision = {"title": "Updated title"}
    r.fetched_updated_at = "2026-05-28T10:00:00.000+0000"
    for k, v in overrides.items():
        setattr(r, k, v)
    return r


def _jira_issue(updated="2026-05-28T09:00:00.000+0000"):
    return {
        "key": TICKET_KEY,
        "fields": {
            "summary": "Old title",
            "description": "Old description",
            "updated": updated,
            "customfield_10016": 3,
        },
    }


class FakeSession:
    """Async session with sequenced .scalar() results + add/commit recording."""

    def __init__(self, *, scalar_results=None):
        self._scalar_results = list(scalar_results or [])
        self.added: list = []
        self.commit_calls = 0

    async def scalar(self, _q):
        return self._scalar_results.pop(0) if self._scalar_results else None

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commit_calls += 1


def _override_auth(role="lead"):
    async def _org():
        return ORG_CLERK_ID

    async def _user():
        return "user_lead"

    async def _role():
        return role

    app.dependency_overrides[get_current_org_id] = _org
    app.dependency_overrides[get_current_user_id] = _user
    app.dependency_overrides[get_current_app_role] = _role


def _override_db(session):
    async def _gen():
        yield session

    app.dependency_overrides[get_db] = _gen


def _patch_jira(monkeypatch, client):
    async def _fake_get_jira_client(team, db):
        return client

    monkeypatch.setattr(rev_mod, "_get_jira_client", _fake_get_jira_client)


def _clear():
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# PATCH /tickets/{key}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_happy_path(monkeypatch):
    # scalar order: _resolve_team (team), _load_cached_suggestion (analysis row)
    session = FakeSession(
        scalar_results=[_make_team(), _make_analysis_row({"title": "Suggested"})]
    )
    _override_auth("lead")
    _override_db(session)

    jira = MagicMock()
    jira.check_stale = AsyncMock(return_value=False)
    jira.get_issue = AsyncMock(return_value=_jira_issue())
    jira.update_issue = AsyncMock(return_value={})
    _patch_jira(monkeypatch, jira)

    fake_analyze = AsyncMock(return_value=[_make_result()])
    monkeypatch.setattr(rev_mod, "analyze_tickets", fake_analyze)

    body = {
        "revision": {
            "title": "New title",
            "description": "New description",
            "acceptanceCriteria": ["AC one", "AC two"],
            "storyPoints": 5,
        },
        "fetchedUpdatedAt": "2026-05-28T09:00:00.000+0000",
        "teamId": str(TEAM_ID),
    }

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t"
        ) as c:
            r = await c.patch(f"/api/scope-cop/tickets/{TICKET_KEY}", json=body)
    finally:
        _clear()

    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["committed"] is True
    assert payload["result"]["ticketKey"] == TICKET_KEY
    assert payload["result"]["readinessScore"] == 82

    # update_issue called once with correctly mapped fields.
    jira.update_issue.assert_awaited_once()
    called_key, called_fields = jira.update_issue.await_args.args
    assert called_key == TICKET_KEY
    assert called_fields["summary"] == "New title"
    assert called_fields["customfield_10016"] == 5
    # AC folded into the description text.
    assert "New description" in called_fields["description"]
    assert "Acceptance Criteria:" in called_fields["description"]
    assert "- AC one" in called_fields["description"]

    # Audit row written.
    assert session.commit_calls == 1
    rows = [o for o in session.added if isinstance(o, TicketRevision)]
    assert len(rows) == 1
    audit = rows[0]
    assert audit.ticket_key == TICKET_KEY
    assert audit.team_id == TEAM_ID
    assert audit.suggested_revision == {"title": "Suggested"}
    assert audit.applied_revision["title"] == "New title"
    assert audit.applied_revision["story_points"] == 5
    assert audit.original_jira_state["key"] == TICKET_KEY

    # Re-scored.
    fake_analyze.assert_awaited_once()
    assert fake_analyze.await_args.kwargs["ticket_keys"] == [TICKET_KEY]


@pytest.mark.asyncio
async def test_patch_stale_returns_409(monkeypatch):
    session = FakeSession(scalar_results=[_make_team()])
    _override_auth("lead")
    _override_db(session)

    jira = MagicMock()
    jira.check_stale = AsyncMock(return_value=True)
    jira.get_issue = AsyncMock(return_value=_jira_issue())
    jira.update_issue = AsyncMock(return_value={})
    _patch_jira(monkeypatch, jira)

    fake_analyze = AsyncMock(return_value=[_make_result()])
    monkeypatch.setattr(rev_mod, "analyze_tickets", fake_analyze)

    body = {
        "revision": {"title": "New title"},
        "fetchedUpdatedAt": "2026-05-28T08:00:00.000+0000",
        "teamId": str(TEAM_ID),
    }

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t"
        ) as c:
            r = await c.patch(f"/api/scope-cop/tickets/{TICKET_KEY}", json=body)
    finally:
        _clear()

    assert r.status_code == 409, r.text
    assert "modified in Jira" in r.json()["detail"]
    jira.update_issue.assert_not_awaited()
    fake_analyze.assert_not_awaited()
    # No audit row, no commit.
    assert session.commit_calls == 0
    assert not [o for o in session.added if isinstance(o, TicketRevision)]


# ---------------------------------------------------------------------------
# GET /tickets/{key}/revision-preview
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_preview_returns_cached_suggestion(monkeypatch):
    cached = {"title": "Cached suggestion", "story_points": 8}
    # scalar order: _resolve_team (team), _load_cached_suggestion (row)
    session = FakeSession(scalar_results=[_make_team(), _make_analysis_row(cached)])
    _override_auth("lead")
    _override_db(session)

    jira = MagicMock()
    jira.get_issue = AsyncMock(return_value=_jira_issue())
    _patch_jira(monkeypatch, jira)

    fake_analyze = AsyncMock(return_value=[_make_result()])
    monkeypatch.setattr(rev_mod, "analyze_tickets", fake_analyze)

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t"
        ) as c:
            r = await c.get(
                f"/api/scope-cop/tickets/{TICKET_KEY}/revision-preview",
                params={"team_id": str(TEAM_ID)},
            )
    finally:
        _clear()

    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["suggestedRevision"] == cached
    assert payload["original"]["title"] == "Old title"
    assert payload["fetchedUpdatedAt"] == "2026-05-28T09:00:00.000+0000"
    # Cached present → no fresh analysis.
    fake_analyze.assert_not_awaited()


@pytest.mark.asyncio
async def test_preview_runs_fresh_when_no_cache(monkeypatch):
    # _load_cached_suggestion returns None → fresh analyze.
    session = FakeSession(scalar_results=[_make_team(), None])
    _override_auth("lead")
    _override_db(session)

    jira = MagicMock()
    jira.get_issue = AsyncMock(return_value=_jira_issue())
    _patch_jira(monkeypatch, jira)

    fresh = _make_result(suggested_revision={"title": "Freshly computed"})
    fake_analyze = AsyncMock(return_value=[fresh])
    monkeypatch.setattr(rev_mod, "analyze_tickets", fake_analyze)

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t"
        ) as c:
            r = await c.get(
                f"/api/scope-cop/tickets/{TICKET_KEY}/revision-preview",
                params={"team_id": str(TEAM_ID)},
            )
    finally:
        _clear()

    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["suggestedRevision"] == {"title": "Freshly computed"}
    fake_analyze.assert_awaited_once()
    assert fake_analyze.await_args.kwargs["ticket_keys"] == [TICKET_KEY]
