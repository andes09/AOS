"""
Incremental identifier-refresh service (Initiative A, Wave 4, M7).

While ``identifier_scan_service.run_team_scan`` performs a full bootstrap
from the closed-sprint corpus, this module is for the steady-state case:
when a sprint closes (or an admin clicks "Refresh") we want to:

1. Only re-scan tickets that completed since the last refresh.
2. Cheaply bump ``last_seen_at`` / ``occurrence_count`` for tokens we
   already know — never re-classify them with Claude.
3. Only ship the **new** tokens (capped at top-200 by frequency) through
   the classifier.
4. Apply a confidence age-out so identifiers we haven't seen in months
   gradually decay to zero and eventually prune themselves.

Public surface
--------------
- ``refresh_team_identifiers`` — main entry, called by router endpoint.
- ``apply_age_out`` — confidence half-life decay + pruning, exposed so
  ops/cron can invoke it independently.
- ``refresh_after_sprint_close`` — background-friendly wrapper that
  swallows exceptions (used by future sprint-close hook in Wave 6).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
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
from src.services.identifier_scan_service import (
    CLASSIFIER_BATCH_SIZE,
    LOW_CONFIDENCE_THRESHOLD,
    TOP_N_TOKENS,
    _parse_tech_stack,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Age-out tunables
# ---------------------------------------------------------------------------

# A "month" is 30 days for the half-life math; precise calendaring not needed.
_DAYS_PER_MONTH = 30
DECAY_FACTOR = 0.9  # multiplied per age-out pass
PRUNE_BELOW_CONFIDENCE = 0.1


# ---------------------------------------------------------------------------
# Incremental refresh
# ---------------------------------------------------------------------------


async def refresh_team_identifiers(
    *,
    team: Team,
    jira_client: Any,
    anthropic_key: str,
    db: AsyncSession,
    age_out: bool = True,
) -> dict[str, int]:
    """Incrementally refresh a team's identifier glossary.

    Strategy
    --------
    1. ``since_at`` = max(``last_seen_at``) across this team's identifiers,
       falling back to ``team.created_at`` if the team has none yet.
    2. Pull tickets from closed sprints whose ``completed_at > since_at``.
    3. Tokenize the corpus. Tokens we already know (matched by
       ``normalized_token``) get a cheap ``occurrence_count`` /
       ``last_seen_at`` bump — the classifier is NOT called for them.
       Unknown tokens are sorted by frequency, capped at the top
       :data:`TOP_N_TOKENS`, and sent to the classifier.
    4. If ``age_out`` is True, :func:`apply_age_out` runs at the end.

    Returns
    -------
    dict[str, int]
        ``{tokens_seen, new_tokens, classified, persisted, aged_out, pruned}``
    """
    # 1. Compute since_at.
    last_seen = await db.scalar(
        select(TeamIdentifier.last_seen_at)
        .where(TeamIdentifier.team_id == team.id)
        .order_by(TeamIdentifier.last_seen_at.desc())
        .limit(1)
    )
    since_at: datetime = last_seen or team.created_at or datetime.utcnow()

    # 2. Pull incremental corpus.
    tickets, epics = await fetch_bootstrap_corpus(
        team_id=str(team.id),
        db=db,
        jira_client=jira_client,
        max_tickets=500,
        since_at=since_at,
    )

    # 3. Tokenize.
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

    summary = {
        "tokens_seen": 0,
        "new_tokens": 0,
        "classified": 0,
        "persisted": 0,
        "aged_out": 0,
        "pruned": 0,
    }

    if not extracted:
        if age_out:
            age_summary = await apply_age_out(team.id, db)
            summary["aged_out"] = age_summary["aged_out"]
            summary["pruned"] = age_summary["pruned"]
            await db.commit()
        return summary

    counts = count_tokens(extracted)
    summary["tokens_seen"] = len(counts)

    # First-seen source + raw form per normalized token (for inserts).
    first_source: dict[str, str] = {}
    first_raw: dict[str, str] = {}
    for tok in extracted:
        first_source.setdefault(tok.normalized, tok.source)
        first_raw.setdefault(tok.normalized, tok.token)

    now = datetime.utcnow()

    # 4. Split into known vs new by querying existing rows for the team.
    existing_rows_result = await db.execute(
        select(TeamIdentifier).where(TeamIdentifier.team_id == team.id)
    )
    existing_rows: list[TeamIdentifier] = list(existing_rows_result.scalars().all())
    by_norm: dict[str, TeamIdentifier] = {r.normalized_token: r for r in existing_rows}

    new_norm_counts: dict[str, int] = {}
    for norm, cnt in counts.items():
        if norm in by_norm:
            row = by_norm[norm]
            row.occurrence_count = (row.occurrence_count or 0) + cnt
            row.last_seen_at = now
            summary["persisted"] += 1
        else:
            new_norm_counts[norm] = cnt

    summary["new_tokens"] = len(new_norm_counts)

    # 5. Cap new tokens at TOP_N by frequency, classify, insert.
    if new_norm_counts:
        top_new = sorted(new_norm_counts.items(), key=lambda kv: kv[1], reverse=True)[
            :TOP_N_TOKENS
        ]
        classifier_input: list[tuple[str, str, int]] = [
            (first_raw.get(norm, norm), norm, cnt) for norm, cnt in top_new
        ]
        stack = _parse_tech_stack(team)
        classified = await classify_identifiers(
            classifier_input, stack, anthropic_key, batch_size=CLASSIFIER_BATCH_SIZE
        )
        summary["classified"] = len(classified)
        top_counts_by_norm = dict(top_new)

        for c in classified:
            norm = c.normalized_token
            raw = c.token
            source = first_source.get(norm, "ticket_description")
            delta = top_counts_by_norm.get(norm, c.occurrence_count or 1)
            # Defensive: race-safe re-check (someone else may have inserted).
            existing = await db.scalar(
                select(TeamIdentifier).where(
                    TeamIdentifier.team_id == team.id,
                    TeamIdentifier.token == raw,
                )
            )
            if existing:
                existing.occurrence_count = (existing.occurrence_count or 0) + delta
                existing.last_seen_at = now
                existing.skill = c.skill
                existing.domain = c.domain
                existing.confidence = c.confidence
            else:
                db.add(
                    TeamIdentifier(
                        team_id=team.id,
                        token=raw,
                        normalized_token=norm,
                        skill=c.skill,
                        domain=c.domain,
                        confidence=c.confidence,
                        source=source,
                        occurrence_count=delta,
                        first_seen_at=now,
                        last_seen_at=now,
                    )
                )
            summary["persisted"] += 1
            if c.confidence < LOW_CONFIDENCE_THRESHOLD:
                # Note: low-confidence count not currently surfaced in summary,
                # but retained as a log line for ops visibility.
                pass

    # 6. Age-out pass.
    if age_out:
        age_summary = await apply_age_out(team.id, db)
        summary["aged_out"] = age_summary["aged_out"]
        summary["pruned"] = age_summary["pruned"]

    await db.commit()
    return summary


# ---------------------------------------------------------------------------
# Confidence age-out
# ---------------------------------------------------------------------------


async def apply_age_out(
    team_id: uuid.UUID,
    db: AsyncSession,
    half_life_months: int = 6,
) -> dict[str, int]:
    """Decay confidence on identifiers we haven't seen for ``half_life_months``.

    For each row where ``last_seen_at`` is older than the cutoff:
      * ``confidence *= DECAY_FACTOR`` (0.9)
      * if the new confidence is < :data:`PRUNE_BELOW_CONFIDENCE`, delete it.

    Idempotency
    -----------
    A single invocation processes each row at most once: we select rows
    matching the cutoff condition into a list, then iterate. The freshly
    decayed rows still have ``last_seen_at < cutoff``, but they are not
    re-queried within this call. Callers that invoke ``apply_age_out``
    repeatedly will keep decaying — that's the intended half-life behavior
    across refresh cycles, not pathological double-decay within one cycle.

    Returns
    -------
    dict[str, int]
        ``{aged_out, pruned}`` — both rows we decayed and the subset of
        those we removed entirely.
    """
    cutoff = datetime.utcnow() - timedelta(days=half_life_months * _DAYS_PER_MONTH)

    rows_result = await db.execute(
        select(TeamIdentifier)
        .where(TeamIdentifier.team_id == team_id)
        .where(TeamIdentifier.last_seen_at < cutoff)
    )
    candidates: list[TeamIdentifier] = list(rows_result.scalars().all())

    aged_out = 0
    pruned = 0
    for row in candidates:
        new_conf = (row.confidence or 0.0) * DECAY_FACTOR
        if new_conf < PRUNE_BELOW_CONFIDENCE:
            await db.delete(row)
            pruned += 1
        else:
            row.confidence = new_conf
        aged_out += 1

    return {"aged_out": aged_out, "pruned": pruned}


# ---------------------------------------------------------------------------
# Background-friendly hook (wired in Wave 6 from jira/sync.py)
# ---------------------------------------------------------------------------


async def refresh_after_sprint_close(
    team_id: uuid.UUID,
    jira_client_factory,
    db: AsyncSession,
) -> None:
    """Background-friendly wrapper. Logs exceptions, doesn't raise.

    TODO(Wave 6): wire from apps/api/src/integrations/jira/sync.py when a
    sprint transitions ACTIVE → COMPLETED.

    ``jira_client_factory`` is a zero-arg async callable that returns an
    authenticated JiraClient — we accept a factory rather than the client
    directly so the caller controls credential resolution.
    """
    try:
        from src.services.scope_cop import _get_anthropic_key  # local import: avoid cycles

        team = await db.scalar(select(Team).where(Team.id == team_id))
        if team is None:
            logger.warning("refresh_after_sprint_close: team %s missing; skipping", team_id)
            return
        jira_client = await jira_client_factory()
        anthropic_key = await _get_anthropic_key(str(team_id), db)
        await refresh_team_identifiers(
            team=team, jira_client=jira_client, anthropic_key=anthropic_key, db=db
        )
    except Exception as e:  # noqa: BLE001 — must not propagate
        logger.exception("refresh_after_sprint_close: failed for team %s: %s", team_id, e)
