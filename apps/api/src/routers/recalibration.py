"""Recalibration proposals API router (M8c, Initiative A Wave 5).

Endpoints (all lead role)
-------------------------
POST   /api/recalibration/scan/{team_id}                  — run detect_and_persist, returns count
GET    /api/recalibration/proposals/{team_id}?status=...  — list proposals (default: pending)
POST   /api/recalibration/proposals/{id}/approve          — apply mutation + mark approved
POST   /api/recalibration/proposals/{id}/dismiss          — mark dismissed (no mutation)

The proposal row IS the audit record: `decided_at`, `decided_by`, and the
`evidence` JSONB link to the SprintPlanOverride ids that triggered it. No
separate audit table is necessary.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from src.auth import get_current_org_id, get_current_user_id
from src.auth_roles import require_role
from src.database import get_db
from src.models.developer import Developer
from src.models.identifier import TeamIdentifier
from src.models.organization import Organization
from src.models.recalibration_proposal import RecalibrationProposal
from src.models.team import Team
from src.services.override_analyzer import detect_and_persist

router = APIRouter(tags=["recalibration"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class ScanResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    inserted: int


class ProposalRow(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    id: str
    team_id: str
    kind: str
    developer_id: str | None
    identifier_id: str | None
    skill: str | None
    current_value: float | None
    suggested_value: float | None
    suggested_skill: str | None
    evidence: list
    status: str
    decided_at: str | None
    decided_by: str | None
    created_at: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_to_model(row: RecalibrationProposal) -> ProposalRow:
    return ProposalRow(
        id=str(row.id),
        team_id=str(row.team_id),
        kind=row.kind,
        developer_id=str(row.developer_id) if row.developer_id else None,
        identifier_id=str(row.identifier_id) if row.identifier_id else None,
        skill=row.skill,
        current_value=row.current_value,
        suggested_value=row.suggested_value,
        suggested_skill=row.suggested_skill,
        evidence=list(row.evidence or []),
        status=row.status,
        decided_at=row.decided_at.isoformat() if row.decided_at else None,
        decided_by=str(row.decided_by) if row.decided_by else None,
        created_at=row.created_at.isoformat() if row.created_at else "",
    )


async def _resolve_team_in_org(team_id: str, clerk_org_id: str, db: AsyncSession) -> Team:
    try:
        team_uuid = uuid.UUID(team_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found.")
    team = await db.scalar(select(Team).where(Team.id == team_uuid))
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found.")
    org = await db.scalar(select(Organization).where(Organization.id == team.organization_id))
    if not org or org.clerk_org_id != clerk_org_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found.")
    return team


async def _resolve_proposal_in_org(
    proposal_id: str, clerk_org_id: str, db: AsyncSession
) -> RecalibrationProposal:
    try:
        prop_uuid = uuid.UUID(proposal_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found.")
    row = await db.scalar(
        select(RecalibrationProposal).where(RecalibrationProposal.id == prop_uuid)
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found.")
    # Cross-org guard via team.
    team = await db.scalar(select(Team).where(Team.id == row.team_id))
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found.")
    org = await db.scalar(select(Organization).where(Organization.id == team.organization_id))
    if not org or org.clerk_org_id != clerk_org_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found.")
    return row


async def _resolve_actor_developer_id(
    user_id: str, clerk_org_id: str, db: AsyncSession
) -> uuid.UUID | None:
    """Resolve Clerk user_id -> Developer.id in this org. None when not found."""
    dev = await db.scalar(
        select(Developer)
        .join(Team, Developer.team_id == Team.id)
        .join(Organization, Team.organization_id == Organization.id)
        .where(
            Organization.clerk_org_id == clerk_org_id,
            Developer.clerk_user_id == user_id,
        )
        .limit(1)
    )
    return dev.id if dev else None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/scan/{team_id}", response_model=ScanResponse)
async def scan_team(
    team_id: str,
    _: str = Depends(require_role("lead")),
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """Run the override analyzer for ``team_id``. Returns count of new proposals."""
    team = await _resolve_team_in_org(team_id, clerk_org_id, db)
    inserted = await detect_and_persist(str(team.id), db)
    return ScanResponse(inserted=inserted)


@router.get("/proposals/{team_id}", response_model=list[ProposalRow])
async def list_proposals(
    team_id: str,
    status_filter: str = Query("pending", alias="status"),
    _: str = Depends(require_role("lead")),
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """List proposals for a team. Default ``?status=pending``."""
    team = await _resolve_team_in_org(team_id, clerk_org_id, db)
    stmt = (
        select(RecalibrationProposal)
        .where(RecalibrationProposal.team_id == team.id)
        .where(RecalibrationProposal.status == status_filter)
        .order_by(RecalibrationProposal.created_at.desc())
    )
    rows = (await db.scalars(stmt)).all()
    return [_row_to_model(r) for r in rows]


@router.post("/proposals/{proposal_id}/approve", response_model=ProposalRow)
async def approve_proposal(
    proposal_id: str,
    _: str = Depends(require_role("lead")),
    user_id: str = Depends(get_current_user_id),
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """Apply the proposed mutation and mark the proposal approved."""
    row = await _resolve_proposal_in_org(proposal_id, clerk_org_id, db)
    if row.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Proposal already {row.status}.",
        )

    if row.kind == "skill_rating":
        if not row.developer_id or not row.skill or row.suggested_value is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Malformed skill_rating proposal.",
            )
        dev = await db.scalar(select(Developer).where(Developer.id == row.developer_id))
        if not dev:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Developer not found.")
        ratings = dict(dev.skill_ratings or {})
        ratings[row.skill] = row.suggested_value
        dev.skill_ratings = ratings
        flag_modified(dev, "skill_ratings")
    elif row.kind == "identifier_skill":
        if not row.identifier_id or not row.suggested_skill:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Malformed identifier_skill proposal.",
            )
        ident = await db.scalar(
            select(TeamIdentifier).where(TeamIdentifier.id == row.identifier_id)
        )
        if not ident:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Identifier not found."
            )
        ident.skill = row.suggested_skill
    else:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown proposal kind: {row.kind}",
        )

    row.status = "approved"
    row.decided_at = datetime.utcnow()
    row.decided_by = await _resolve_actor_developer_id(user_id, clerk_org_id, db)
    await db.commit()
    return _row_to_model(row)


@router.post("/proposals/{proposal_id}/dismiss", response_model=ProposalRow)
async def dismiss_proposal(
    proposal_id: str,
    _: str = Depends(require_role("lead")),
    user_id: str = Depends(get_current_user_id),
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """Mark a proposal as dismissed. No mutation applied."""
    row = await _resolve_proposal_in_org(proposal_id, clerk_org_id, db)
    if row.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Proposal already {row.status}.",
        )
    row.status = "dismissed"
    row.decided_at = datetime.utcnow()
    row.decided_by = await _resolve_actor_developer_id(user_id, clerk_org_id, db)
    await db.commit()
    return _row_to_model(row)
