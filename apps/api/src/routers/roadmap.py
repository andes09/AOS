"""
Roadmap — the personal, day-by-day project plan behind the calendar view.

One roadmap (Project → Milestones → Tasks) per org, generated from the
onboarding brief via services/roadmap_generator. Tasks carry a scheduled_date
(calendar day) and a status the user flips to check things off, plus delete.

GET    /api/roadmap                              → the org's roadmap, or null
GET    /api/roadmap/members                      → team members + lane colors (planner sidebar)
POST   /api/roadmap/generate                     → generate + persist from the brief
POST   /api/roadmap/regenerate                   → replan the whole roadmap
POST   /api/roadmap/milestones/{id}/regenerate   → replan one milestone
POST   /api/roadmap/tasks                        → create a task
POST   /api/roadmap/tasks/reschedule             → bulk move/reassign (drag-drop)
PATCH  /api/roadmap/tasks/{task_id}              → update status / title / description /
                                                    schedule / assignee / sort order
DELETE /api/roadmap/tasks/{task_id}              → delete a task
"""

import asyncio
import json
import logging
import uuid
from datetime import date, time

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.auth import get_current_org_id, get_current_user_id
from src.database import get_db
from src.models.developer import Developer
from src.models.milestone import Milestone
from src.models.onboarding_session import OnboardingMessage, OnboardingSession
from src.models.organization import Organization
from src.models.project import Project
from src.models.task import Task, TaskStatus
from src.models.team import Team
from src.services import idea_interview, roadmap_adjuster, roadmap_generator

logger = logging.getLogger(__name__)

# Opener shown when the refine-chat has no history yet (rare — onboarded orgs
# already carry their interview transcript on the shared session).
_CHAT_OPENER = (
    "Tell me more about your project — the more detail you give (goals, tech stack, "
    "constraints, key features), the more precise and technical I can make your plan."
)

router = APIRouter(prefix="/api/roadmap", tags=["roadmap"])

_VALID_STATUSES = {s.value for s in TaskStatus}

# Must match LANE_COLOR_COUNT in apps/web/src/lib/laneColors.ts and the
# --lane-N-* triples in apps/web/src/styles/tokens.css.
_LANE_COLOR_COUNT = 10

# A task shorter than 5 minutes is unrenderable on the grid; longer than a day
# is a data-entry slip, not a plan.
_MIN_DURATION_MINUTES = 5
_MAX_DURATION_MINUTES = 1440


# ─── serialization ─────────────────────────────────────────────────────────────
def _task_json(task: Task) -> dict:
    return {
        "id": str(task.id),
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "sortOrder": task.sort_order,
        "scheduledDate": task.scheduled_date.isoformat() if task.scheduled_date else None,
        # "%H:%M", not isoformat(): isoformat emits seconds ("09:30:00"), which
        # the frontend's time helpers would have to strip on every render.
        "scheduledTime": task.scheduled_time.strftime("%H:%M") if task.scheduled_time else None,
        "durationMinutes": task.duration_minutes,
        "assigneeId": str(task.assignee_id) if task.assignee_id else None,
        "feedback": task.feedback,
    }


def _initials(name: str) -> str:
    """First+last initial. Computed here so every surface agrees on the fallback."""
    parts = [p for p in (name or "").split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def _member_json(dev: Developer, scheduled_count: int) -> dict:
    return {
        "id": str(dev.id),
        "name": dev.name,
        "role": dev.role,
        "email": dev.email,
        "colorIndex": (dev.color_index or 0) % _LANE_COLOR_COUNT,
        "avatarUrl": dev.avatar_url,
        "initials": _initials(dev.name),
        "isActive": bool(dev.is_active),
        "scheduledCount": scheduled_count,
    }


def _milestone_json(m: Milestone) -> dict:
    return {
        "id": str(m.id),
        "title": m.title,
        "description": m.description,
        "sortOrder": m.sort_order,
        "tasks": [_task_json(t) for t in m.tasks],
    }


def _project_json(project: Project) -> dict:
    return {
        "id": str(project.id),
        "name": project.name,
        "summary": project.summary,
        "purpose": project.purpose,
        "milestones": [_milestone_json(m) for m in project.milestones],
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


async def _owned_developer(dev_id: uuid.UUID, org: Organization, db: AsyncSession) -> Developer:
    """
    Load a developer, ensuring they belong to the caller's org. 404 otherwise.

    This is the cross-tenant guard for assignment. Without it, a PATCH carrying
    an assigneeId guessed from another organization would succeed, silently
    leaking that person's name and color into this org's planner.
    """
    dev = await db.scalar(
        select(Developer)
        .join(Team, Developer.team_id == Team.id)
        .where(Developer.id == dev_id, Team.organization_id == org.id)
    )
    if dev is None:
        raise HTTPException(status_code=404, detail="developer_not_found")
    return dev


async def _owned_tasks(task_ids: list[uuid.UUID], org: Organization, db: AsyncSession) -> dict:
    """
    Bulk sibling of `_owned_task` — one query for the whole batch rather than N.

    Returns {id: Task}. Callers are responsible for treating a short result as a
    failure; see the reschedule endpoint, which refuses to apply partially.
    """
    rows = (
        await db.execute(
            select(Task)
            .join(Milestone, Task.milestone_id == Milestone.id)
            .join(Project, Milestone.project_id == Project.id)
            .join(Team, Project.team_id == Team.id)
            .where(Task.id.in_(task_ids), Team.organization_id == org.id)
        )
    ).scalars().all()
    return {t.id: t for t in rows}


def _parse_uuid(raw: str, detail: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(status_code=404, detail=detail)


async def _owned_milestone(milestone_id: str, org: Organization, db: AsyncSession) -> Milestone:
    """Load a milestone (with tasks), ensuring it belongs to the caller's org. 404 otherwise."""
    try:
        mid = uuid.UUID(milestone_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="milestone_not_found")
    milestone = await db.scalar(
        select(Milestone)
        .join(Project, Milestone.project_id == Project.id)
        .join(Team, Project.team_id == Team.id)
        .where(Milestone.id == mid, Team.organization_id == org.id)
        .options(selectinload(Milestone.tasks))
    )
    if milestone is None:
        raise HTTPException(status_code=404, detail="milestone_not_found")
    return milestone


async def _session_and_brief(
    clerk_org_id: str, db: AsyncSession
) -> tuple[Organization, OnboardingSession]:
    """The caller's org + its onboarding session, 409 if there's no completed brief yet."""
    org = await _get_org(clerk_org_id, db)
    session = await db.scalar(
        select(OnboardingSession).where(OnboardingSession.organization_id == org.id)
    )
    if session is None or not session.project_brief:
        raise HTTPException(
            status_code=409,
            # Deliberately not "finish onboarding" — the planner's refine-chat
            # can supply the brief too, so onboarding isn't the only way out.
            detail="Add some project details first — there's no project brief to plan from yet.",
        )
    return org, session


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


@router.get("/members")
async def get_members(
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """
    The planner sidebar's lanes: every active person in the org, their lane
    color, and how much open scheduled work they're carrying.

    Deliberately lives here rather than in developers.py — that router is
    require_role("lead")-gated, and every developer needs to see the lanes.
    """
    org = await _get_org(clerk_org_id, db)

    # Correlated subquery for the per-person count, so this stays one round trip
    # instead of a query per lane.
    scheduled_count = (
        select(func.count(Task.id))
        .where(
            Task.assignee_id == Developer.id,
            Task.scheduled_date.is_not(None),
            Task.status != TaskStatus.DONE.value,
        )
        .correlate(Developer)
        .scalar_subquery()
    )

    rows = (
        await db.execute(
            select(Developer, scheduled_count)
            .join(Team, Developer.team_id == Team.id)
            .where(Team.organization_id == org.id, Developer.is_active.is_(True))
            .order_by(Developer.created_at, Developer.id)
        )
    ).all()

    return {"members": [_member_json(dev, count or 0) for dev, count in rows]}


@router.post("/generate")
async def generate(
    force: bool = False,
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    org, session = await _session_and_brief(clerk_org_id, db)

    # Idempotent unless `force`: return the existing roadmap, or replace it with a
    # fresh one when the user has added detail and wants to regenerate.
    existing = await _load_project(session.id, db)
    if existing is not None:
        if not force:
            return _project_json(existing)
        await db.delete(existing)  # cascades to milestones + tasks
        await db.flush()

    api_key = await roadmap_generator.resolve_api_key(clerk_org_id, db)

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


def _validate_status(v: str | None) -> str | None:
    if v is not None and v not in _VALID_STATUSES:
        raise ValueError(f"status must be one of {sorted(_VALID_STATUSES)}")
    return v


def _validate_title(v: str | None) -> str | None:
    if v is not None:
        v = v.strip()
        if not (1 <= len(v) <= 255):
            raise ValueError("title must be 1-255 characters")
    return v


def _validate_duration(v: int | None) -> int | None:
    if v is not None and not (_MIN_DURATION_MINUTES <= v <= _MAX_DURATION_MINUTES):
        raise ValueError(
            f"durationMinutes must be between {_MIN_DURATION_MINUTES} and {_MAX_DURATION_MINUTES}"
        )
    return v


@router.post("/regenerate")
async def regenerate(
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    org, session = await _session_and_brief(clerk_org_id, db)

    team = await db.scalar(
        select(Team).where(Team.organization_id == org.id).order_by(Team.created_at)
    )
    if team is None:
        raise HTTPException(status_code=409, detail="no_team_for_org")

    api_key = await roadmap_generator.resolve_api_key(clerk_org_id, db)

    try:
        await roadmap_generator.regenerate_roadmap(session, team, api_key, db)
    except ValueError as exc:  # bad key
        raise HTTPException(status_code=402, detail=str(exc))
    except RuntimeError as exc:  # upstream / model failure
        raise HTTPException(status_code=502, detail=str(exc))

    project = await _load_project(session.id, db)
    return _project_json(project)


@router.post("/adjust")
async def adjust(
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Re-plan the roadmap's upcoming tasks from the user's per-task feedback.

    Runs on Groq and is non-destructive: done/in-progress tasks are preserved,
    only `todo` tasks are re-planned. See services/roadmap_adjuster.
    """
    org, session = await _session_and_brief(clerk_org_id, db)
    project = await _load_project(session.id, db)
    if project is None:
        raise HTTPException(status_code=409, detail="no_roadmap")

    api_key = await idea_interview.resolve_api_key(clerk_org_id, db)

    try:
        await roadmap_adjuster.adjust_roadmap(project, api_key, db)
    except ValueError as exc:  # bad key
        raise HTTPException(status_code=402, detail=str(exc))
    except RuntimeError as exc:  # upstream / model failure
        raise HTTPException(status_code=502, detail=str(exc))

    project = await _load_project(session.id, db)
    return _project_json(project)


@router.post("/milestones/{milestone_id}/regenerate")
async def regenerate_milestone_endpoint(
    milestone_id: str,
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    org, session = await _session_and_brief(clerk_org_id, db)
    milestone = await _owned_milestone(milestone_id, org, db)

    api_key = await roadmap_generator.resolve_api_key(clerk_org_id, db)

    try:
        milestone = await roadmap_generator.regenerate_milestone(milestone, session, api_key, db)
    except ValueError as exc:  # bad key
        raise HTTPException(status_code=402, detail=str(exc))
    except RuntimeError as exc:  # upstream / model failure
        raise HTTPException(status_code=502, detail=str(exc))

    return _milestone_json(milestone)


class TaskUpdateRequest(BaseModel):
    """
    Every field is optional, and `model_fields_set` distinguishes "omitted"
    (leave alone) from an explicit null (clear it). That distinction is what
    lets the client unassign a task or make it all-day without needing a
    separate endpoint per operation.
    """

    status: str | None = None
    title: str | None = None
    description: str | None = None
    scheduledDate: date | None = None
    scheduledTime: time | None = None
    durationMinutes: int | None = None
    assigneeId: uuid.UUID | None = None
    sortOrder: int | None = None
    feedback: str | None = None

    @field_validator("status")
    @classmethod
    def _valid_status(cls, v: str | None) -> str | None:
        return _validate_status(v)

    @field_validator("title")
    @classmethod
    def _valid_title(cls, v: str | None) -> str | None:
        return _validate_title(v)

    @field_validator("durationMinutes")
    @classmethod
    def _valid_duration(cls, v: int | None) -> int | None:
        return _validate_duration(v)


async def _reorder_task(task: Task, new_order: int, db: AsyncSession) -> None:
    """Move `task` to `new_order` within its milestone, shifting siblings to fill the gap."""
    siblings = list(
        await db.scalars(
            select(Task).where(Task.milestone_id == task.milestone_id).order_by(Task.sort_order)
        )
    )
    if not (0 <= new_order < len(siblings)):
        raise HTTPException(status_code=422, detail="sort_order_out_of_bounds")
    siblings.remove(task)
    siblings.insert(new_order, task)
    for idx, sibling in enumerate(siblings):
        sibling.sort_order = idx


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
    if "description" in body.model_fields_set:
        task.description = body.description
    if "scheduledDate" in body.model_fields_set:
        task.scheduled_date = body.scheduledDate
    if "scheduledTime" in body.model_fields_set:
        task.scheduled_time = body.scheduledTime
    if "durationMinutes" in body.model_fields_set:
        task.duration_minutes = body.durationMinutes
    if "assigneeId" in body.model_fields_set:
        if body.assigneeId is not None:
            await _owned_developer(body.assigneeId, org, db)  # cross-tenant guard
        task.assignee_id = body.assigneeId
    if "feedback" in body.model_fields_set:
        task.feedback = body.feedback
    # Reorder last: it renumbers every sibling, so it must run after this task's
    # own fields are settled.
    if body.sortOrder is not None:
        await _reorder_task(task, body.sortOrder, db)

    await db.commit()
    await db.refresh(task)
    return _task_json(task)


class TaskCreateRequest(BaseModel):
    title: str
    description: str | None = None
    milestoneId: uuid.UUID | None = None
    assigneeId: uuid.UUID | None = None
    scheduledDate: date | None = None
    scheduledTime: time | None = None
    durationMinutes: int | None = None

    @field_validator("title")
    @classmethod
    def _valid_title(cls, v: str) -> str:
        return _validate_title(v)

    @field_validator("durationMinutes")
    @classmethod
    def _valid_duration(cls, v: int | None) -> int | None:
        return _validate_duration(v)


@router.post("/tasks", status_code=201)
async def create_task(
    body: TaskCreateRequest,
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """Create a task — the sidebar lane's "+" button and the day-column quick add."""
    org = await _get_org(clerk_org_id, db)
    session = await db.scalar(
        select(OnboardingSession).where(OnboardingSession.organization_id == org.id)
    )
    project = await _load_project(session.id, db) if session else None
    if project is None or not project.milestones:
        raise HTTPException(status_code=409, detail="no_milestones")

    if body.milestoneId is not None:
        milestone = next((m for m in project.milestones if m.id == body.milestoneId), None)
        if milestone is None:
            raise HTTPException(status_code=404, detail="milestone_not_found")
    else:
        # Unfiled work lands at the end of the plan rather than being rejected.
        milestone = max(project.milestones, key=lambda m: m.sort_order)

    if body.assigneeId is not None:
        await _owned_developer(body.assigneeId, org, db)  # cross-tenant guard

    next_sort = (
        await db.scalar(
            select(func.coalesce(func.max(Task.sort_order), -1) + 1).where(
                Task.milestone_id == milestone.id
            )
        )
    ) or 0

    task = Task(
        milestone_id=milestone.id,
        title=body.title,
        description=body.description,
        status=TaskStatus.TODO.value,
        sort_order=next_sort,
        scheduled_date=body.scheduledDate,
        scheduled_time=body.scheduledTime,
        duration_minutes=body.durationMinutes,
        assignee_id=body.assigneeId,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return _task_json(task)


class TaskRescheduleItem(BaseModel):
    id: uuid.UUID
    scheduledDate: date | None = None
    scheduledTime: time | None = None
    assigneeId: uuid.UUID | None = None


class TaskRescheduleRequest(BaseModel):
    updates: list[TaskRescheduleItem]

    @field_validator("updates")
    @classmethod
    def _non_empty(cls, v: list) -> list:
        if not (1 <= len(v) <= 200):
            raise ValueError("updates must contain between 1 and 200 items")
        return v


@router.post("/tasks/reschedule")
async def reschedule_tasks(
    body: TaskRescheduleRequest,
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Bulk move/reassign, for drag-drop and multi-select operations.

    All-or-nothing: if any id is unknown or belongs to another org, nothing is
    applied. A partial apply would leave the board in a state the user never
    asked for and cannot easily undo.
    """
    org = await _get_org(clerk_org_id, db)
    ids = [u.id for u in body.updates]
    found = await _owned_tasks(ids, org, db)
    if len(found) != len(set(ids)):
        raise HTTPException(status_code=404, detail="task_not_found")

    # Validate every referenced assignee before mutating anything, for the same
    # all-or-nothing reason.
    for dev_id in {u.assigneeId for u in body.updates if u.assigneeId is not None}:
        await _owned_developer(dev_id, org, db)

    for update in body.updates:
        task = found[update.id]
        fields = update.model_fields_set
        if "scheduledDate" in fields:
            task.scheduled_date = update.scheduledDate
        if "scheduledTime" in fields:
            task.scheduled_time = update.scheduledTime
        if "assigneeId" in fields:
            task.assignee_id = update.assigneeId

    await db.commit()
    for task in found.values():
        await db.refresh(task)
    return {"tasks": [_task_json(found[u.id]) for u in body.updates]}


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


# ─── project refine-chat (talk to Groq to add detail before/after planning) ─────
async def _get_or_create_session(
    org: Organization, user_id: str, db: AsyncSession
) -> OnboardingSession:
    session = await db.scalar(
        select(OnboardingSession).where(OnboardingSession.organization_id == org.id)
    )
    if session is None:
        session = OnboardingSession(
            organization_id=org.id, created_by_user_id=user_id, status="in_progress"
        )
        db.add(session)
        await db.flush()
    return session


@router.get("/status")
async def get_status(
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """Lightweight, side-effect-free readiness check for the planner's ? badge."""
    org = await _get_org(clerk_org_id, db)
    session = await db.scalar(
        select(OnboardingSession).where(OnboardingSession.organization_id == org.id)
    )
    brief = session.project_brief if session else None
    missing = idea_interview.missing_fields(brief)
    has_roadmap = False
    if session is not None:
        has_roadmap = (
            await db.scalar(
                select(func.count(Project.id)).where(
                    Project.onboarding_session_id == session.id
                )
            )
        ) > 0
    return {
        "hasRoadmap": has_roadmap,
        "needsMoreInfo": len(missing) > 0,
        "missingFields": missing,
    }


@router.get("/chat")
async def get_chat(
    clerk_org_id: str = Depends(get_current_org_id),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    org = await _get_org(clerk_org_id, db)
    session = await _get_or_create_session(org, user_id, db)

    count = await db.scalar(
        select(func.count(OnboardingMessage.id)).where(
            OnboardingMessage.session_id == session.id
        )
    )
    if not count:
        db.add(OnboardingMessage(session_id=session.id, role="assistant", content=_CHAT_OPENER, seq=0))
    await db.commit()

    rows = (
        await db.execute(
            select(OnboardingMessage)
            .where(OnboardingMessage.session_id == session.id)
            .order_by(OnboardingMessage.seq)
        )
    ).scalars().all()
    missing = idea_interview.missing_fields(session.project_brief)
    return {
        "messages": [
            {
                "id": str(m.id),
                "role": m.role,
                "content": m.content,
                "createdAt": m.created_at.isoformat() if m.created_at else None,
            }
            for m in rows
        ],
        "brief": session.project_brief,
        "missingFields": missing,
        "needsMoreInfo": len(missing) > 0,
    }


class ChatMessageRequest(BaseModel):
    content: str

    @field_validator("content")
    @classmethod
    def _valid(cls, v: str) -> str:
        v = v.strip()
        if not (1 <= len(v) <= 4000):
            raise ValueError("content must be 1-4000 characters")
        return v


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


async def _chat_stream(session: OnboardingSession, content: str, api_key: str, db: AsyncSession):
    """SSE: `token` events while Groq replies, then `brief`, then `done` — or `error`."""
    queue: asyncio.Queue = asyncio.Queue()

    async def on_token(text: str) -> None:
        await queue.put(("token", {"text": text}))

    async def runner() -> None:
        try:
            result = await idea_interview.run_interview_turn(session, content, api_key, db, on_token)
            missing = result["missing_fields"]
            await queue.put(("brief", {
                "brief": result["brief"],
                "missingFields": missing,
                "needsMoreInfo": len(missing) > 0,
            }))
            await queue.put(("done", {"messageId": result["message_id"], "status": result["status"]}))
        except Exception as e:  # noqa: BLE001 — surface any failure to the client
            logger.exception("[roadmap-chat] turn failed for session %s", session.id)
            await queue.put(("error", {"message": str(e) or "Chat failed"}))
        finally:
            await queue.put(None)

    task = asyncio.create_task(runner())
    try:
        while True:
            item = await queue.get()
            if item is None:
                break
            event, data = item
            yield _sse(event, data)
    finally:
        if not task.done():
            task.cancel()


@router.post("/chat/message")
async def chat_message(
    body: ChatMessageRequest,
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    org = await _get_org(clerk_org_id, db)
    session = await db.scalar(
        select(OnboardingSession).where(OnboardingSession.organization_id == org.id)
    )
    if session is None:
        raise HTTPException(status_code=409, detail="chat_not_started")

    api_key = await idea_interview.resolve_api_key(clerk_org_id, db)
    return StreamingResponse(
        _chat_stream(session, body.content, api_key, db),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
