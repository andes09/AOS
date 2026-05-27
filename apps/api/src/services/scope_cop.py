"""
Scope Cop AI service — Claude evaluates ticket readiness on five criteria.

analyze_tickets():
  1. Fetches full ticket detail from Jira per key
  2. Joins per-ticket identifier-match counts from ticket_skill_analyses (Wave 1)
  3. Sends all tickets to Claude in a single prompt with five scoring criteria
  4. Upserts results to ticket_analyses with ON CONFLICT update
  5. Returns list of TicketAnalysisResult Pydantic objects

JSONB stash strategy for new fields (Wave 2):
  The ``ticket_analyses`` table is shared with downstream readers (routers,
  sprint_brain) that expect ``issues``/``suggestions`` to be ``list[str]``.
  We avoid a migration by stashing ``stack_alignment`` and
  ``matched_identifier_count`` as a sentinel dict prepended to the
  ``suggestions`` JSONB array, of the form
  ``{"_meta": True, "stack_alignment": <int>, "matched_identifier_count": <int|None>}``.
  Readers that iterate ``suggestions`` as strings should call
  ``_split_meta_from_suggestions()`` to peel the sentinel off (see helper below).
"""

import json
import logging
import uuid
from datetime import datetime, timezone

import anthropic
import httpx
from fastapi import HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.identifier import TicketSkillAnalysis
from src.models.organization import Organization
from src.models.team import Team
from src.services.encryption import decrypt

logger = logging.getLogger(__name__)

_MODEL = "claude-opus-4-6"


# ---------------------------------------------------------------------------
# Pydantic response model
# ---------------------------------------------------------------------------


class TicketAnalysisResult(BaseModel):
    ticket_key: str
    ticket_title: str
    readiness_score: int
    status: str  # "ready" | "needs_work" | "blocked"
    issues: list[str]
    suggestions: list[str]
    # Wave 2 (Initiative A): stack-alignment scoring. Optional for backward
    # compatibility — older cached rows / Claude responses that omit these
    # fields will surface as ``None`` without crashing the API contract.
    stack_alignment: int | None = None
    matched_identifier_count: int | None = None


# ---------------------------------------------------------------------------
# JSONB meta-sentinel helpers (Wave 2 — see module docstring)
# ---------------------------------------------------------------------------


def _make_meta_sentinel(stack_alignment: int | None, matched_count: int | None) -> dict:
    """Build the sentinel dict that gets prepended to the ``suggestions`` JSONB
    array to carry stack_alignment + matched_identifier_count without a schema
    migration. Downstream readers should detect ``_meta is True`` and skip.
    """
    return {
        "_meta": True,
        "stack_alignment": stack_alignment,
        "matched_identifier_count": matched_count,
    }


def _split_meta_from_suggestions(
    suggestions: list,
) -> tuple[list[str], int | None, int | None]:
    """Peel the meta sentinel (if present) off a stored ``suggestions`` array.

    Returns ``(string_suggestions, stack_alignment, matched_identifier_count)``.
    Used by router code that surfaces cached analyses so the sentinel never
    leaks into the API response as a stray "suggestion".
    """
    stack_alignment: int | None = None
    matched_count: int | None = None
    cleaned: list[str] = []
    for item in suggestions or []:
        if isinstance(item, dict) and item.get("_meta") is True:
            stack_alignment = item.get("stack_alignment")
            matched_count = item.get("matched_identifier_count")
            continue
        if isinstance(item, str):
            cleaned.append(item)
    return cleaned, stack_alignment, matched_count


# ---------------------------------------------------------------------------
# Claude tool schema — forces structured readiness output
# ---------------------------------------------------------------------------

_SCOPE_COP_TOOL: dict = {
    "name": "score_tickets",
    "description": (
        "Score each ticket on sprint readiness. "
        "Evaluate five criteria and return a structured assessment per ticket."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "ticketKey": {"type": "string"},
                        "ticketTitle": {"type": "string"},
                        "readinessScore": {
                            "type": "integer",
                            "description": "0–100 readiness score derived from the five criteria (5 × 20 pts).",
                        },
                        "status": {
                            "type": "string",
                            "enum": ["ready", "needs_work", "blocked"],
                            "description": ">=80 → ready, 50-79 → needs_work, <50 → blocked.",
                        },
                        "acceptance_criteria": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": 20,
                            "description": "0–20 pts. Testable success conditions clearly stated.",
                        },
                        "estimate": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": 20,
                            "description": "0–20 pts. Story-point value set and non-zero.",
                        },
                        "bounded_scope": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": 20,
                            "description": "0–20 pts. Single, clearly-scoped deliverable.",
                        },
                        "unambiguous_ownership": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": 20,
                            "description": "0–20 pts. Clear owner — no 'someone should' / 'TBD'.",
                        },
                        "stack_alignment": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": 20,
                            "description": (
                                "Whether the ticket touches the team's known stack. "
                                "20 = clearly does; 10 = vague; 0 = doesn't seem to."
                            ),
                        },
                        "matched_identifier_count": {
                            "type": "integer",
                            "description": (
                                "Echo of the count provided in the prompt — Claude should "
                                "pass through what it was given."
                            ),
                        },
                        "issues": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Specific problems found in this ticket.",
                        },
                        "suggestions": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Actionable improvements to bring the ticket to ready.",
                        },
                    },
                    "required": [
                        "ticketKey",
                        "ticketTitle",
                        "readinessScore",
                        "status",
                        "issues",
                        "suggestions",
                        "stack_alignment",
                        "matched_identifier_count",
                    ],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["results"],
        "additionalProperties": False,
    },
}

_SYSTEM_PROMPT = """\
You are an expert agile coach evaluating sprint ticket readiness.

Score each ticket from 0 to 100 based on 5 equally-weighted criteria (0–20 pts each):

1. **Acceptance criteria** (0–20 pts): Are testable success conditions explicitly stated \
   in the description or a dedicated AC field? Vague or absent → deduct.
2. **Estimate** (0–20 pts): Is a story point value set and non-zero? \
   Missing or zero estimate → 0 pts for this criterion.
3. **Bounded scope** (0–20 pts): Is this a single, clearly-scoped deliverable? \
   Compound tickets with "and also", "plus", or multiple unrelated goals → deduct.
4. **Unambiguous ownership** (0–20 pts): Is it clear who does the work? \
   Vague phrases like "someone should", "the team needs to", or "TBD" → deduct.
5. **Stack alignment** (0–20 pts): Does the ticket touch the team's known stack?
   - 20 pts: ticket clearly touches the team's stack (the supplied \
     `matched_identifier_count` confirms specific files / services / schemas).
   - 10 pts: vaguely on-stack but unclear, OR the count is "unknown" because \
     no identifier scan has run for this team (default to a neutral 10).
   - 0 pts: doesn't seem to touch the team's stack at all.
   - If `matched_identifier_count == 0`, cap `stack_alignment` at 5 and consider \
     setting status='needs_work' even when the other four criteria pass — the \
     ticket may be off-stack work for this team.

The total `readinessScore` should equal the sum of the five 0–20 sub-scores.

Status derived from score:
- >= 80  → "ready"
- 50–79  → "needs_work"
- < 50   → "blocked"

For each ticket, list concrete issues found and specific, actionable suggestions to fix them.
Echo the per-ticket `matched_identifier_count` you were given back in the response \
(use 0 if the prompt says "unknown" — but only after applying the neutral-10 rule above). \
Always respond by calling the score_tickets tool.\
"""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _fetch_ticket(jira_client, key: str) -> dict:
    """Fetch a single Jira issue: summary, description, story points."""
    url = (
        f"https://api.atlassian.com/ex/jira/{jira_client.cloud_id}"
        f"/rest/api/3/issue/{key}"
        "?fields=summary,description,story_points,customfield_10016,customfield_10028"
    )
    async with httpx.AsyncClient() as c:
        r = await c.get(url, headers=jira_client._headers())
        if r.status_code == 404:
            logger.warning("Jira issue %s not found — using stub entry", key)
            return {"key": key, "summary": key, "description": None, "story_points": None}
        r.raise_for_status()
        data = r.json()

    fields = data.get("fields", {})
    story_points = (
        fields.get("story_points")
        or fields.get("customfield_10016")
        or fields.get("customfield_10028")
    )
    description = fields.get("description")
    if isinstance(description, dict):
        description = _flatten_adf(description)

    return {
        "key": key,
        "summary": fields.get("summary") or key,
        "description": description,
        "story_points": story_points,
    }


def _flatten_adf(node: dict) -> str:
    """Recursively extract plain text from an Atlassian Document Format node."""
    parts: list[str] = []
    if node.get("type") == "text":
        parts.append(node.get("text", ""))
    for child in node.get("content", []):
        parts.append(_flatten_adf(child))
    return " ".join(p for p in parts if p).strip()


def _build_prompt(
    tickets: list[dict],
    match_counts: dict[str, int | None] | None = None,
) -> str:
    """Build the per-ticket prompt body.

    ``match_counts`` maps ticket_key → number of matched team identifiers
    (from ``ticket_skill_analyses.matched_identifiers``). A value of ``None``
    means we have no analysis row for that ticket — surfaced to Claude as
    "unknown" so the system prompt's neutral-10 rule applies.
    """
    match_counts = match_counts or {}
    lines = ["## Tickets to Evaluate", ""]
    for t in tickets:
        key = t["key"]
        lines.append(f"### {key}: {t['summary']}")
        pts = t.get("story_points")
        lines.append(f"Story points: {pts if pts is not None else 'NOT SET'}")
        mc = match_counts.get(key)
        mc_text = "unknown" if mc is None else str(mc)
        lines.append(f"{key} — matched_identifier_count: {mc_text}")
        desc = t.get("description") or "(no description provided)"
        lines.append(f"Description:\n{str(desc)[:1000]}")
        lines.append("")
    lines.append(
        "Evaluate each ticket against the five readiness criteria and call score_tickets."
    )
    return "\n".join(lines)


async def _fetch_match_counts(
    team_id: str,
    ticket_keys: list[str],
    db: AsyncSession,
) -> dict[str, int | None]:
    """Return ``{ticket_key: len(matched_identifiers) or None}``.

    Joins ``tickets`` (matched on team_id + jira_issue_key) to
    ``ticket_skill_analyses``. Tickets without an analysis row yield ``None``,
    which the prompt surfaces as "unknown".
    """
    from src.models.ticket import Ticket

    if not ticket_keys:
        return {}

    rows = (
        await db.execute(
            select(Ticket.jira_issue_key, TicketSkillAnalysis.matched_identifiers)
            .join(
                TicketSkillAnalysis,
                TicketSkillAnalysis.ticket_id == Ticket.id,
                isouter=True,
            )
            .where(Ticket.team_id == uuid.UUID(team_id))
            .where(Ticket.jira_issue_key.in_(ticket_keys))
        )
    ).all()

    counts: dict[str, int | None] = {k: None for k in ticket_keys}
    for jira_key, matched in rows:
        if matched is None:
            counts[jira_key] = None
        else:
            try:
                counts[jira_key] = len(matched)
            except TypeError:
                counts[jira_key] = None
    return counts


def _derive_status(score: int) -> str:
    if score >= 80:
        return "ready"
    if score >= 50:
        return "needs_work"
    return "blocked"


async def _get_anthropic_key(team_id: str, db: AsyncSession) -> str:
    """Resolve team → org → decrypted Anthropic key. Raises HTTP 402 if unset."""
    team = await db.scalar(
        select(Team).where(Team.id == uuid.UUID(team_id))
    )
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found.")

    org = await db.scalar(
        select(Organization).where(Organization.id == team.organization_id)
    )
    if not org or not org.encrypted_anthropic_key:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="No Anthropic API key configured. Please add your key in Settings.",
        )
    return decrypt(org.encrypted_anthropic_key)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def analyze_tickets(
    team_id: str,
    ticket_keys: list[str],
    jira_client,
    db: AsyncSession,
) -> list[TicketAnalysisResult]:
    """
    Fetch tickets from Jira, score readiness with Claude, upsert to DB.

    Args:
        team_id:     UUID string of the team (used for DB upsert and org key lookup).
        ticket_keys: List of Jira issue keys, e.g. ["PROJ-1", "PROJ-2"].
        jira_client: Authenticated JiraClient instance.
        db:          Async SQLAlchemy session.

    Returns:
        List of TicketAnalysisResult Pydantic objects, one per ticket key.

    Raises:
        HTTPException 402: org has no Anthropic API key configured.
        HTTPException 404: team not found.
        ValueError: invalid API key.
        RuntimeError: Claude API error or unexpected response.
    """
    # Resolve Anthropic key from team's org (BYOK)
    anthropic_api_key = await _get_anthropic_key(team_id, db)

    # 1. Fetch all tickets from Jira
    tickets: list[dict] = []
    for key in ticket_keys:
        ticket = await _fetch_ticket(jira_client, key)
        tickets.append(ticket)

    # 1b. Pull matched-identifier counts so Claude can score `stack_alignment`.
    # Missing analysis rows → None → "unknown" in the prompt.
    match_counts = await _fetch_match_counts(team_id, ticket_keys, db)

    # 2. Call Claude with all tickets in a single prompt
    client = anthropic.AsyncAnthropic(api_key=anthropic_api_key)
    try:
        response = await client.messages.create(
            model=_MODEL,
            max_tokens=4096,
            system=_SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": _build_prompt(tickets, match_counts)}
            ],
            tools=[_SCOPE_COP_TOOL],
            tool_choice={"type": "tool", "name": "score_tickets"},
        )
    except anthropic.AuthenticationError as exc:
        raise ValueError(
            "Invalid Anthropic API key. Please update your key in Settings."
        ) from exc
    except anthropic.RateLimitError as exc:
        raise RuntimeError(
            "Anthropic API rate limit reached. Please wait a moment and try again."
        ) from exc
    except anthropic.APIError as exc:
        raise RuntimeError(f"Anthropic API error: {exc.message}") from exc

    # 3. Extract Claude's structured tool call output
    tool_block = next(
        (b for b in response.content if b.type == "tool_use" and b.name == "score_tickets"),
        None,
    )
    if tool_block is None:
        raise RuntimeError(
            "Claude did not return a scope analysis. Please try again."
        )

    raw_results: list[dict] = tool_block.input["results"]

    # 4. Upsert each result to ticket_analyses
    now = datetime.utcnow()
    results: list[TicketAnalysisResult] = []

    for item in raw_results:
        score = int(item["readinessScore"])
        # Enforce score → status derivation (overrides any Claude enum mismatch)
        derived_status = _derive_status(score)
        ticket_title = item.get("ticketTitle") or item["ticketKey"]

        # Wave 2: parse new fields; tolerate Claude omitting them (backward compat).
        raw_stack = item.get("stack_alignment")
        stack_alignment = int(raw_stack) if isinstance(raw_stack, (int, float)) else None
        raw_match = item.get("matched_identifier_count")
        if isinstance(raw_match, (int, float)):
            matched_count: int | None = int(raw_match)
        else:
            # Fall back to the count we sent in the prompt (authoritative).
            matched_count = match_counts.get(item["ticketKey"])

        # Stash meta sentinel as first element of suggestions JSONB array.
        # See module docstring for rationale.
        clean_suggestions = list(item.get("suggestions", []))
        suggestions_to_persist: list = [
            _make_meta_sentinel(stack_alignment, matched_count),
            *clean_suggestions,
        ]

        await db.execute(
            text("""
                INSERT INTO ticket_analyses
                    (id, team_id, ticket_key, ticket_title,
                     readiness_score, status, issues, suggestions, analyzed_at)
                VALUES
                    (:id, :team_id, :ticket_key, :ticket_title,
                     :readiness_score, :status,
                     CAST(:issues AS jsonb), CAST(:suggestions AS jsonb), :analyzed_at)
                ON CONFLICT (team_id, ticket_key)
                DO UPDATE SET
                    ticket_title    = EXCLUDED.ticket_title,
                    readiness_score = EXCLUDED.readiness_score,
                    status          = EXCLUDED.status,
                    issues          = EXCLUDED.issues,
                    suggestions     = EXCLUDED.suggestions,
                    analyzed_at     = EXCLUDED.analyzed_at
            """),
            {
                "id": str(uuid.uuid4()),
                "team_id": str(team_id),
                "ticket_key": item["ticketKey"],
                "ticket_title": ticket_title,
                "readiness_score": score,
                "status": derived_status,
                "issues": json.dumps(item.get("issues", [])),
                "suggestions": json.dumps(suggestions_to_persist),
                "analyzed_at": now,
            },
        )
        results.append(
            TicketAnalysisResult(
                ticket_key=item["ticketKey"],
                ticket_title=ticket_title,
                readiness_score=score,
                status=derived_status,
                issues=item.get("issues", []),
                suggestions=clean_suggestions,
                stack_alignment=stack_alignment,
                matched_identifier_count=matched_count,
            )
        )

    await db.commit()
    return results
