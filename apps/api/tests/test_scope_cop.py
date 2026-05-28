"""Tests for ``src.services.scope_cop.analyze_tickets`` (Initiative A, Wave 2).

Mocks Anthropic + Jira + DB session via the MagicMock-style pattern used in
``tests/test_identifier_classifier.py`` and ``tests/test_identifiers_router.py``.

The project's ``tmp_db`` fixture is unusable here because the existing
``ticket_analyses.issues`` JSONB column cannot be rendered on SQLite — so we
substitute an async-aware DB session double.

Coverage:
1. ``_build_prompt`` (via ``analyze_tickets``) emits per-ticket
   ``matched_identifier_count`` lines for known counts.
2. Tickets without a ``ticket_skill_analyses`` row are surfaced as
   ``matched_identifier_count: unknown``.
3. Claude response with ``stack_alignment=3`` + ``matched_identifier_count=0``
   is preserved in the returned Pydantic AND persisted to the upsert.
4. Backward compat: Claude omits ``stack_alignment`` → Pydantic field defaults
   to ``None`` without crashing; ``matched_identifier_count`` falls back to the
   value we sent in the prompt.
5. The persisted ``suggestions`` JSONB starts with the meta sentinel, allowing
   downstream readers to ``_split_meta_from_suggestions`` it off.
6. ``_split_meta_from_suggestions`` round-trips cleanly.
"""
from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services import scope_cop as scope_cop_service
from src.services.scope_cop import (
    TicketAnalysisResult,
    _split_meta_from_suggestions,
    analyze_tickets,
)


TEAM_ID = str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Helpers
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
    """Minimal AsyncSession stand-in for analyze_tickets.

    - ``execute`` records every call's ``(stmt, params)``.
    - ``commit`` increments a counter.
    """

    def __init__(self) -> None:
        self.executes: list[tuple[object, dict | None]] = []
        self.commit_calls = 0
        # Used when ``_fetch_match_counts`` issues its SELECT — we patch the
        # helper directly in tests, so this fallback should never fire.
        self._match_count_rows: list[tuple] = []

    async def execute(self, stmt, params=None):  # noqa: ANN001
        self.executes.append((stmt, params))
        result = MagicMock()
        result.all = MagicMock(return_value=list(self._match_count_rows))
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
    """Install monkeypatches for the four external collaborators.

    Returns the AsyncMock for ``client.messages.create`` so tests can introspect
    the prompt that was sent.
    """
    async def _fake_key(team_id, db):  # noqa: ARG001
        return "sk-ant-test"

    async def _fake_fetch_ticket(jira_client, key):  # noqa: ARG001
        # Match ``tickets`` by key; fall back to a stub.
        for t in tickets:
            if t["key"] == key:
                return t
        return {"key": key, "summary": key, "description": None, "story_points": None}

    async def _fake_match_counts(team_id, ticket_keys, db):  # noqa: ARG001
        return {k: match_counts.get(k) for k in ticket_keys}

    monkeypatch.setattr(scope_cop_service, "_get_anthropic_key", _fake_key)
    monkeypatch.setattr(scope_cop_service, "_fetch_ticket", _fake_fetch_ticket)
    monkeypatch.setattr(scope_cop_service, "_fetch_match_counts", _fake_match_counts)

    # Patch the AsyncAnthropic client factory.
    create_mock = AsyncMock(return_value=_mock_tool_response(claude_results))
    fake_client = MagicMock()
    fake_client.messages.create = create_mock
    MockAsync = MagicMock(return_value=fake_client)
    monkeypatch.setattr(scope_cop_service.anthropic, "AsyncAnthropic", MockAsync)
    return create_mock


def _extract_prompt(create_mock: AsyncMock) -> str:
    """Return the user-content string that was sent to Claude."""
    call = create_mock.await_args
    msgs = call.kwargs["messages"]
    return msgs[0]["content"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prompt_includes_matched_identifier_count_lines(monkeypatch):
    tickets = [
        {"key": "PROJ-1", "summary": "Refactor OrderService",
         "description": "Touch OrderService.java", "story_points": 3},
        {"key": "PROJ-2", "summary": "Update docs",
         "description": "Edit README", "story_points": 1},
    ]
    claude_results = [
        {
            "ticketKey": "PROJ-1", "ticketTitle": "Refactor OrderService",
            "readinessScore": 88, "status": "ready",
            "issues": [], "suggestions": [],
            "stack_alignment": 18, "matched_identifier_count": 7,
        },
        {
            "ticketKey": "PROJ-2", "ticketTitle": "Update docs",
            "readinessScore": 60, "status": "needs_work",
            "issues": ["off-stack"], "suggestions": ["scope to docs only"],
            "stack_alignment": 5, "matched_identifier_count": 0,
        },
    ]
    db = _FakeDb()
    create_mock = _patch_common(
        monkeypatch,
        tickets=tickets,
        match_counts={"PROJ-1": 7, "PROJ-2": 0},
        claude_results=claude_results,
    )

    results = await analyze_tickets(
        team_id=TEAM_ID,
        ticket_keys=["PROJ-1", "PROJ-2"],
        jira_client=MagicMock(),
        db=db,
    )

    prompt = _extract_prompt(create_mock)
    assert "PROJ-1 — matched_identifier_count: 7" in prompt
    assert "PROJ-2 — matched_identifier_count: 0" in prompt
    assert len(results) == 2
    assert results[0].matched_identifier_count == 7
    assert results[1].matched_identifier_count == 0


@pytest.mark.asyncio
async def test_prompt_marks_missing_analyses_as_unknown(monkeypatch):
    tickets = [
        {"key": "PROJ-99", "summary": "New unscanned ticket",
         "description": "no scan run", "story_points": 5},
    ]
    claude_results = [
        {
            "ticketKey": "PROJ-99", "ticketTitle": "New unscanned ticket",
            "readinessScore": 80, "status": "ready",
            "issues": [], "suggestions": [],
            # Claude is told to default to neutral 10 when "unknown".
            "stack_alignment": 10, "matched_identifier_count": 0,
        },
    ]
    db = _FakeDb()
    # match_counts maps PROJ-99 → None (no analysis row).
    create_mock = _patch_common(
        monkeypatch,
        tickets=tickets,
        match_counts={"PROJ-99": None},
        claude_results=claude_results,
    )

    await analyze_tickets(
        team_id=TEAM_ID,
        ticket_keys=["PROJ-99"],
        jira_client=MagicMock(),
        db=db,
    )

    prompt = _extract_prompt(create_mock)
    assert "PROJ-99 — matched_identifier_count: unknown" in prompt


@pytest.mark.asyncio
async def test_low_stack_alignment_response_preserved_in_result_and_persisted(
    monkeypatch,
):
    tickets = [
        {"key": "PROJ-7", "summary": "Random off-stack work",
         "description": "rust + go", "story_points": 2},
    ]
    claude_results = [
        {
            "ticketKey": "PROJ-7", "ticketTitle": "Random off-stack work",
            "readinessScore": 55, "status": "needs_work",
            "issues": ["off-stack"], "suggestions": ["align to team stack"],
            "stack_alignment": 3, "matched_identifier_count": 0,
        },
    ]
    db = _FakeDb()
    _patch_common(
        monkeypatch,
        tickets=tickets,
        match_counts={"PROJ-7": 0},
        claude_results=claude_results,
    )

    results = await analyze_tickets(
        team_id=TEAM_ID,
        ticket_keys=["PROJ-7"],
        jira_client=MagicMock(),
        db=db,
    )

    # Pydantic carries the new fields.
    assert isinstance(results[0], TicketAnalysisResult)
    assert results[0].stack_alignment == 3
    assert results[0].matched_identifier_count == 0
    # Pydantic's `suggestions` is the clean list — no sentinel.
    assert results[0].suggestions == ["align to team stack"]

    # Persisted JSONB stash check: first INSERT param's `suggestions` payload
    # begins with the meta sentinel.
    insert_params = [p for _, p in db.executes if p and "suggestions" in p]
    assert insert_params, "no INSERT call captured"
    persisted = json.loads(insert_params[0]["suggestions"])
    assert isinstance(persisted, list)
    assert persisted[0] == {
        "_meta": True,
        "stack_alignment": 3,
        "matched_identifier_count": 0,
    }
    assert persisted[1:] == ["align to team stack"]


@pytest.mark.asyncio
async def test_backward_compat_missing_stack_alignment_defaults_to_none(monkeypatch):
    tickets = [
        {"key": "PROJ-50", "summary": "Legacy-shape response",
         "description": "x", "story_points": 1},
    ]
    # Claude returns OLD shape (no stack_alignment / matched_identifier_count).
    claude_results = [
        {
            "ticketKey": "PROJ-50", "ticketTitle": "Legacy-shape response",
            "readinessScore": 70, "status": "needs_work",
            "issues": [], "suggestions": ["add AC"],
        },
    ]
    db = _FakeDb()
    _patch_common(
        monkeypatch,
        tickets=tickets,
        match_counts={"PROJ-50": 4},  # prompt-side count is authoritative fallback
        claude_results=claude_results,
    )

    results = await analyze_tickets(
        team_id=TEAM_ID,
        ticket_keys=["PROJ-50"],
        jira_client=MagicMock(),
        db=db,
    )

    assert results[0].stack_alignment is None
    # When Claude omits the echo, we fall back to the value we sent (4).
    assert results[0].matched_identifier_count == 4


def test_split_meta_helper_roundtrip():
    persisted = [
        {"_meta": True, "stack_alignment": 12, "matched_identifier_count": 4},
        "first real suggestion",
        "second real suggestion",
    ]
    cleaned, stack, count = _split_meta_from_suggestions(persisted)
    assert cleaned == ["first real suggestion", "second real suggestion"]
    assert stack == 12
    assert count == 4

    # Older rows with no sentinel still return clean defaults.
    cleaned2, stack2, count2 = _split_meta_from_suggestions(["just a suggestion"])
    assert cleaned2 == ["just a suggestion"]
    assert stack2 is None
    assert count2 is None
