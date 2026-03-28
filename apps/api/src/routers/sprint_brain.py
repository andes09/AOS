"""
Sprint Brain API router.

Endpoints
---------
POST /api/sprint-brain/plan
    Generate an AI-powered sprint plan for a team.

POST /api/sprint-brain/what-if
    Re-plan with specified tickets dropped; returns revised confidence/assignments.

Coordinator stubs
-----------------
Three internal helpers are currently stubbed and must be completed once the
following upstream tracks land:

  _get_anthropic_key()      → needs Organisation model (Track C) + encryption service
  _get_developer_profiles() → needs TeamMember + VelocityRecord models (Track C)
                              and velocity service (Track E velocity engine)
  _get_candidate_tickets()  → needs Ticket model (Track C) + Jira sync (Track D)
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select

from src.auth import get_current_user_id, get_current_org_id
from src.database import get_db
from src.models.organization import Organization
from src.models.ticket import Ticket, TicketStatus
from src.services.encryption import decrypt
from src.services.sprint_brain import (
    SprintBrainInput,
    SprintBrainOutput,
    generate_sprint_plan,
    simulate_what_if,
)

router = APIRouter(prefix="/api/sprint-brain", tags=["sprint-brain"])


# ---------------------------------------------------------------------------
# Pydantic request/response models
# ---------------------------------------------------------------------------


class PlanRequest(BaseModel):
    team_id: str
    sprint_length_days: int = 14
    sprint_start_date: str = ""        # ISO-8601; defaults to today if omitted
    pto_overrides: dict[str, float] = {}


class WhatIfRequest(BaseModel):
    team_id: str
    sprint_length_days: int = 14
    sprint_start_date: str = ""
    pto_overrides: dict[str, float] = {}
    dropped_ticket_ids: list[str]      # tickets to remove from the candidate pool


# ---------------------------------------------------------------------------
# Coordinator stubs — replace once upstream tracks are merged
# ---------------------------------------------------------------------------


async def _get_anthropic_key(clerk_org_id: str, db: AsyncSession) -> str:
    org = await db.scalar(select(Organization).where(Organization.clerk_org_id == clerk_org_id))
    if not org or not org.encrypted_anthropic_key:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="No Anthropic API key configured. Please add your key in Settings.",
        )
    return decrypt(org.encrypted_anthropic_key)


async def _get_developer_profiles(team_id: str, db: AsyncSession) -> list[dict]:
    """
    STUB — fetch velocity profiles for all active team members.

    TODO (coordinator): implement once these are available:
      - src.models.developer.TeamMember     (Track C)
      - src.models.velocity.VelocityRecord  (Track C)
      - src.services.velocity.calculate_developer_velocity  (Track E velocity engine)

    Expected implementation sketch:
        members = await db.scalars(
            select(TeamMember)
            .where(TeamMember.team_id == team_id, TeamMember.is_active == True)
        )
        profiles = []
        for member in members:
            records = await db.scalars(
                select(VelocityRecord)
                .where(VelocityRecord.developer_id == member.id)
                .order_by(VelocityRecord.created_at.desc())
                .limit(10)
            )
            velocity = calculate_developer_velocity([
                {"points_delivered": r.points_delivered,
                 "points_committed": r.points_committed}
                for r in records
            ])
            profiles.append({
                "developer_id": str(member.id),
                "display_name": member.display_name,
                "velocity": velocity,
            })
        return profiles
    """
    return []  # stub: Sprint Brain will warn about insufficient data


async def _get_candidate_tickets(team_id: str, db: AsyncSession) -> list[dict]:
    """Fetch unassigned/backlog tickets for sprint planning."""
    tickets = (await db.scalars(
        select(Ticket)
        .where(
            Ticket.team_id == team_id,
            Ticket.sprint_id.is_(None),
            Ticket.status.notin_([TicketStatus.DONE, TicketStatus.CANCELLED]),
        )
        .order_by(Ticket.story_points_estimated.desc().nulls_last())
        .limit(50)
    )).all()
    return [
        {
            "id": t.jira_issue_key or str(t.id),
            "summary": t.title,
            "story_points": t.story_points_estimated or 0,
            "priority": "medium",
            "labels": t.labels or [],
        }
        for t in tickets
    ]


# ---------------------------------------------------------------------------
# Route helpers
# ---------------------------------------------------------------------------


def _sprint_plan_response(team_id: str, sprint_start: str, plan: SprintBrainOutput) -> dict:
    return {
        "team_id": team_id,
        "sprint_start": sprint_start,
        "assignments": plan.assignments,
        "confidence_score": plan.confidence_score,
        "summary": plan.summary,
        "warnings": plan.warnings,
        "what_if_dropped": plan.what_if_dropped,
        "insufficient_data_devs": plan.insufficient_data_devs,
    }


async def _build_brain_input(
    team_id: str,
    sprint_length_days: int,
    sprint_start_date: str,
    pto_overrides: dict[str, float],
    db: AsyncSession,
) -> tuple[SprintBrainInput, str]:
    """Return (SprintBrainInput, resolved_sprint_start_date)."""
    candidate_tickets = await _get_candidate_tickets(team_id, db)
    if not candidate_tickets:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "No candidate tickets found for this team. "
                "Sync your Jira backlog first."
            ),
        )

    developer_profiles = await _get_developer_profiles(team_id, db)
    sprint_start = sprint_start_date or date.today().isoformat()

    return (
        SprintBrainInput(
            team_id=team_id,
            candidate_tickets=candidate_tickets,
            developer_profiles=developer_profiles,
            sprint_length_days=sprint_length_days,
            sprint_start_date=sprint_start,
            pto_overrides=pto_overrides,
        ),
        sprint_start,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/plan")
async def create_sprint_plan(
    request: PlanRequest,
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Generate an AI-powered sprint plan.

    Fetches the team's velocity profiles and unstarted Jira tickets, then
    asks Claude to assign tickets to developers and return a confidence score,
    plain-English summary, risk warnings, and what-if analysis for each ticket.
    """
    api_key = await _get_anthropic_key(clerk_org_id, db)

    brain_input, sprint_start = await _build_brain_input(
        team_id=request.team_id,
        sprint_length_days=request.sprint_length_days,
        sprint_start_date=request.sprint_start_date,
        pto_overrides=request.pto_overrides,
        db=db,
    )

    try:
        plan = await generate_sprint_plan(brain_input, api_key)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        )

    return _sprint_plan_response(request.team_id, sprint_start, plan)


@router.post("/what-if")
async def what_if_scenario(
    request: WhatIfRequest,
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Model the impact of dropping specific tickets from the sprint.

    Re-runs sprint planning with the given tickets removed from the candidate
    pool and returns the revised plan. Compare `confidence_score` before and
    after to quantify the benefit of descoping.
    """
    api_key = await _get_anthropic_key(clerk_org_id, db)

    brain_input, sprint_start = await _build_brain_input(
        team_id=request.team_id,
        sprint_length_days=request.sprint_length_days,
        sprint_start_date=request.sprint_start_date,
        pto_overrides=request.pto_overrides,
        db=db,
    )

    try:
        plan = await simulate_what_if(brain_input, request.dropped_ticket_ids, api_key)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        )

    return {
        "team_id": request.team_id,
        "sprint_start": sprint_start,
        "dropped_tickets": request.dropped_ticket_ids,
        "revised_plan": {
            "assignments": plan.assignments,
            "confidence_score": plan.confidence_score,
            "summary": plan.summary,
            "warnings": plan.warnings,
            "insufficient_data_devs": plan.insufficient_data_devs,
        },
    }
