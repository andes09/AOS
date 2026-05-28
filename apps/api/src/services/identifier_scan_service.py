"""
Identifier bootstrap scan service (Initiative A, Wave 3).

Single source of truth for the bootstrap-scan pipeline:
corpus → tokenize → top-N cap → classify → upsert.

Two callers:
1. ``POST /api/identifiers/scan`` (routers/identifiers.py) — the interactive
   endpoint (thin wrapper around ``run_team_scan``).
2. The onboarding ``/import-history`` background task (routers/onboarding.py) —
   auto-triggers the same scan once Jira sprint history import completes, so
   the team's identifier glossary is ready by the time the lead lands on the
   Settings → Team Glossary page (SA-10).

The function is **idempotent**: re-running upserts (occurrence_count is
incremented for tokens that already exist, classification is refreshed).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.identifier import TeamIdentifier
from src.models.team import Team
from src.services.identifier_bootstrap_source import fetch_bootstrap_corpus
from src.services.identifier_classifier import classify_identifiers
from src.services.identifier_extraction import (
    ExtractedToken,
    count_tokens,
    extract_tokens,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tunables (kept here so the router and the background task share defaults)
# ---------------------------------------------------------------------------

TOP_N_TOKENS = 200
CLASSIFIER_BATCH_SIZE = 50
LOW_CONFIDENCE_THRESHOLD = 0.6


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_tech_stack(team: Team) -> list[str]:
    """``Team.tech_stack`` is stored as JSON-encoded ``list[str]``.

    Tolerant of ``None``, malformed JSON, or a legacy comma-separated string.
    Returns a deduped list of non-empty trimmed strings.
    """
    raw = team.tech_stack
    if not raw:
        return []
    items: list[str] = []
    if isinstance(raw, list):
        items = [str(x) for x in raw]
    else:
        try:
            decoded = json.loads(raw)
            if isinstance(decoded, list):
                items = [str(x) for x in decoded]
            elif isinstance(decoded, str):
                items = [decoded]
        except (json.JSONDecodeError, TypeError):
            items = [p for p in str(raw).split(",")]
    cleaned: list[str] = []
    seen: set[str] = set()
    for x in items:
        v = x.strip()
        if v and v.lower() not in seen:
            seen.add(v.lower())
            cleaned.append(v)
    return cleaned


# ---------------------------------------------------------------------------
# Core entry point
# ---------------------------------------------------------------------------


async def run_team_scan(
    *,
    team: Team,
    jira_client: Any,
    anthropic_key: str,
    db: AsyncSession,
) -> dict[str, int]:
    """Run a full bootstrap identifier scan and upsert results.

    Returns the same summary dict shape the ``/scan`` endpoint historically
    returned (camelCase mapping happens at the router boundary):

        {
            "tokens_scanned": int,
            "tokens_classified": int,
            "identifiers_persisted": int,
            "low_confidence_count": int,
        }

    Callers own the DB session lifecycle. This function calls ``await db.commit()``
    once at the end so a single scan is atomic; cross-cutting transactions
    should pass a dedicated session.
    """
    # 1. Fetch the closed-sprint corpus.
    tickets, epics = await fetch_bootstrap_corpus(
        team_id=str(team.id), db=db, jira_client=jira_client, max_tickets=500
    )

    # 2. Tokenize every text source.
    extracted: list[ExtractedToken] = []
    for t in tickets:
        if t.title:
            extracted.extend(extract_tokens(t.title, "ticket_title"))
        if t.description:
            extracted.extend(extract_tokens(t.description, "ticket_description"))
        for label in t.labels or []:
            norm = label.strip().lower()
            if len(norm) >= 3:
                extracted.append(ExtractedToken(token=label, normalized=norm, source="label"))
        for comp in t.components or []:
            norm = comp.strip().lower()
            if len(norm) >= 3:
                extracted.append(ExtractedToken(token=comp, normalized=norm, source="component"))
    for e in epics:
        if e.title:
            extracted.extend(extract_tokens(e.title, "epic"))
        if e.description:
            extracted.extend(extract_tokens(e.description, "epic"))

    if not extracted:
        return {
            "tokens_scanned": 0,
            "tokens_classified": 0,
            "identifiers_persisted": 0,
            "low_confidence_count": 0,
        }

    # First-seen source + raw form per normalized token.
    first_source: dict[str, str] = {}
    first_raw: dict[str, str] = {}
    for tok in extracted:
        first_source.setdefault(tok.normalized, tok.source)
        first_raw.setdefault(tok.normalized, tok.token)

    # 3. Aggregate frequencies and cap at TOP_N.
    counts = count_tokens(extracted)
    top_tokens = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:TOP_N_TOKENS]
    counts_by_norm = dict(top_tokens)

    # 4. Classify against the team's tech stack.
    classifier_input: list[tuple[str, str, int]] = [
        (first_raw.get(norm, norm), norm, cnt) for norm, cnt in top_tokens
    ]
    stack = _parse_tech_stack(team)
    classified = await classify_identifiers(
        classifier_input, stack, anthropic_key, batch_size=CLASSIFIER_BATCH_SIZE
    )

    # 5. Portable upsert (select-then-insert/update).
    now = datetime.utcnow()
    persisted = 0
    low_conf = 0
    for c in classified:
        norm = c.normalized_token
        raw = c.token
        source = first_source.get(norm, "ticket_description")
        delta_count = counts_by_norm.get(norm, c.occurrence_count or 1)

        existing = await db.scalar(
            select(TeamIdentifier).where(
                TeamIdentifier.team_id == team.id,
                TeamIdentifier.token == raw,
            )
        )
        if existing:
            existing.occurrence_count = (existing.occurrence_count or 0) + delta_count
            existing.last_seen_at = now
            existing.skill = c.skill
            existing.domain = c.domain
            existing.confidence = c.confidence
        else:
            db.add(TeamIdentifier(
                team_id=team.id,
                token=raw,
                normalized_token=norm,
                skill=c.skill,
                domain=c.domain,
                confidence=c.confidence,
                source=source,
                occurrence_count=delta_count,
                first_seen_at=now,
                last_seen_at=now,
            ))
        persisted += 1
        if c.confidence < LOW_CONFIDENCE_THRESHOLD:
            low_conf += 1

    await db.commit()

    return {
        "tokens_scanned": len(counts),
        "tokens_classified": len(classified),
        "identifiers_persisted": persisted,
        "low_confidence_count": low_conf,
    }
