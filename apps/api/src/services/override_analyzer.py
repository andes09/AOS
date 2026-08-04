"""Override pattern analyzer (M8c, Initiative A Wave 5).

Reads SprintPlanOverride history and emits RecalibrationProposal candidates
when a (developer, skill) pair or (identifier, suggested_skill) pair sees
``threshold`` (default: 3) same-direction overrides in the trailing
``lookback_days`` (default: 90).

Two algorithms:

1. ``skill_rating`` — A developer keeps getting reassigned AWAY from tickets
   whose skill_vector contains a particular skill with weight > 0.5. We
   propose lowering that developer's ``skill_ratings[skill]`` by 0.3
   (floored at 0). The dev's current rating becomes ``current_value``.

2. ``identifier_skill`` — A specific identifier token keeps being reassigned
   away (reason=skill_fit) to a target developer whose dominant skill is X,
   while the identifier is currently classified as Y (X != Y). We propose
   reclassifying the identifier to X.

The analyzer is intended to run periodically (e.g. nightly job) or on demand
from the recalibration router — not per request — so the queries optimize
for correctness over throughput.
"""
from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.developer import Developer
from src.models.identifier import TeamIdentifier, TicketSkillAnalysis
from src.models.recalibration_proposal import RecalibrationProposal
from src.models.sprint_plan_override import SprintPlanOverride
from src.models.ticket import Ticket

logger = logging.getLogger(__name__)

SKILL_THRESHOLD_WEIGHT = 0.5   # min skill_vector weight to count as a "skill ticket"
RATING_DECREMENT       = 0.3   # how much to suggest lowering a rating by
DEFAULT_LOOKBACK_DAYS  = 90
DEFAULT_THRESHOLD      = 3
DISMISSED_COOLDOWN_DAYS = 30


# ---------------------------------------------------------------------------
# detect_patterns
# ---------------------------------------------------------------------------


async def detect_patterns(
    team_id: str,
    db: AsyncSession,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    threshold: int = DEFAULT_THRESHOLD,
) -> list[dict[str, Any]]:
    """Return a list of proposal candidates (NOT persisted)."""
    try:
        team_uuid = uuid.UUID(str(team_id))
    except (ValueError, TypeError):
        # Returning [] here is indistinguishable from "no patterns found", so
        # log it — a malformed team_id means the caller is passing junk.
        logger.warning("detect_patterns: invalid team_id %r — returning no patterns", team_id)
        return []

    cutoff = datetime.utcnow() - timedelta(days=lookback_days)

    # ------------------------------------------------------------------
    # Pull all reassignment overrides for this team in the window.
    # We join through tickets to filter by team_id (overrides themselves
    # don't carry team_id; they carry sprint_id+ticket_id).
    # ------------------------------------------------------------------
    stmt = (
        select(SprintPlanOverride, Ticket.id)
        .join(Ticket, SprintPlanOverride.ticket_id == Ticket.id)
        .where(
            Ticket.team_id == team_uuid,
            SprintPlanOverride.reason_code == "skill_fit",
            SprintPlanOverride.created_at >= cutoff,
        )
    )
    rows = (await db.execute(stmt)).all()

    if not rows:
        return []

    # Collect ticket_ids so we can batch-fetch their skill analyses once.
    ticket_ids = list({r[1] for r in rows})
    analyses_stmt = select(TicketSkillAnalysis).where(
        TicketSkillAnalysis.ticket_id.in_(ticket_ids)
    )
    analyses = (await db.scalars(analyses_stmt)).all()
    analysis_by_ticket: dict[uuid.UUID, TicketSkillAnalysis] = {
        a.ticket_id: a for a in analyses
    }

    # ------------------------------------------------------------------
    # Algorithm 1: per-(developer, skill) counters where the overridden
    # ticket actually exercised that skill.
    # Algorithm 2: per-(identifier_id, target_dev) counters.
    # ------------------------------------------------------------------
    # skill_counts[(orig_dev, skill)] -> [override_id, ...]
    skill_counts: dict[tuple[uuid.UUID, str], list[str]] = defaultdict(list)
    # ident_target_counts[(identifier_id, target_dev_id)] -> [override_id, ...]
    ident_target_counts: dict[tuple[uuid.UUID, uuid.UUID], list[str]] = defaultdict(list)

    for override, ticket_id in rows:
        analysis = analysis_by_ticket.get(ticket_id)
        if analysis is None:
            continue

        # Skill rating algorithm: original_developer being reassigned away
        # from a skill-heavy ticket.
        if override.original_developer_id is not None:
            sv = analysis.skill_vector or {}
            for skill_name, weight in sv.items():
                try:
                    w = float(weight)
                except (TypeError, ValueError):
                    # Non-numeric weight = corrupt skill_vector on the analysis
                    # row; skipping it silently would hide the bad data forever.
                    logger.warning(
                        "detect_patterns: non-numeric skill weight, skipping",
                        extra={"skill": skill_name, "weight": repr(weight), "override_id": str(override.id)},
                    )
                    continue
                if w > SKILL_THRESHOLD_WEIGHT:
                    skill_counts[(override.original_developer_id, skill_name)].append(
                        str(override.id)
                    )

        # Identifier algorithm: per-(identifier, target_dev) counters.
        if override.new_developer_id is not None:
            for ident in (analysis.matched_identifiers or []):
                try:
                    ident_uuid = uuid.UUID(str(ident))
                except (ValueError, TypeError):
                    logger.warning(
                        "detect_patterns: malformed matched_identifier, skipping",
                        extra={"identifier": repr(ident), "override_id": str(override.id)},
                    )
                    continue
                ident_target_counts[(ident_uuid, override.new_developer_id)].append(
                    str(override.id)
                )

    # ------------------------------------------------------------------
    # Build skill_rating candidates.
    # Need current_value from Developer.skill_ratings.
    # ------------------------------------------------------------------
    candidates: list[dict[str, Any]] = []

    dev_ids_needed = {dev_id for (dev_id, _), evs in skill_counts.items() if len(evs) >= threshold}
    devs_by_id: dict[uuid.UUID, Developer] = {}
    if dev_ids_needed:
        dev_rows = (await db.scalars(
            select(Developer).where(Developer.id.in_(list(dev_ids_needed)))
        )).all()
        devs_by_id = {d.id: d for d in dev_rows}

    for (dev_id, skill_name), evidence in skill_counts.items():
        if len(evidence) < threshold:
            continue
        dev = devs_by_id.get(dev_id)
        if dev is None:
            continue
        ratings = dict(dev.skill_ratings or {})
        current = ratings.get(skill_name)
        try:
            current_val = float(current) if current is not None else 0.0
        except (TypeError, ValueError):
            current_val = 0.0
        suggested = max(0.0, current_val - RATING_DECREMENT)
        if suggested == current_val:
            # Already at floor; no useful suggestion.
            continue
        candidates.append({
            "kind": "skill_rating",
            "developer_id": str(dev_id),
            "skill": skill_name,
            "current_value": current_val,
            "suggested_value": suggested,
            "evidence": evidence,
        })

    # ------------------------------------------------------------------
    # Build identifier_skill candidates.
    # For each identifier token X: group its overrides by target_dev,
    # then pick the dev's dominant skill as the suggested reclassification.
    # ------------------------------------------------------------------
    if ident_target_counts:
        ident_ids_needed = list({k[0] for k in ident_target_counts.keys()})
        target_dev_ids_needed = list({k[1] for k in ident_target_counts.keys()})

        ident_rows = (await db.scalars(
            select(TeamIdentifier).where(TeamIdentifier.id.in_(ident_ids_needed))
        )).all()
        idents_by_id: dict[uuid.UUID, TeamIdentifier] = {i.id: i for i in ident_rows}

        target_devs = (await db.scalars(
            select(Developer).where(Developer.id.in_(target_dev_ids_needed))
        )).all()
        target_dev_by_id: dict[uuid.UUID, Developer] = {d.id: d for d in target_devs}

        # Aggregate (identifier, suggested_skill) -> evidence list, where
        # suggested_skill is the target dev's top-rated skill.
        ident_skill_evidence: dict[tuple[uuid.UUID, str], list[str]] = defaultdict(list)
        for (ident_uuid, target_dev_id), evidence in ident_target_counts.items():
            target_dev = target_dev_by_id.get(target_dev_id)
            if target_dev is None or not target_dev.skill_ratings:
                continue
            try:
                top_skill = max(target_dev.skill_ratings.items(), key=lambda kv: float(kv[1] or 0))[0]
            except (ValueError, TypeError):
                logger.warning(
                    "detect_patterns: unrankable skill_ratings, skipping developer",
                    extra={"developer_id": str(target_dev_id), "skill_ratings": repr(target_dev.skill_ratings)},
                )
                continue
            ident_skill_evidence[(ident_uuid, top_skill)].extend(evidence)

        for (ident_uuid, suggested_skill), evidence in ident_skill_evidence.items():
            if len(evidence) < threshold:
                continue
            ident = idents_by_id.get(ident_uuid)
            if ident is None:
                continue
            if ident.skill == suggested_skill:
                continue
            candidates.append({
                "kind": "identifier_skill",
                "identifier_id": str(ident_uuid),
                "skill": ident.skill,
                "suggested_skill": suggested_skill,
                "evidence": evidence,
            })

    return candidates


# ---------------------------------------------------------------------------
# persist_proposals
# ---------------------------------------------------------------------------


async def persist_proposals(
    team_id: str,
    candidates: list[dict[str, Any]],
    db: AsyncSession,
) -> int:
    """Persist candidates, skipping dupes (pending) and recently-dismissed."""
    if not candidates:
        return 0

    try:
        team_uuid = uuid.UUID(str(team_id))
    except (ValueError, TypeError):
        return 0

    # Pull existing proposals for this team that might conflict.
    cooldown_cutoff = datetime.utcnow() - timedelta(days=DISMISSED_COOLDOWN_DAYS)

    existing_stmt = select(RecalibrationProposal).where(
        RecalibrationProposal.team_id == team_uuid,
    )
    existing = (await db.scalars(existing_stmt)).all()

    # Build dedupe keys:
    # skill_rating  → (kind, developer_id, skill)
    # identifier    → (kind, identifier_id, suggested_skill)
    def _key(p: Any) -> tuple:
        if p.kind == "skill_rating":
            return ("skill_rating", str(p.developer_id), p.skill)
        if p.kind == "identifier_skill":
            return ("identifier_skill", str(p.identifier_id), p.suggested_skill)
        return ("unknown",)

    blocked: set[tuple] = set()
    for p in existing:
        if p.status == "pending":
            blocked.add(_key(p))
        elif p.status == "dismissed":
            if p.decided_at is not None and p.decided_at >= cooldown_cutoff:
                blocked.add(_key(p))

    inserted = 0
    for c in candidates:
        if c["kind"] == "skill_rating":
            key = ("skill_rating", c["developer_id"], c["skill"])
        elif c["kind"] == "identifier_skill":
            key = ("identifier_skill", c["identifier_id"], c["suggested_skill"])
        else:
            continue
        if key in blocked:
            continue

        row = RecalibrationProposal(
            id=uuid.uuid4(),
            team_id=team_uuid,
            kind=c["kind"],
            developer_id=uuid.UUID(c["developer_id"]) if c.get("developer_id") else None,
            identifier_id=uuid.UUID(c["identifier_id"]) if c.get("identifier_id") else None,
            skill=c.get("skill"),
            current_value=c.get("current_value"),
            suggested_value=c.get("suggested_value"),
            suggested_skill=c.get("suggested_skill"),
            evidence=c.get("evidence", []),
            status="pending",
        )
        db.add(row)
        blocked.add(key)  # avoid duplicates within the same batch
        inserted += 1

    if inserted:
        await db.commit()
    return inserted


# ---------------------------------------------------------------------------
# detect_and_persist
# ---------------------------------------------------------------------------


async def detect_and_persist(team_id: str, db: AsyncSession) -> int:
    candidates = await detect_patterns(team_id, db)
    return await persist_proposals(team_id, candidates, db)
