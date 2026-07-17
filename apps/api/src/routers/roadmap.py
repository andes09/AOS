"""
Roadmap — the personal, day-by-day project plan behind the calendar view.

One roadmap (Project → Milestones → Tasks) per org, generated from the
onboarding brief via services/roadmap_generator. Tasks carry a scheduled_date
(calendar day) and a status the user flips to check things off, plus delete.

GET    /api/roadmap                    → the org's roadmap, or null
POST   /api/roadmap/generate           → generate + persist from the brief
PATCH  /api/roadmap/tasks/{task_id}    → update status / title / scheduled_date
DELETE /api/roadmap/tasks/{task_id}    → delete a task
"""

import logging
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.auth import get_current_org_id
from src.database import get_db
from src.models.milestone import Milestone
from src.models.onboarding_session import OnboardingSession
from src.models.organization import Organization
from src.models.project import Project
from src.models.task import Task, TaskStatus
from src.models.team import Team
from src.services import roadmap_generator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/roadmap", tags=["roadmap"])

_VALID_STATUSES = {s.value for s in TaskStatus}


# ─── serialization ─────────────────────────────────────────────────────────────
def _task_json(task: Task) -> dict:
    return {
        "id": str(task.id),
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "sortOrder": task.sort_order,
        "scheduledDate": task.scheduled_date.isoformat() if task.scheduled_date else None,
    }


def _project_json(project: Project) -> dict:
    return {
        "id": str(project.id),
        "name": project.name,
        "summary": project.summary,
        "purpose": project.purpose,
        "milestones": [
            {
                "id": str(m.id),
                "title": m.title,
                "description": m.description,
                "sortOrder": m.sort_order,
                "tasks": [_task_json(t) for t in m.tasks],
            }
            for m in project.milestones
        ],
    }


# ─── shared lookups ─────────────────────────────────────────────────────────────
async def _get_org(clerk_org_id: str, db: AsyncSession) -> Organization:
    org = await db.scalar(select(Organization).where(Organization.clerk_org_id == clerk_org_id))
    if not org:
        raise HTTPException(status_code=409, detail="org_not_provisioned")
    return org


async def _load_project(session_id: uuid.UUID, db: AsyncSession) -> Project | None:
    """The org's project with milestones+tasks eagerly loaded (ordered)."""
    return await db.scalar(
        select(Project)
        .where(Project.onboarding_session_id == session_id)
        .options(selectinload(Project.milestones).selectinload(Milestone.tasks))
    )


async def _owned_task(task_id: str, org: Organization, db: AsyncSession) -> Task:
    """Load a task, ensuring it belongs to the caller's org. 404 otherwise."""
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="task_not_found")
    task = await db.scalar(
        select(Task)
        .join(Milestone, Task.milestone_id == Milestone.id)
        .join(Project, Milestone.project_id == Project.id)
        .join(Team, Project.team_id == Team.id)
        .where(Task.id == tid, Team.organization_id == org.id)
    )
    if task is None:
        raise HTTPException(status_code=404, detail="task_not_found")
    return task


# ─── endpoints ──────────────────────────────────────────────────────────────────
@router.get("")
async def get_roadmap(
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    org = await _get_org(clerk_org_id, db)
    session = await db.scalar(
        select(OnboardingSession).where(OnboardingSession.organization_id == org.id)
    )
    if session is None:
        return None
    project = await _load_project(session.id, db)
    return _project_json(project) if project else None


@router.post("/generate")
async def generate(
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    org = await _get_org(clerk_org_id, db)
    session = await db.scalar(
        select(OnboardingSession).where(OnboardingSession.organization_id == org.id)
    )
    if session is None or not session.project_brief:
        raise HTTPException(
            status_code=409,
            detail="Finish the onboarding interview first — there's no project brief to plan from yet.",
        )

    # Idempotent: return the existing roadmap rather than generating a second one.
    existing = await _load_project(session.id, db)
    if existing is not None:
        return _project_json(existing)

    api_key = roadmap_generator.resolve_groq_key()
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="No Groq API key configured for planning. Set GROQ_API_KEY.",
        )

    team = await db.scalar(
        select(Team).where(Team.organization_id == org.id).order_by(Team.created_at)
    )
    if team is None:
        raise HTTPException(status_code=409, detail="no_team_for_org")

    try:
        await roadmap_generator.generate_roadmap(session, team, api_key, db)
    except ValueError as exc:  # bad key
        raise HTTPException(status_code=402, detail=str(exc))
    except RuntimeError as exc:  # upstream / model failure
        raise HTTPException(status_code=502, detail=str(exc))

    project = await _load_project(session.id, db)
    return _project_json(project)


class TaskUpdateRequest(BaseModel):
    status: str | None = None
    title: str | None = None
    scheduledDate: date | None = None

    @field_validator("status")
    @classmethod
    def _valid_status(cls, v: str | None) -> str | None:
        if v is not None and v not in _VALID_STATUSES:
            raise ValueError(f"status must be one of {sorted(_VALID_STATUSES)}")
        return v

    @field_validator("title")
    @classmethod
    def _valid_title(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if not (1 <= len(v) <= 255):
                raise ValueError("title must be 1-255 characters")
        return v


@router.patch("/tasks/{task_id}")
async def update_task(
    task_id: str,
    body: TaskUpdateRequest,
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    org = await _get_org(clerk_org_id, db)
    task = await _owned_task(task_id, org, db)

    if body.status is not None:
        task.status = body.status
    if body.title is not None:
        task.title = body.title
    if "scheduledDate" in body.model_fields_set:
        task.scheduled_date = body.scheduledDate

    await db.commit()
    await db.refresh(task)
    return _task_json(task)


@router.delete("/tasks/{task_id}", status_code=204)
async def delete_task(
    task_id: str,
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    org = await _get_org(clerk_org_id, db)
    task = await _owned_task(task_id, org, db)
    await db.delete(task)
    await db.commit()
    return Response(status_code=204)
