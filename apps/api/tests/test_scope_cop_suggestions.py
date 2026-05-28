"""Tests for the SB-4 ``suggested_revision`` payload produced by
``src.services.scope_cop.analyze_tickets``.

Mirrors the mocking pattern in ``tests/test_scope_cop.py`` — patches the Anthropic
client factory, ``_get_anthropic_key``, ``_fetch_ticket``, and
``_fetch_match_counts`` so the service runs end-to-end without I/O.

Coverage:
1. All four revision fields populated — round-trips into both the upsert payload
   and the returned Pydantic ``TicketAnalysisResult``.
2. Mixed nulls — only ``acceptance_criteria`` + ``story_points`` changed; the
   other fields stay ``None``.
3. Claude omits ``suggested_revision`` entirely — service must default to
   ``None`` on the Pydantic and persist SQL ``NULL`` (no JSON cast crash).
"""
from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.services import scope_cop as scope_cop_service
from src.services.scope_cop import TicketAnalysisResult, analyze_tickets


TEAM_ID = str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Helpers (copied verbatim from test_scope_cop.py to keep this file isolated)
# ---------------------------------------------------------------------------


def _mock_tool_response(results: list[dict]):
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.name = "score_tickets"
    tool_block.input = {"results": results}
    response = MagicMock()
    response.content = [tool_block]
    return response


class _FakeDb:
    def __init__(self) -> None:
        self.executes: list[tuple[object, dict | None]] = []
        self.commit_calls = 0

    async def execute(self, stmt, params=None):  # noqa: ANN001
        self.executes.append((stmt, params))
        result = MagicMock()
        result.all = MagicMock(return_value=[])
        return result

    async def commit(self) -> None:
        self.commit_calls += 1


def _patch_common(
    monkeypatch,
    *,
    tickets: list[dict],
    match_counts: dict[str, int | None],
    claude_results: list[dict],
):
    async def _fake_key(team_id, db):  # noqa: ARG001
        return "sk-ant-test"

    async def _fake_fetch_ticket(jira_client, key):  # noqa: ARG001
        for t in tickets:
            if t["key"] == key:
                return t
        return {"key": key, "summary": key, "description": None, "story_points": None}

    async def _fake_match_counts(team_id, ticket_keys, db):  # noqa: ARG001
        return {k: match_counts.get(k) for k in ticket_keys}

    monkeypatch.setattr(scope_cop_service, "_get_anthropic_key", _fake_key)
    monkeypatch.setattr(scope_cop_service, "_fetch_ticket", _fake_fetch_ticket)
    monkeypatch.setattr(scope_cop_service, "_fetch_match_counts", _fake_match_counts)

    create_mock = AsyncMock(return_value=_mock_tool_response(claude_results))
    fake_client = MagicMock()
    fake_client.messages.create = create_mock
    MockAsync = MagicMock(return_value=fake_client)
    monkeypatch.setattr(scope_cop_service.anthropic, "AsyncAnthropic", MockAsync)
    return create_mock


def _captured_insert_param(db: _FakeDb, key: str) -> dict:
    """Return the params dict of the INSERT for ``key`` (assumes one per ticket)."""
    for _, params in db.executes:
        if params and params.get("ticket_key") == key:
            return params
    raise AssertionError(f"no INSERT captured for {key}")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_four_revision_fields_round_trip(monkeypatch):
    tickets = [
        {
            "key": "PROJ-100",
            "summary": "vague ticket",
            "description": "do the thing",
            "story_points": None,
        },
    ]
    revision = {
        "title": "Refactor OrderService to extract pricing module",
        "description": (
            "Split the pricing calculations out of OrderService into a new "
            "PricingService class. Preserve existing public API on OrderService."
        ),
        "acceptance_criteria": [
            "PricingService exists with calculate_total method",
            "OrderService.total delegates to PricingService",
            "All existing OrderService tests still pass",
        ],
        "story_points": 5,
    }
    claude_results = [
        {
            "ticketKey": "PROJ-100",
            "ticketTitle": "vague ticket",
            "readinessScore": 45,
            "status": "blocked",
            "issues": ["no AC", "no estimate", "vague title"],
            "suggestions": ["clarify scope", "add AC", "estimate"],
            "stack_alignment": 18,
            "matched_identifier_count": 3,
            "suggested_revision": revision,
        },
    ]
    db = _FakeDb()
    _patch_common(
        monkeypatch,
        tickets=tickets,
        match_counts={"PROJ-100": 3},
        claude_results=claude_results,
    )

    results = await analyze_tickets(
        team_id=TEAM_ID,
        ticket_keys=["PROJ-100"],
        jira_client=MagicMock(),
        db=db,
    )

    assert isinstance(results[0], TicketAnalysisResult)
    assert results[0].suggested_revision == revision

    params = _captured_insert_param(db, "PROJ-100")
    persisted = json.loads(params["suggested_revision"])
    assert persisted == revision


@pytest.mark.asyncio
async def test_mixed_nulls_only_ac_and_story_points_changed(monkeypatch):
    tickets = [
        {
            "key": "PROJ-200",
            "summary": "Fine title, fine description, no AC, no estimate",
            "description": "Already clear what we're doing here.",
            "story_points": None,
        },
    ]
    revision = {
        "title": None,
        "description": None,
        "acceptance_criteria": [
            "Endpoint returns 200 on valid input",
            "Endpoint returns 400 on missing required field",
        ],
        "story_points": 3,
    }
    claude_results = [
        {
            "ticketKey": "PROJ-200",
            "ticketTitle": "Fine title, fine description, no AC, no estimate",
            "readinessScore": 60,
            "status": "needs_work",
            "issues": ["no AC", "no estimate"],
            "suggestions": ["add AC", "set story points"],
            "stack_alignment": 15,
            "matched_identifier_count": 2,
            "suggested_revision": revision,
        },
    ]
    db = _FakeDb()
    _patch_common(
        monkeypatch,
        tickets=tickets,
        match_counts={"PROJ-200": 2},
        claude_results=claude_results,
    )

    results = await analyze_tickets(
        team_id=TEAM_ID,
        ticket_keys=["PROJ-200"],
        jira_client=MagicMock(),
        db=db,
    )

    assert results[0].suggested_revision == revision
    assert results[0].suggested_revision["title"] is None
    assert results[0].suggested_revision["description"] is None
    assert results[0].suggested_revision["acceptance_criteria"] == revision["acceptance_criteria"]
    assert results[0].suggested_revision["story_points"] == 3

    params = _captured_insert_param(db, "PROJ-200")
    persisted = json.loads(params["suggested_revision"])
    assert persisted == revision


@pytest.mark.asyncio
async def test_claude_omits_suggested_revision_defaults_to_none(monkeypatch):
    """Backward-compat safety net: even though the tool schema requires the key,
    if Claude misbehaves and omits it the service must not crash — Pydantic
    field defaults to ``None`` and SQL persists NULL.
    """
    tickets = [
        {
            "key": "PROJ-300",
            "summary": "Already perfect ticket",
            "description": "Crystal clear.",
            "story_points": 3,
        },
    ]
    claude_results = [
        {
            "ticketKey": "PROJ-300",
            "ticketTitle": "Already perfect ticket",
            "readinessScore": 95,
            "status": "ready",
            "issues": [],
            "suggestions": [],
            "stack_alignment": 20,
            "matched_identifier_count": 5,
            # suggested_revision intentionally omitted
        },
    ]
    db = _FakeDb()
    _patch_common(
        monkeypatch,
        tickets=tickets,
        match_counts={"PROJ-300": 5},
        claude_results=claude_results,
    )

    results = await analyze_tickets(
        team_id=TEAM_ID,
        ticket_keys=["PROJ-300"],
        jira_client=MagicMock(),
        db=db,
    )

    assert results[0].suggested_revision is None

    params = _captured_insert_param(db, "PROJ-300")
    # When None, we pass SQL NULL (not the JSON string "null") so the cast
    # short-circuits cleanly.
    assert params["suggested_revision"] is None
