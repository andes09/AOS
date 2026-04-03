"""
Retro AI API router.

Endpoints
---------
POST /api/retro/generate/{sprint_id}
    Generate a Claude-powered retrospective for a completed sprint.
    Idempotent: upserts retro + patterns; never duplicates on re-run.
    Requires lead role. Returns RetroResponse.

GET /api/retro/{sprint_id}
    Return stored retrospective for a sprint. Requires lead role.
    404 if retro not yet generated.

GET /api/retro/patterns/{team_id}
    Return all patterns for a team sorted by occurrenceCount DESC.
    Requires lead role. 404 if team does not exist.

PATCH /api/retro/pattern/{pattern_id}/resolve
    Set pattern status to resolved. Requires lead role. 404 if not found.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth_roles import require_role
from src.database import get_db
from src.models.retro import PatternStatus, RetroPattern, Retrospective
from src.models.sprint import Sprint
from src.models.team import Team
from src.services.retro_ai import (
    ActionItem,
    VelocitySummary,
    generate_retrospective,
)

retro_router = APIRouter(tags=["retro"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class RetroPatternResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: str
    pattern_type: str
    description: str
    occurrence_count: int
    first_seen_at: str | None
    last_seen_at: str | None
    status: str
    affected_sprint_names: list[str]


class RetroResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    retro_id: str
    sprint_id: str
    sprint_name: str
    generated_at: str
    went_well: list[str]
    went_poorly: list[str]
    action_items: list[ActionItem]
    patterns: list[RetroPatternResponse]
    velocity_summary: VelocitySummary


class PatternsResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    team_id: str
    patterns: list[RetroPatternResponse]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_sprint_name(sprint_id: uuid.UUID, db: AsyncSession) -> str:
    sprint = await db.scalar(select(Sprint).where(Sprint.id == sprint_id))
    return sprint.name if sprint else str(sprint_id)


async def _build_retro_response(retro: Retrospective, db: AsyncSession) -> RetroResponse:
    sprint_name = await _get_sprint_name(retro.sprint_id, db)

    # Load patterns for this retro's team that match the stored action_items / velocity_summary
    # For GET we return all patterns associated with the retro via the team
    # Per spec: GET returns same shape as POST 200 — patterns from retro_patterns for the team
    pattern_rows = (
        await db.scalars(
            select(RetroPattern)
            .where(RetroPattern.team_id == retro.team_id)
            .order_by(RetroPattern.occurrence_count.desc())
        )
    ).all()

    patterns = [_pattern_row_to_response(p) for p in pattern_rows]

    action_items = [
        ActionItem(
            action=item["action"],
            owner=item.get("owner"),
            priority=item["priority"],
        )
        for item in (retro.action_items or [])
    ]

    vs = retro.velocity_summary or {}
    velocity_summary = VelocitySummary(
        committed=vs.get("committed", 0),
        delivered=vs.get("delivered", 0),
        completion_rate=vs.get("completionRate", 0),
    )

    return RetroResponse(
        retro_id=str(retro.id),
        sprint_id=str(retro.sprint_id),
        sprint_name=sprint_name,
        generated_at=retro.generated_at.isoformat(),
        went_well=retro.went_well or [],
        went_poorly=retro.went_poorly or [],
        action_items=action_items,
        patterns=patterns,
        velocity_summary=velocity_summary,
    )


def _pattern_row_to_response(p: RetroPattern) -> RetroPatternResponse:
    return RetroPatternResponse(
        id=str(p.id),
        pattern_type=p.pattern_type,
        description=p.description or "",
        occurrence_count=p.occurrence_count,
        first_seen_at=str(p.first_seen_sprint_id) if p.first_seen_sprint_id else None,
        last_seen_at=str(p.last_seen_sprint_id) if p.last_seen_sprint_id else None,
        status=p.status,
        affected_sprint_names=p.affected_sprint_names or [],
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@retro_router.post("/generate/{sprint_id}", response_model=RetroResponse)
async def post_generate_retro(
    sprint_id: str,
    team_id: str,
    _: str = Depends(require_role("lead")),
    db: AsyncSession = Depends(get_db),
):
    """
    Generate a Claude-powered retrospective for a completed sprint.

    Idempotent: re-running upserts all fields and does not double-increment
    pattern occurrence counts for the same sprint.

    Raises 402 if no Anthropic API key is configured for the org.
    Raises 404 if sprint not found.
    Raises 422 if sprint is not COMPLETED.
    """
    try:
        svc_response = await generate_retrospective(
            sprint_id=sprint_id,
            team_id=team_id,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=str(exc)
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        )

    # Re-load the persisted retro to build the full response with rich pattern data
    retro = await db.scalar(
        select(Retrospective).where(Retrospective.sprint_id == uuid.UUID(sprint_id))
    )
    if not retro:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Retrospective was not persisted.",
        )

    return await _build_retro_response(retro, db)


@retro_router.get("/patterns/{team_id}", response_model=PatternsResponse)
async def get_patterns(
    team_id: str,
    _: str = Depends(require_role("lead")),
    db: AsyncSession = Depends(get_db),
):
    """
    Return all patterns for a team sorted by occurrenceCount DESC.

    404 if team does not exist. Returns 200 with empty list if team exists
    but has no patterns.
    """
    try:
        team_uuid = uuid.UUID(team_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found.")

    team = await db.scalar(select(Team).where(Team.id == team_uuid))
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found.")

    pattern_rows = (
        await db.scalars(
            select(RetroPattern)
            .where(RetroPattern.team_id == team_uuid)
            .order_by(RetroPattern.occurrence_count.desc())
        )
    ).all()

    return PatternsResponse(
        team_id=team_id,
        patterns=[_pattern_row_to_response(p) for p in pattern_rows],
    )


@retro_router.get("/{sprint_id}", response_model=RetroResponse)
async def get_retro(
    sprint_id: str,
    _: str = Depends(require_role("lead")),
    db: AsyncSession = Depends(get_db),
):
    """
    Return stored retrospective for a sprint.

    404 if no retro has been generated for this sprint yet.
    """
    try:
        sprint_uuid = uuid.UUID(sprint_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Retrospective not found.")

    retro = await db.scalar(
        select(Retrospective).where(Retrospective.sprint_id == sprint_uuid)
    )
    if not retro:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No retrospective found for this sprint.",
        )

    return await _build_retro_response(retro, db)


@retro_router.patch("/pattern/{pattern_id}/resolve", response_model=RetroPatternResponse)
async def resolve_pattern(
    pattern_id: str,
    _: str = Depends(require_role("lead")),
    db: AsyncSession = Depends(get_db),
):
    """Set pattern status to resolved. 404 if pattern not found."""
    try:
        pattern_uuid = uuid.UUID(pattern_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pattern not found.")

    pattern = await db.scalar(select(RetroPattern).where(RetroPattern.id == pattern_uuid))
    if not pattern:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pattern not found.")

    pattern.status = PatternStatus.RESOLVED.value
    await db.commit()
    await db.refresh(pattern)

    return _pattern_row_to_response(pattern)
