"""
Identifier-association API router (Initiative A, Wave 1).

Endpoints
---------
POST   /api/identifiers/scan         — Lead; runs bootstrap scan + upserts.
GET    /api/identifiers/{team_id}    — Lead; list identifiers (optional low-conf filter).
PATCH  /api/identifiers/{id}         — Lead; manual correction.
DELETE /api/identifiers/{id}         — Lead; remove false positive.

The heavy lifting for ``/scan`` lives in
``src.services.identifier_scan_service.run_team_scan`` (Wave 3 refactor) so the
same code path is reused by the onboarding background task that auto-triggers
a scan after Jira sprint history import completes.
"""
from __future__ import annotations

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
from src.services.identifier_refresh_service import refresh_team_identifiers
from src.services.identifier_scan_service import (
    LOW_CONFIDENCE_THRESHOLD,
    run_team_scan,
)
from src.services.scope_cop import _get_anthropic_key

router = APIRouter(tags=["identifiers"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class ScanRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    team_id: str


class RefreshRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    team_id: str | None = None


class RefreshSummary(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    tokens_seen: int
    new_tokens: int
    classified: int
    persisted: int
    aged_out: int
    pruned: int


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


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/refresh",
    response_model=RefreshSummary,
    status_code=status.HTTP_202_ACCEPTED,
)
async def refresh_identifiers(
    request: RefreshRequest,
    _: str = Depends(require_role("lead")),
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """Incremental identifier refresh (M7).

    Thin wrapper around
    ``identifier_refresh_service.refresh_team_identifiers``. If ``team_id``
    is omitted, picks the lead's first team in the org. Synchronous (mirrors
    ``/scan``) — returns the summary once classification + age-out finish.
    """
    team_id = request.team_id
    if not team_id:
        # Resolve "default" team for the org. Mirrors how the lead's UI
        # has a single active team selector; we just pick the most recent.
        org = await db.scalar(
            select(Organization).where(Organization.clerk_org_id == clerk_org_id)
        )
        if not org:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Team not found."
            )
        team = await db.scalar(
            select(Team)
            .where(Team.organization_id == org.id)
            .order_by(Team.created_at.desc())
        )
        if not team:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Team not found."
            )
    else:
        team = await _resolve_team_in_org(team_id, clerk_org_id, db)

    jira_client = await _get_jira_client(team, db)
    anthropic_key = await _get_anthropic_key(str(team.id), db)

    summary = await refresh_team_identifiers(
        team=team, jira_client=jira_client, anthropic_key=anthropic_key, db=db
    )
    return RefreshSummary(
        tokens_seen=summary["tokens_seen"],
        new_tokens=summary["new_tokens"],
        classified=summary["classified"],
        persisted=summary["persisted"],
        aged_out=summary["aged_out"],
        pruned=summary["pruned"],
    )


@router.post("/scan", response_model=ScanSummary)
async def scan_identifiers(
    request: ScanRequest,
    _: str = Depends(require_role("lead")),
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """Run a bootstrap identifier scan for ``team_id`` and persist the results.

    Thin wrapper: resolves auth + connections, delegates to
    ``identifier_scan_service.run_team_scan``. Idempotent.
    """
    team = await _resolve_team_in_org(request.team_id, clerk_org_id, db)

    # Resolve Jira + Anthropic — these raise HTTP errors on misconfiguration.
    jira_client = await _get_jira_client(team, db)
    anthropic_key = await _get_anthropic_key(str(team.id), db)

    summary = await run_team_scan(
        team=team, jira_client=jira_client, anthropic_key=anthropic_key, db=db
    )
    return ScanSummary(
        tokens_scanned=summary["tokens_scanned"],
        tokens_classified=summary["tokens_classified"],
        identifiers_persisted=summary["identifiers_persisted"],
        low_confidence_count=summary["low_confidence_count"],
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
