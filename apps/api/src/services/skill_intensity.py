"""Per-ticket skill & domain intensity inference.

Pure-Python computation (no Claude, no router) that turns a single ticket plus
its team's learned ``TeamIdentifier`` rows into normalized skill and domain
intensity vectors.

Algorithm summary
-----------------
1. Tokenize all four text sources (title, description, labels, components) via
   :mod:`src.services.identifier_extraction`.
2. For each extracted normalized token, look up the matching ``TeamIdentifier``
   (by ``normalized_token``) for the team.
3. Per match, accumulate a score onto the matched skill (and domain, if any):
   ``confidence * verb_weight * effort_multiplier``.
4. ``verb_weight`` is determined by scanning up to 3 word-positions back in the
   identifier's source text. High-intensity verb -> 1.5; low-intensity -> 0.5;
   otherwise 1.0.
5. Normalize skill scores so the max skill = 1.0 (so vectors are comparable
   across tickets). Same for domain.
6. Round all output to 3 decimals.

No DB I/O happens in :func:`compute_intensity` — it's a pure function. The
upsert lives in :func:`persist_intensity`, and :func:`compute_and_persist`
glues them together.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.identifier import TicketSkillAnalysis
from src.services.identifier_extraction import extract_tokens, normalize_token


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass
class SkillIntensityResult:
    """Outcome of :func:`compute_intensity` for a single ticket."""

    skill_vector: dict[str, float] = field(default_factory=dict)
    domain_vector: dict[str, float] = field(default_factory=dict)
    matched_identifiers: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Verb tables (module constants)
# ---------------------------------------------------------------------------


HIGH_INTENSITY_VERBS: frozenset[str] = frozenset(
    {
        "design", "architect", "implement", "build", "rewrite", "refactor",
        "optimize", "migrate", "redesign", "introduce", "develop", "construct",
    }
)

LOW_INTENSITY_VERBS: frozenset[str] = frozenset(
    {
        "read", "fetch", "select", "query", "view", "display", "show",
        "log", "monitor", "observe", "check",
    }
)

_VERB_WINDOW = 3
_WORD_SPLIT = re.compile(r"\W+")


# ---------------------------------------------------------------------------
# Verb-context helpers
# ---------------------------------------------------------------------------


def _word_positions(text: str) -> list[tuple[str, int]]:
    """Return ``(lowercased_word, start_offset)`` tuples for each word in text.

    Uses ``re.finditer`` with a word-character pattern so we know each word's
    character offset, which lets us locate identifiers by position rather than
    by string match (avoiding ambiguity when an identifier appears twice).
    """
    return [(m.group(0).lower(), m.start()) for m in re.finditer(r"\w[\w./-]*", text)]


def _verb_weight_for_offset(words: list[tuple[str, int]], char_offset: int) -> float:
    """Find the word at ``char_offset`` and check the prior 3 words for a verb.

    Returns 1.5 for high-intensity, 0.5 for low-intensity, 1.0 otherwise.
    Case-insensitive. ``words`` must come from :func:`_word_positions` on the
    same source text.
    """
    # Locate index of the matched word by char offset.
    idx = None
    for i, (_, off) in enumerate(words):
        if off == char_offset:
            idx = i
            break
    if idx is None:
        return 1.0

    start = max(0, idx - _VERB_WINDOW)
    for prior, _ in words[start:idx]:
        stripped = prior.strip(".,;:()[]").lower()
        if stripped in HIGH_INTENSITY_VERBS:
            return 1.5
        if stripped in LOW_INTENSITY_VERBS:
            return 0.5
    return 1.0


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------


def _build_identifier_lookup(team_identifiers: Iterable) -> dict[str, list]:
    """Index team identifiers by normalized_token. Multiple rows per token allowed."""
    lookup: dict[str, list] = {}
    for ti in team_identifiers:
        key = (ti.normalized_token or "").lower()
        if not key:
            continue
        lookup.setdefault(key, []).append(ti)
    return lookup


def compute_intensity(
    ticket_title: str,
    ticket_description: str,
    ticket_labels: list[str],
    ticket_components: list[str],
    team_identifiers: list,
    effort_multiplier: float = 1.0,
) -> SkillIntensityResult:
    """Compute skill + domain intensity vectors for a single ticket.

    See module docstring for the algorithm. Pure function — no DB.
    """
    lookup = _build_identifier_lookup(team_identifiers)
    if not lookup:
        return SkillIntensityResult()

    # Four text sources. For labels/components we concatenate items so the
    # tokenizer can see them, but verb context within a label string is
    # essentially meaningless — that's fine, it just produces weight 1.0.
    labels_text = " ".join(ticket_labels or [])
    components_text = " ".join(ticket_components or [])

    sources: list[tuple[str, str]] = [
        ("ticket_title", ticket_title or ""),
        ("ticket_description", ticket_description or ""),
        ("label", labels_text),
        ("component", components_text),
    ]

    skill_scores: dict[str, float] = {}
    domain_scores: dict[str, float] = {}
    matched_identifiers: list[str] = []
    seen_identifiers: set[str] = set()

    for source_name, text in sources:
        if not text:
            continue
        word_positions = _word_positions(text)
        extracted = extract_tokens(text, source=source_name)
        for et in extracted:
            matches = lookup.get(et.normalized)
            if not matches:
                continue

            # Find the char offset of this specific token occurrence so we can
            # look back accurately. ``extract_tokens`` doesn't surface the
            # offset, so we re-find the first occurrence we haven't already
            # consumed for this normalized form.
            char_offset = _find_token_offset(text, et.token, word_positions)
            weight = _verb_weight_for_offset(word_positions, char_offset) if char_offset is not None else 1.0

            for ti in matches:
                contribution = float(ti.confidence) * weight * float(effort_multiplier)
                skill_scores[ti.skill] = skill_scores.get(ti.skill, 0.0) + contribution
                if ti.domain:
                    domain_scores[ti.domain] = domain_scores.get(ti.domain, 0.0) + contribution

            # Preserve raw token in insertion order, deduped.
            if et.token not in seen_identifiers:
                matched_identifiers.append(et.token)
                seen_identifiers.add(et.token)

    if not skill_scores and not domain_scores:
        return SkillIntensityResult(matched_identifiers=matched_identifiers)

    skill_vector = _normalize_max(skill_scores)
    domain_vector = _normalize_max(domain_scores)

    return SkillIntensityResult(
        skill_vector=skill_vector,
        domain_vector=domain_vector,
        matched_identifiers=matched_identifiers,
    )


def _find_token_offset(
    text: str, raw_token: str, word_positions: list[tuple[str, int]]
) -> int | None:
    """Return the start offset of ``raw_token`` in ``text`` matching a word position.

    Falls back to ``text.find`` if the word-position search misses (e.g. token
    contains punctuation the word splitter doesn't preserve).
    """
    lowered = raw_token.lower()
    normalized = normalize_token(raw_token)
    for word, off in word_positions:
        if word == lowered or word == normalized:
            return off
    # Fallback: plain substring search.
    pos = text.find(raw_token)
    return pos if pos >= 0 else None


def _normalize_max(scores: dict[str, float]) -> dict[str, float]:
    """Scale a score dict so the max value = 1.0. Returns rounded to 3 decimals."""
    if not scores:
        return {}
    peak = max(scores.values())
    if peak <= 0:
        return {}
    return {k: round(v / peak, 3) for k, v in scores.items()}


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


async def persist_intensity(
    ticket_id: str,
    result: SkillIntensityResult,
    db: AsyncSession,
) -> None:
    """Upsert one :class:`TicketSkillAnalysis` row keyed by ``ticket_id``.

    Uses the postgres ``ON CONFLICT DO UPDATE`` so retries / re-syncs don't
    explode on the unique constraint.
    """
    # Accept either a UUID instance or a string; SQLAlchemy will coerce as needed.
    if isinstance(ticket_id, str):
        try:
            ticket_uuid: uuid.UUID | str = uuid.UUID(ticket_id)
        except ValueError:
            ticket_uuid = ticket_id  # let the driver raise if it's truly invalid
    else:
        ticket_uuid = ticket_id

    now = datetime.utcnow()
    stmt = pg_insert(TicketSkillAnalysis).values(
        id=uuid.uuid4(),
        ticket_id=ticket_uuid,
        skill_vector=result.skill_vector,
        domain_vector=result.domain_vector,
        matched_identifiers=result.matched_identifiers,
        analyzed_at=now,
    ).on_conflict_do_update(
        index_elements=["ticket_id"],
        set_={
            "skill_vector": result.skill_vector,
            "domain_vector": result.domain_vector,
            "matched_identifiers": result.matched_identifiers,
            "analyzed_at": now,
        },
    )
    await db.execute(stmt)


async def compute_and_persist(
    ticket: object,
    team_identifiers: list,
    db: AsyncSession,
    effort_multiplier: float = 1.0,
    ticket_description: str = "",
) -> SkillIntensityResult:
    """Convenience wrapper. Computes the intensity vectors then upserts."""

    def _get(obj: object, name: str, default):
        if isinstance(obj, dict):
            return obj.get(name, default)
        return getattr(obj, name, default)

    title = _get(ticket, "title", "") or ""
    labels = _get(ticket, "labels", []) or []
    components = _get(ticket, "components", []) or []
    ticket_id = _get(ticket, "id", None)

    result = compute_intensity(
        ticket_title=title,
        ticket_description=ticket_description,
        ticket_labels=list(labels),
        ticket_components=list(components),
        team_identifiers=team_identifiers,
        effort_multiplier=effort_multiplier,
    )
    if ticket_id is not None:
        await persist_intensity(str(ticket_id), result, db)
    return result
