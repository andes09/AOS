"""
Sprint API router.

Endpoints
---------
GET   /api/sprints/current
    Returns the active sprint for the authenticated team.
GET   /api/sprints/completed
    Returns all completed sprints for the authenticated team, newest first.
PATCH /api/sprints/{sprint_id}/assignments/{ticket_id}
    Reassign / remove / add a single ticket assignment on a sprint plan.
    Captures an override audit row (M8a) for Sprint Brain learning + plan-
    quality telemetry (M8d).
"""
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import date

from src.auth import get_current_user_id, get_current_org_id
from src.auth_roles import require_role
from src.database import get_db
from src.models.developer import Developer
from src.models.organization import Organization
from src.models.sprint import Sprint, SprintStatus
from src.models.sprint_plan_override import (
    OverrideAction,
    OverrideReason,
    SprintPlanOverride,
)
from src.models.team import Team
from src.models.ticket import Ticket
from src.dependencies import resolve_team

router = APIRouter(prefix="/api/sprints", tags=["sprints"])


# Validation sets derived from the enums so a new value only needs to be added
# in one place (the enum) for the API to accept it.
_ACTION_VALUES = {e.value for e in OverrideAction}
_REASON_VALUES = {e.value for e in OverrideReason}


class CurrentSprintResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    id: str
    name: str
    # jira_sprint_id exposed so integrations (e.g. the Stage 1 simulator) can
    # join Omada sprints to their originating Jira sprint id without scraping
    # by name. Optional because not every sprint has a Jira origin.
    jira_sprint_id: str | None
    start_date: date | None
    end_date: date | None
    sprint_length: int
    total_points: float | None
    status: str


class CompletedSprintsResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    sprints: list[CurrentSprintResponse]


@router.get("/completed", response_model=CompletedSprintsResponse)
async def get_completed_sprints(
    team: Team = Depends(resolve_team),
    db: AsyncSession = Depends(get_db),
):
    """Return all completed sprints for the authenticated team, newest first."""
    rows = (
        await db.scalars(
            select(Sprint)
            .where(Sprint.team_id == team.id, Sprint.status == SprintStatus.COMPLETED)
            .order_by(Sprint.end_date.desc())
        )
    ).all()
    return CompletedSprintsResponse(
        sprints=[
            CurrentSprintResponse(
                id=str(s.id),
                name=s.name,
                jira_sprint_id=s.jira_sprint_id,
                start_date=s.start_date,
                end_date=s.end_date,
                sprint_length=team.sprint_length_days,
                total_points=s.committed_points,
                status=s.status.value,
            )
            for s in rows
        ]
    )


@router.get("/current", response_model=CurrentSprintResponse)
async def get_current_sprint(
    team: Team = Depends(resolve_team),
    db: AsyncSession = Depends(get_db),
):
    """Return the active sprint for the authenticated team."""
    sprint = await db.scalar(
        select(Sprint)
        .where(Sprint.team_id == team.id, Sprint.status == SprintStatus.ACTIVE)
        .order_by(Sprint.start_date.desc())
    )
    if not sprint:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active sprint")
    return CurrentSprintResponse(
        id=str(sprint.id),
        name=sprint.name,
        jira_sprint_id=sprint.jira_sprint_id,
        start_date=sprint.start_date,
        end_date=sprint.end_date,
        sprint_length=team.sprint_length_days,
        total_points=sprint.committed_points,
        status=sprint.status.value,
    )


# ---------------------------------------------------------------------------
# M8a — assignment override capture
# ---------------------------------------------------------------------------

class PatchAssignmentRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    new_developer_id: uuid.UUID | None = None
    action: Literal["reassign", "remove", "add"]
    reason_code: str | None = None
    reason_text: str | None = None


class PatchAssignmentResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    ticket_id: str
    sprint_id: str
    assignee_id: str | None
    override_id: str


@router.patch(
    "/{sprint_id}/assignments/{ticket_id}",
    response_model=PatchAssignmentResponse,
)
async def patch_assignment(
    sprint_id: uuid.UUID,
    ticket_id: uuid.UUID,
    body: PatchAssignmentRequest,
    user_id: str = Depends(get_current_user_id),
    clerk_org_id: str = Depends(get_current_org_id),
    _role: str = Depends(require_role("lead")),
    db: AsyncSession = Depends(get_db),
) -> PatchAssignmentResponse:
    """Reassign / remove / add a single ticket assignment.

    Mutates `Ticket.assignee_id` (single source of truth for velocity
    attribution) and writes a `SprintPlanOverride` audit row in the same
    transaction.

    Returns 403 if the caller is not a lead, 404 if the sprint belongs to
    another org, 422 if the ticket is not in the sprint or an invalid reason
    code is supplied.
    """
    if body.reason_code is not None and body.reason_code not in _REASON_VALUES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid reason_code. Allowed: {sorted(_REASON_VALUES)}",
        )

    # Resolve sprint -> team -> org (404 if foreign).
    sprint = await db.scalar(select(Sprint).where(Sprint.id == sprint_id))
    if sprint is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sprint not found")
    team = await db.scalar(select(Team).where(Team.id == sprint.team_id))
    if team is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sprint not found")
    org = await db.scalar(
        select(Organization).where(Organization.id == team.organization_id)
    )
    if org is None or org.clerk_org_id != clerk_org_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sprint not found")

    # Resolve ticket and verify it belongs to this sprint.
    ticket = await db.scalar(select(Ticket).where(Ticket.id == ticket_id))
    if ticket is None or ticket.sprint_id != sprint_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Ticket is not in this sprint",
        )

    # Capture prior assignee (for the override row) before mutating.
    original_assignee_id = ticket.assignee_id

    if body.action == OverrideAction.REMOVE.value:
        ticket.assignee_id = None
    else:  # reassign | add
        ticket.assignee_id = body.new_developer_id

    # Best-effort: store the acting lead's Developer.id (UUID) under created_by.
    # If we can't resolve a Developer for this Clerk user, leave NULL — the
    # column is nullable by design (see migration 0018).
    created_by_uuid: uuid.UUID | None = None
    actor_dev = await db.scalar(
        select(Developer).where(Developer.clerk_user_id == user_id).limit(1)
    )
    if actor_dev is not None:
        created_by_uuid = actor_dev.id

    override = SprintPlanOverride(
        id=uuid.uuid4(),
        sprint_id=sprint_id,
        ticket_id=ticket_id,
        action=body.action,
        original_developer_id=original_assignee_id,
        new_developer_id=body.new_developer_id if body.action != OverrideAction.REMOVE.value else None,
        reason_code=body.reason_code,
        reason_text=body.reason_text,
        created_by=created_by_uuid,
    )
    db.add(override)
    await db.commit()

    return PatchAssignmentResponse(
        ticket_id=str(ticket_id),
        sprint_id=str(sprint_id),
        assignee_id=str(ticket.assignee_id) if ticket.assignee_id else None,
        override_id=str(override.id),
    )
