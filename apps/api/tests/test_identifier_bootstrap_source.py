"""
Unit tests for the identifier-bootstrap data-source helper.

These tests mock both the AsyncSession and the Jira client so they don't
require Postgres or network access.
"""
import os
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock

# Required env for src.* imports (mirrors conftest.py).
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("DATABASE_URL_SYNC", "postgresql://test:test@localhost/test")
os.environ.setdefault("CLERK_SECRET_KEY", "sk_test_dummy")
os.environ.setdefault("CLERK_PUBLISHABLE_KEY", "pk_test_dummy")
os.environ.setdefault("CLERK_WEBHOOK_SECRET", "whsec_dummy")
os.environ.setdefault("ENCRYPTION_KEY", "a" * 64)

from src.services.identifier_bootstrap_source import (  # noqa: E402
    fetch_bootstrap_corpus,
    _flatten_description,
    _extract_epic_key,
)
from src.models.ticket import Ticket  # noqa: E402


def _make_ticket(key: str, title: str = "T", labels=None, components=None) -> Ticket:
    """Build a Ticket ORM instance in-memory (no DB)."""
    t = Ticket(
        id=uuid.uuid4(),
        sprint_id=uuid.uuid4(),
        team_id=uuid.uuid4(),
        jira_issue_id=f"id-{key}",
        jira_issue_key=key,
        title=title,
        labels=labels or [],
        components=components or [],
    )
    return t


def _mock_db_returning(tickets):
    """Return a MagicMock AsyncSession whose db.execute(...) yields the given tickets."""
    db = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = tickets
    exec_result = MagicMock()
    exec_result.scalars.return_value = scalars
    db.execute = AsyncMock(return_value=exec_result)
    return db


def _issue_payload(
    key: str,
    description: str = "",
    epic: str | None = None,
    summary: str = "",
) -> dict:
    fields: dict = {
        "summary": summary,
        "description": description,
    }
    if epic is not None:
        fields["customfield_10014"] = epic
    return {"key": key, "fields": fields}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_returns_empty_when_no_completed_sprints():
    db = _mock_db_returning([])
    jira = MagicMock()
    jira.get_issue = AsyncMock()

    tickets, epics = await fetch_bootstrap_corpus(
        team_id=str(uuid.uuid4()), db=db, jira_client=jira
    )

    assert tickets == []
    assert epics == []
    jira.get_issue.assert_not_awaited()


@pytest.mark.asyncio
async def test_caps_at_max_tickets():
    # Even though we synthesize 7 tickets, the DB layer is what enforces the
    # LIMIT — so we simulate the cap by handing back exactly max_tickets.
    capped = [_make_ticket(f"PROJ-{i}") for i in range(3)]
    db = _mock_db_returning(capped)
    jira = MagicMock()
    jira.get_issue = AsyncMock(
        side_effect=lambda k: _issue_payload(k, description="x", epic=None)
    )

    tickets, _ = await fetch_bootstrap_corpus(
        team_id=str(uuid.uuid4()), db=db, jira_client=jira, max_tickets=3
    )

    assert len(tickets) == 3
    # Verify the LIMIT clause was applied on the query (best-effort check).
    issued_stmt = db.execute.call_args.args[0]
    compiled = str(issued_stmt)
    assert "LIMIT" in compiled.upper() or "limit" in compiled


@pytest.mark.asyncio
async def test_jira_failure_on_one_ticket_does_not_abort():
    t1 = _make_ticket("PROJ-1")
    t2 = _make_ticket("PROJ-2")
    t3 = _make_ticket("PROJ-3")
    db = _mock_db_returning([t1, t2, t3])

    async def _get(key):
        if key == "PROJ-2":
            raise RuntimeError("jira 500")
        return _issue_payload(key, description=f"desc-{key}", epic=None)

    jira = MagicMock()
    jira.get_issue = AsyncMock(side_effect=_get)

    tickets, epics = await fetch_bootstrap_corpus(
        team_id=str(uuid.uuid4()), db=db, jira_client=jira
    )

    assert len(tickets) == 3  # all three returned
    by_key = {t.jira_issue_key: t for t in tickets}
    assert by_key["PROJ-1"].description == "desc-PROJ-1"
    assert by_key["PROJ-3"].description == "desc-PROJ-3"
    # The failed one falls back to empty description, not dropped.
    assert by_key["PROJ-2"].description == ""
    assert epics == []


@pytest.mark.asyncio
async def test_epic_deduplication():
    # 5 tickets sharing 2 unique epic keys.
    pairings = [
        ("PROJ-1", "EPIC-A"),
        ("PROJ-2", "EPIC-A"),
        ("PROJ-3", "EPIC-B"),
        ("PROJ-4", "EPIC-B"),
        ("PROJ-5", "EPIC-A"),
    ]
    tickets_in = [_make_ticket(k) for k, _ in pairings]
    db = _mock_db_returning(tickets_in)

    epic_to_key = dict(pairings)

    async def _get(key):
        if key.startswith("EPIC-"):
            return _issue_payload(
                key, description=f"epic-desc-{key}", summary=f"Epic {key}"
            )
        return _issue_payload(key, description="", epic=epic_to_key[key])

    jira = MagicMock()
    jira.get_issue = AsyncMock(side_effect=_get)

    tickets, epics = await fetch_bootstrap_corpus(
        team_id=str(uuid.uuid4()), db=db, jira_client=jira
    )

    assert len(tickets) == 5
    assert len(epics) == 2
    returned_epic_keys = sorted(e.jira_issue_key for e in epics)
    assert returned_epic_keys == ["EPIC-A", "EPIC-B"]
    # Each epic fetched exactly once (not three times for EPIC-A).
    epic_call_keys = [
        c.args[0] for c in jira.get_issue.await_args_list if c.args[0].startswith("EPIC-")
    ]
    assert sorted(epic_call_keys) == ["EPIC-A", "EPIC-B"]


# ---------------------------------------------------------------------------
# Small unit coverage for the helper parsers (cheap, no async).
# ---------------------------------------------------------------------------


def test_flatten_description_handles_str_and_adf_and_none():
    assert _flatten_description(None) == ""
    assert _flatten_description("hello world") == "hello world"
    adf = {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "foo"}]},
            {"type": "paragraph", "content": [{"type": "text", "text": "bar"}]},
        ],
    }
    assert _flatten_description(adf) == "foo bar"


def test_extract_epic_key_classic_and_next_gen():
    # Classic: customfield_10014
    assert _extract_epic_key({"fields": {"customfield_10014": "EPIC-1"}}) == "EPIC-1"
    # Next-gen: parent is an epic
    next_gen = {
        "fields": {
            "parent": {
                "key": "EPIC-2",
                "fields": {"issuetype": {"name": "Epic"}},
            }
        }
    }
    assert _extract_epic_key(next_gen) == "EPIC-2"
    # Parent that is a story should NOT be treated as an epic
    story_parent = {
        "fields": {
            "parent": {
                "key": "PROJ-9",
                "fields": {"issuetype": {"name": "Story"}},
            }
        }
    }
    assert _extract_epic_key(story_parent) is None
    # No epic info at all
    assert _extract_epic_key({"fields": {}}) is None
