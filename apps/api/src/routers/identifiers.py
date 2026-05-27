"""
Identifier-association API router (Initiative A, Wave 1).

Endpoints
---------
POST   /api/identifiers/scan         — Lead; runs bootstrap scan + upserts.
GET    /api/identifiers/{team_id}    — Lead; list identifiers (optional low-conf filter).
PATCH  /api/identifiers/{id}         — Lead; manual correction.
DELETE /api/identifiers/{id}         — Lead; remove false positive.

The scan endpoint:
1. Resolves the team (404 on cross-org or unknown).
2. Builds a JiraClient via the same helper Scope Cop uses
   (``src.routers.scope_cop._get_jira_client``) — single source of truth.
3. Resolves the org's Anthropic key via
   ``src.services.scope_cop._get_anthropic_key`` (also reused).
4. Pulls a closed-sprint corpus, tokenizes title/description/labels/components
   for tickets and title/description for epics, aggregates frequencies.
5. Caps at the top-200 most-frequent tokens and hands them to the classifier.
6. Upserts results into ``team_identifiers`` with a portable upsert
   (select → insert/update) so the same code works under both Postgres
   (production) and SQLite (tests).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_org_id
from src.auth_roles import require_role
from src.database import get_db
from src.models.identifier import TeamIdentifier
from src.models.organization import Organization
from src.models.team import Team
from src.routers.scope_cop import _get_jira_client
from src.services.identifier_bootstrap_source import fetch_bootstrap_corpus
from src.services.identifier_classifier import classify_identifiers
from src.services.identifier_extraction import count_tokens, extract_tokens
from src.services.scope_cop import _get_anthropic_key

router = APIRouter(tags=["identifiers"])


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

TOP_N_TOKENS = 200
CLASSIFIER_BATCH_SIZE = 50
LOW_CONFIDENCE_THRESHOLD = 0.6  # below this, surface for human review


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class ScanRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    team_id: str


class ScanSummary(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    tokens_scanned: int
    tokens_classified: int
    identifiers_persisted: int
    low_confidence_count: int


class IdentifierRow(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    id: str
    team_id: str
    token: str
    normalized_token: str
    skill: str
    domain: str | None
    confidence: float
    source: str
    occurrence_count: int
    first_seen_at: str
    last_seen_at: str


class IdentifierPatch(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    skill: str | None = None
    domain: str | None = None
    confidence: float | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_to_model(row: TeamIdentifier) -> IdentifierRow:
    return IdentifierRow(
        id=str(row.id),
        team_id=str(row.team_id),
        token=row.token,
        normalized_token=row.normalized_token,
        skill=row.skill,
        domain=row.domain,
        confidence=row.confidence,
        source=row.source,
        occurrence_count=row.occurrence_count,
        first_seen_at=row.first_seen_at.isoformat() if row.first_seen_at else "",
        last_seen_at=row.last_seen_at.isoformat() if row.last_seen_at else "",
    )


async def _resolve_team_in_org(team_id: str, clerk_org_id: str, db: AsyncSession) -> Team:
    """Resolve team and assert it belongs to the requesting org. 404 on any mismatch."""
    try:
        team_uuid = uuid.UUID(team_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found.")

    team = await db.scalar(select(Team).where(Team.id == team_uuid))
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found.")

    org = await db.scalar(select(Organization).where(Organization.id == team.organization_id))
    if not org or org.clerk_org_id != clerk_org_id:
        # Mirror Scope Cop / repo convention: foreign org -> 404, not 403.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found.")
    return team


def _parse_tech_stack(team: Team) -> list[str]:
    """``Team.tech_stack`` is stored as JSON-encoded ``list[str]`` (see
    routers/teams.py: ``team.tech_stack = json.dumps(body.tech_stack)``).

    Be defensive: tolerate ``None``, malformed JSON, or a legacy
    comma-separated string. Returns a deduped list of non-empty trimmed
    strings.
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
            # Legacy fallback: comma-separated string.
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
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/scan", response_model=ScanSummary)
async def scan_identifiers(
    request: ScanRequest,
    _: str = Depends(require_role("lead")),
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """Run a bootstrap identifier scan for ``team_id`` and persist the results.

    Idempotent: re-running increments ``occurrence_count`` and refreshes
    ``last_seen_at`` for existing tokens; new tokens are inserted.
    """
    team = await _resolve_team_in_org(request.team_id, clerk_org_id, db)

    # Resolve Jira + Anthropic — these raise HTTP errors on misconfiguration.
    jira_client = await _get_jira_client(team, db)
    anthropic_key = await _get_anthropic_key(str(team.id), db)

    # 1. Fetch the closed-sprint corpus.
    tickets, epics = await fetch_bootstrap_corpus(
        team_id=str(team.id), db=db, jira_client=jira_client, max_tickets=500
    )

    # 2. Tokenize every text source.
    extracted = []
    for t in tickets:
        if t.title:
            extracted.extend(extract_tokens(t.title, "ticket_title"))
        if t.description:
            extracted.extend(extract_tokens(t.description, "ticket_description"))
        # Labels & components: no regex — each value is its own raw token.
        for label in t.labels or []:
            norm = label.strip().lower()
            if len(norm) >= 3:
                from src.services.identifier_extraction import ExtractedToken  # local to avoid top-line clutter
                extracted.append(ExtractedToken(token=label, normalized=norm, source="label"))
        for comp in t.components or []:
            norm = comp.strip().lower()
            if len(norm) >= 3:
                from src.services.identifier_extraction import ExtractedToken
                extracted.append(ExtractedToken(token=comp, normalized=norm, source="component"))
    for e in epics:
        if e.title:
            extracted.extend(extract_tokens(e.title, "epic"))
        if e.description:
            extracted.extend(extract_tokens(e.description, "epic"))

    if not extracted:
        return ScanSummary(
            tokens_scanned=0,
            tokens_classified=0,
            identifiers_persisted=0,
            low_confidence_count=0,
        )

    # First-seen source + first-seen raw form per normalized token (stable).
    first_source: dict[str, str] = {}
    first_raw: dict[str, str] = {}
    for tok in extracted:
        first_source.setdefault(tok.normalized, tok.source)
        first_raw.setdefault(tok.normalized, tok.token)

    # 3. Aggregate frequencies and cap at TOP_N.
    counts = count_tokens(extracted)
    top_tokens = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:TOP_N_TOKENS]
    counts_by_norm = dict(top_tokens)

    # 4. Classify against the team's tech stack. Classifier expects
    #    [(raw_token, normalized_token, occurrence_count), ...].
    classifier_input: list[tuple[str, str, int]] = [
        (first_raw.get(norm, norm), norm, cnt) for norm, cnt in top_tokens
    ]
    stack = _parse_tech_stack(team)
    classified = await classify_identifiers(
        classifier_input, stack, anthropic_key, batch_size=CLASSIFIER_BATCH_SIZE
    )

    # 5. Upsert. Portable pattern (select-then-insert/update) so SQLite tests
    #    and Postgres production share the same path.
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
            # Re-classification can refine the label; trust the new result.
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

    return ScanSummary(
        tokens_scanned=len(counts),
        tokens_classified=len(classified),
        identifiers_persisted=persisted,
        low_confidence_count=low_conf,
    )


@router.get("/{team_id}", response_model=list[IdentifierRow])
async def list_identifiers(
    team_id: str,
    low_confidence_only: bool = Query(False, alias="low_confidence_only"),
    _: str = Depends(require_role("lead")),
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """List identifiers for a team. Optional ``?low_confidence_only=true``."""
    team = await _resolve_team_in_org(team_id, clerk_org_id, db)
    stmt = select(TeamIdentifier).where(TeamIdentifier.team_id == team.id)
    if low_confidence_only:
        stmt = stmt.where(TeamIdentifier.confidence < LOW_CONFIDENCE_THRESHOLD)
    stmt = stmt.order_by(TeamIdentifier.occurrence_count.desc())
    rows = (await db.scalars(stmt)).all()
    return [_row_to_model(r) for r in rows]


async def _resolve_identifier_in_org(
    identifier_id: str, clerk_org_id: str, db: AsyncSession
) -> TeamIdentifier:
    try:
        ident_uuid = uuid.UUID(identifier_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Identifier not found.")
    row = await db.scalar(select(TeamIdentifier).where(TeamIdentifier.id == ident_uuid))
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Identifier not found.")
    # Cross-org guard via the team it belongs to.
    team = await db.scalar(select(Team).where(Team.id == row.team_id))
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Identifier not found.")
    org = await db.scalar(select(Organization).where(Organization.id == team.organization_id))
    if not org or org.clerk_org_id != clerk_org_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Identifier not found.")
    return row


@router.patch("/{identifier_id}", response_model=IdentifierRow)
async def patch_identifier(
    identifier_id: str,
    body: IdentifierPatch,
    _: str = Depends(require_role("lead")),
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """Manual override. Only provided fields are updated."""
    row = await _resolve_identifier_in_org(identifier_id, clerk_org_id, db)
    if body.skill is not None:
        row.skill = body.skill
    if body.domain is not None:
        row.domain = body.domain
    if body.confidence is not None:
        row.confidence = body.confidence
    row.last_seen_at = datetime.utcnow()
    await db.commit()
    return _row_to_model(row)


@router.delete("/{identifier_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_identifier(
    identifier_id: str,
    _: str = Depends(require_role("lead")),
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """Remove a false positive."""
    row = await _resolve_identifier_in_org(identifier_id, clerk_org_id, db)
    await db.delete(row)
    await db.commit()
    return None
