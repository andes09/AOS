"""
Data-source helper for the M2 identifier-bootstrap scan.

Pulls closed-sprint tickets + their epics for a single team so that the
tokenizer (SA-2) and bootstrap-scan endpoint (SA-5) can extract identifier
candidates from real historical text.

Read-only. Caller owns the AsyncSession + authenticated JiraClient.

------------------------------------------------------------------
Known gap (flagged for Wave-1 SA-5):
  The current `JiraClient` in `src/integrations/jira/client.py` does NOT
  expose a `get_issue(key)` method that returns the full issue payload
  (description + epic link). The closest existing method is
  `get_issue_links(issue_key)` which hits GET /rest/api/3/issue/{key} but
  only requests fields=issuelinks,summary.

  This helper duck-types `jira_client.get_issue(key)` and expects it to
  return a dict shaped like Jira's REST API issue payload:
      {
        "key": "PROJ-123",
        "fields": {
          "description": <ADF dict | str | None>,
          "customfield_10014": "PROJ-99"   # epic link (Jira Cloud default)
          # ...or "parent": {"key": "PROJ-99"} for next-gen projects
        }
      }

  SA-5 will need to either:
    (a) add `async def get_issue(self, key: str) -> dict` to JiraClient,
        calling GET /rest/api/3/issue/{key}?fields=description,customfield_10014,parent,summary
    (b) pass a thin adapter into this helper.
------------------------------------------------------------------
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.sprint import Sprint, SprintStatus
from src.models.ticket import Ticket

logger = logging.getLogger(__name__)

# Jira Cloud's default field for the epic link on classic projects.
# Next-gen projects use the "parent" field instead — we check both.
_EPIC_LINK_CUSTOMFIELD = "customfield_10014"

# Conservative concurrency cap. Simulator load-tests showed sustained
# org-wide rate-limits around 10 req/sec; 5 keeps us comfortably under
# while still being ~5x faster than serial.
_JIRA_FETCH_CONCURRENCY = 5


@dataclass
class TicketTextSource:
    ticket_id: str          # UUID as str
    jira_issue_key: str | None
    title: str
    description: str        # may be empty
    labels: list[str]
    components: list[str]


@dataclass
class EpicTextSource:
    jira_issue_key: str
    title: str
    description: str


def _flatten_description(raw) -> str:
    """Jira Cloud returns ADF (Atlassian Document Format) dicts for descriptions.
    For tokenization we only need flat text — walk the doc and concat text nodes.
    Accepts None / str / dict.
    """
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        out: list[str] = []

        def walk(node):
            if isinstance(node, dict):
                if node.get("type") == "text" and "text" in node:
                    out.append(node["text"])
                for child in node.get("content", []) or []:
                    walk(child)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(raw)
        return " ".join(out)
    return ""


def _extract_epic_key(issue_payload: dict) -> str | None:
    fields = issue_payload.get("fields", {}) or {}
    # Classic projects: customfield_10014 holds the parent epic key.
    epic = fields.get(_EPIC_LINK_CUSTOMFIELD)
    if isinstance(epic, str) and epic:
        return epic
    # Next-gen projects: parent issue is the epic.
    parent = fields.get("parent")
    if isinstance(parent, dict):
        parent_type = (parent.get("fields", {}) or {}).get("issuetype", {}) or {}
        # Only follow parent when it's actually an epic — otherwise it's a
        # sub-task's story parent which would pollute the corpus.
        if (parent_type.get("name") or "").lower() == "epic":
            return parent.get("key")
        # If issuetype isn't included in payload, fall back to using the
        # parent key anyway — better to over-fetch than miss an epic.
        if not parent_type:
            return parent.get("key")
    return None


async def _safe_get_issue(jira_client, key: str) -> dict | None:
    """Single-issue fetch wrapped so that one failure doesn't sink the bootstrap."""
    try:
        return await jira_client.get_issue(key)
    except Exception as e:  # noqa: BLE001 — Jira can raise httpx, fastapi.HTTPException, etc.
        logger.warning("identifier-bootstrap: skipping Jira issue %s — %s", key, e)
        return None


async def _gather_with_limit(coros, concurrency: int):
    sem = asyncio.Semaphore(concurrency)

    async def _runner(coro):
        async with sem:
            return await coro

    return await asyncio.gather(*[_runner(c) for c in coros])


async def fetch_bootstrap_corpus(
    team_id: str,
    db: AsyncSession,
    jira_client,
    max_tickets: int = 500,
) -> tuple[list[TicketTextSource], list[EpicTextSource]]:
    """Return (tickets, epics) from this team's closed-sprint history.

    Tickets: from `tickets` JOIN `sprints` where sprint.status = COMPLETED,
             ordered by sprint creation desc, capped at `max_tickets`.
             Description fetched from Jira per ticket.
    Epics:   each ticket's epic link is followed via Jira; deduped by key.

    Failures on individual Jira fetches are isolated — affected
    tickets/epics simply have empty descriptions or are skipped.
    """
    # Coerce team_id (caller may pass str or UUID).
    team_uuid = uuid.UUID(team_id) if isinstance(team_id, str) else team_id

    stmt = (
        select(Ticket)
        .join(Sprint, Ticket.sprint_id == Sprint.id)
        .where(Ticket.team_id == team_uuid)
        .where(Sprint.status == SprintStatus.COMPLETED)
        .order_by(Sprint.created_at.desc())
        .limit(max_tickets)
    )
    result = await db.execute(stmt)
    tickets: list[Ticket] = list(result.scalars().all())

    if not tickets:
        return [], []

    # --- Fetch each ticket's Jira payload (concurrent, bounded) ---
    fetch_keys = [t.jira_issue_key for t in tickets if t.jira_issue_key]
    payloads_list = await _gather_with_limit(
        [_safe_get_issue(jira_client, k) for k in fetch_keys],
        concurrency=_JIRA_FETCH_CONCURRENCY,
    )
    payloads_by_key: dict[str, dict] = {
        k: p for k, p in zip(fetch_keys, payloads_list) if p is not None
    }

    # --- Build TicketTextSource list ---
    ticket_sources: list[TicketTextSource] = []
    epic_keys: set[str] = set()
    for t in tickets:
        payload = payloads_by_key.get(t.jira_issue_key) if t.jira_issue_key else None
        description = ""
        if payload:
            description = _flatten_description(
                (payload.get("fields") or {}).get("description")
            )
            epic_key = _extract_epic_key(payload)
            if epic_key:
                epic_keys.add(epic_key)
        ticket_sources.append(
            TicketTextSource(
                ticket_id=str(t.id),
                jira_issue_key=t.jira_issue_key,
                title=t.title or "",
                description=description,
                labels=list(t.labels or []),
                components=list(t.components or []),
            )
        )

    # --- Fetch each unique epic once ---
    epic_keys_list = sorted(epic_keys)
    epic_payloads = await _gather_with_limit(
        [_safe_get_issue(jira_client, k) for k in epic_keys_list],
        concurrency=_JIRA_FETCH_CONCURRENCY,
    )

    epic_sources: list[EpicTextSource] = []
    for key, payload in zip(epic_keys_list, epic_payloads):
        if payload is None:
            continue
        fields = payload.get("fields", {}) or {}
        epic_sources.append(
            EpicTextSource(
                jira_issue_key=payload.get("key") or key,
                title=fields.get("summary") or "",
                description=_flatten_description(fields.get("description")),
            )
        )

    return ticket_sources, epic_sources
