"""
Roadmap — the personal, day-by-day project plan behind the calendar view.

One roadmap (Project → Milestones → Tasks) per project. An org can have
multiple projects (see docs/plans/2026-07-20-project-hub.md); every route
below is scoped by project_id, resolved via project_common._owned_project
(404s if the project doesn't belong to the caller's org). Tasks carry a
scheduled_date (calendar day) and a status the user flips to check things
off, plus delete.

Route handlers here are thin adapters over src/services/roadmap_service.py
(extracted in Stage 5, the MCP server build, so REST and MCP tools share one
implementation) — JSON shaping, lookups, and validators all live there now.

GET    /api/projects/{project_id}/roadmap                              → the project's roadmap
GET    /api/projects/{project_id}/roadmap/members                      → team members + lane colors (planner sidebar)
POST   /api/projects/{project_id}/roadmap/generate                     → idempotent repair: regenerate from brief only if no milestones exist yet
POST   /api/projects/{project_id}/roadmap/regenerate                   → replan the whole roadmap
POST   /api/projects/{project_id}/roadmap/adjust                       → non-destructive re-plan from per-task feedback
POST   /api/projects/{project_id}/roadmap/extend-day                   → generate a few more todo tasks for one day
POST   /api/projects/{project_id}/roadmap/milestones/{id}/regenerate   → replan one milestone
POST   /api/projects/{project_id}/roadmap/tasks                        → create a task
POST   /api/projects/{project_id}/roadmap/tasks/reschedule             → bulk move/reassign (drag-drop)
PATCH  /api/projects/{project_id}/roadmap/tasks/{task_id}              → update status / title / description /
                                                                          schedule / assignee / sort order
DELETE /api/projects/{project_id}/roadmap/tasks/{task_id}              → delete a task
GET    /api/projects/{project_id}/roadmap/status                       → readiness check for the planner's badge
GET    /api/projects/{project_id}/roadmap/chat                         → refine-chat transcript
POST   /api/projects/{project_id}/roadmap/chat/message                 → refine-chat turn (SSE)
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

from src.auth import get_current_org_id, get_current_user_id
from src.database import get_db
from src.models.onboarding_session import OnboardingMessage
from src.models.task import Task, TaskStatus
from src.routers.project_common import _get_org, _owned_project
from src.services import idea_interview, roadmap_adjuster, roadmap_generator
from src.services import roadmap_service as svc
from src.services.task_ids import allocate_short_id

logger = logging.getLogger(__name__)

# Opener shown when the refine-chat has no history yet (rare — onboarded orgs
# already carry their interview transcript on the shared session).
_CHAT_OPENER = (
    "Tell me more about your project — the more detail you give (goals, tech stack, "
    "constraints, key features), the more precise and technical I can make your plan."
)

router = APIRouter(prefix="/api/projects/{project_id}/roadmap", tags=["roadmap"])


# ─── endpoints ──────────────────────────────────────────────────────────────────
@router.get("")
async def get_roadmap(
    project_id: uuid.UUID,
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    org = await _get_org(clerk_org_id, db)
    project = await _owned_project(project_id, org, db)
    return svc.project_json(project)


@router.get("/members")
async def get_members(
    project_id: uuid.UUID,
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """
    The planner sidebar's lanes: every active person in the org, their lane
    color, and how much open scheduled work they're carrying *on this
    project*.

    Deliberately lives here rather than in developers.py — that router is
    require_role("lead")-gated, and every developer needs to see the lanes.
    """
    org = await _get_org(clerk_org_id, db)
    project = await _owned_project(project_id, org, db)
    return await svc.get_members(org, project, db)


@router.post("/generate")
async def generate(
    project_id: uuid.UUID,
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Idempotent repair endpoint, not the "create a new project" path (that's
    POST /api/projects/sessions/{id}/generate now). Only reachable for a
    project that already exists in the URL: returns as-is if milestones
    already exist, otherwise generates them from the project's onboarding
    brief.

    Uses regenerate_roadmap (not generate_roadmap) even on the "no
    milestones yet" branch: generate_roadmap would INSERT a brand-new Project
    row, which collides with the unique FK on onboarding_session_id since
    this project already has one. regenerate_roadmap finds the existing
    Project by that same FK and populates it in place.
    """
    org = await _get_org(clerk_org_id, db)
    project = await _owned_project(project_id, org, db)
    if project.milestones:
        return svc.project_json(project)

    session = project.onboarding_session
    svc.require_brief(session)
    team = await svc.resolve_project_team(project, db)
    api_key = await idea_interview.resolve_api_key(clerk_org_id, db)

    try:
        await roadmap_generator.regenerate_roadmap(session, team, api_key, db)
    except ValueError as exc:  # bad key
        raise HTTPException(status_code=402, detail=str(exc))
    except RuntimeError as exc:  # upstream / model failure
        raise HTTPException(status_code=502, detail=str(exc))

    project = await _owned_project(project_id, org, db)
    return svc.project_json(project)


@router.post("/regenerate")
async def regenerate(
    project_id: uuid.UUID,
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    org = await _get_org(clerk_org_id, db)
    project = await _owned_project(project_id, org, db)
    session = project.onboarding_session
    svc.require_brief(session)
    team = await svc.resolve_project_team(project, db)

    api_key = await idea_interview.resolve_api_key(clerk_org_id, db)

    try:
        await roadmap_generator.regenerate_roadmap(session, team, api_key, db)
    except ValueError as exc:  # bad key
        raise HTTPException(status_code=402, detail=str(exc))
    except RuntimeError as exc:  # upstream / model failure
        raise HTTPException(status_code=502, detail=str(exc))

    project = await _owned_project(project_id, org, db)
    return svc.project_json(project)


@router.post("/adjust")
async def adjust(
    project_id: uuid.UUID,
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Re-plan the roadmap's upcoming tasks from the user's per-task feedback.

    Runs on Groq and is non-destructive: done/in-progress tasks are preserved,
    only `todo` tasks are re-planned. See services/roadmap_adjuster.
    """
    org = await _get_org(clerk_org_id, db)
    project = await _owned_project(project_id, org, db)
    if not project.milestones:
        raise HTTPException(status_code=409, detail="no_roadmap")

    api_key = await idea_interview.resolve_api_key(clerk_org_id, db)

    try:
        await roadmap_adjuster.adjust_roadmap(project, api_key, db)
    except ValueError as exc:  # bad key
        raise HTTPException(status_code=402, detail=str(exc))
    except RuntimeError as exc:  # upstream / model failure
        raise HTTPException(status_code=502, detail=str(exc))

    project = await _owned_project(project_id, org, db)
    return svc.project_json(project)


class ExtendDayRequest(BaseModel):
    date: date


@router.post("/extend-day")
async def extend_day(
    project_id: uuid.UUID,
    body: ExtendDayRequest,
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Generate a few more `todo` tasks for a single day, once the user has cleared
    everything scheduled on it and wants to keep going. Non-destructive: existing
    tasks are untouched. See services/roadmap_adjuster.extend_day.
    """
    org = await _get_org(clerk_org_id, db)
    project = await _owned_project(project_id, org, db)
    if not project.milestones:
        raise HTTPException(status_code=409, detail="no_roadmap")

    api_key = await idea_interview.resolve_api_key(clerk_org_id, db)

    try:
        await roadmap_adjuster.extend_day(project, body.date, api_key, db)
    except ValueError as exc:  # bad key
        raise HTTPException(status_code=402, detail=str(exc))
    except RuntimeError as exc:  # upstream / model failure
        raise HTTPException(status_code=502, detail=str(exc))

    project = await _owned_project(project_id, org, db)
    return svc.project_json(project)


@router.post("/milestones/{milestone_id}/regenerate")
async def regenerate_milestone_endpoint(
    project_id: uuid.UUID,
    milestone_id: str,
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    org = await _get_org(clerk_org_id, db)
    project = await _owned_project(project_id, org, db)
    milestone = await svc.owned_milestone(milestone_id, project, db)
    session = project.onboarding_session

    api_key = await idea_interview.resolve_api_key(clerk_org_id, db)

    try:
        milestone = await roadmap_generator.regenerate_milestone(milestone, session, api_key, db)
    except ValueError as exc:  # bad key
        raise HTTPException(status_code=402, detail=str(exc))
    except RuntimeError as exc:  # upstream / model failure
        raise HTTPException(status_code=502, detail=str(exc))

    return svc.milestone_json(milestone)


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
        return svc.validate_status(v)

    @field_validator("title")
    @classmethod
    def _valid_title(cls, v: str | None) -> str | None:
        return svc.validate_title(v)

    @field_validator("durationMinutes")
    @classmethod
    def _valid_duration(cls, v: int | None) -> int | None:
        return svc.validate_duration(v)


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
    project_id: uuid.UUID,
    task_id: str,
    body: TaskUpdateRequest,
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    org = await _get_org(clerk_org_id, db)
    project = await _owned_project(project_id, org, db)
    task = await svc.owned_task(task_id, project, db)

    if body.status is not None:
        if body.status == TaskStatus.DONE.value and await svc.task_blocked_by_earlier_sibling(task, project, db):
            raise HTTPException(status_code=409, detail="task_blocked_by_earlier_task")
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
            await svc.owned_developer(body.assigneeId, org, db)  # cross-tenant guard
        task.assignee_id = body.assigneeId
    if "feedback" in body.model_fields_set:
        task.feedback = body.feedback
    # Reorder last: it renumbers every sibling, so it must run after this task's
    # own fields are settled.
    if body.sortOrder is not None:
        await _reorder_task(task, body.sortOrder, db)

    await db.commit()
    await db.refresh(task)
    return svc.task_json(task)


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
        return svc.validate_title(v)

    @field_validator("durationMinutes")
    @classmethod
    def _valid_duration(cls, v: int | None) -> int | None:
        return svc.validate_duration(v)


@router.post("/tasks", status_code=201)
async def create_task(
    project_id: uuid.UUID,
    body: TaskCreateRequest,
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """Create a task — the sidebar lane's "+" button and the day-column quick add."""
    org = await _get_org(clerk_org_id, db)
    project = await _owned_project(project_id, org, db)
    if not project.milestones:
        raise HTTPException(status_code=409, detail="no_milestones")

    if body.milestoneId is not None:
        milestone = next((m for m in project.milestones if m.id == body.milestoneId), None)
        if milestone is None:
            raise HTTPException(status_code=404, detail="milestone_not_found")
    else:
        # Unfiled work lands at the end of the plan rather than being rejected.
        milestone = max(project.milestones, key=lambda m: m.sort_order)

    if body.assigneeId is not None:
        await svc.owned_developer(body.assigneeId, org, db)  # cross-tenant guard

    next_sort = (
        await db.scalar(
            select(func.coalesce(func.max(Task.sort_order), -1) + 1).where(
                Task.milestone_id == milestone.id
            )
        )
    ) or 0

    task = Task(
        milestone_id=milestone.id,
        short_id=await allocate_short_id(org, db),
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
    return svc.task_json(task)


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
    project_id: uuid.UUID,
    body: TaskRescheduleRequest,
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Bulk move/reassign, for drag-drop and multi-select operations.

    All-or-nothing: if any id is unknown or belongs to another project,
    nothing is applied. A partial apply would leave the board in a state the
    user never asked for and cannot easily undo.
    """
    org = await _get_org(clerk_org_id, db)
    project = await _owned_project(project_id, org, db)
    ids = [u.id for u in body.updates]
    found = await svc.owned_tasks(ids, project, db)
    if len(found) != len(set(ids)):
        raise HTTPException(status_code=404, detail="task_not_found")

    # Validate every referenced assignee before mutating anything, for the same
    # all-or-nothing reason.
    for dev_id in {u.assigneeId for u in body.updates if u.assigneeId is not None}:
        await svc.owned_developer(dev_id, org, db)

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
    return {"tasks": [svc.task_json(found[u.id]) for u in body.updates]}


@router.delete("/tasks/{task_id}", status_code=204)
async def delete_task(
    project_id: uuid.UUID,
    task_id: str,
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    org = await _get_org(clerk_org_id, db)
    project = await _owned_project(project_id, org, db)
    task = await svc.owned_task(task_id, project, db)
    await db.delete(task)
    await db.commit()
    return Response(status_code=204)


# ─── project refine-chat (talk to Groq to add detail before/after planning) ─────
@router.get("/status")
async def get_status(
    project_id: uuid.UUID,
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """Lightweight, side-effect-free readiness check for the planner's ? badge."""
    org = await _get_org(clerk_org_id, db)
    project = await _owned_project(project_id, org, db)
    return svc.get_roadmap_status(project)


@router.get("/chat")
async def get_chat(
    project_id: uuid.UUID,
    clerk_org_id: str = Depends(get_current_org_id),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    org = await _get_org(clerk_org_id, db)
    project = await _owned_project(project_id, org, db)
    session = project.onboarding_session

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


async def _chat_stream(session, content: str, api_key: str, db: AsyncSession):
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
    project_id: uuid.UUID,
    body: ChatMessageRequest,
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    org = await _get_org(clerk_org_id, db)
    project = await _owned_project(project_id, org, db)
    session = project.onboarding_session

    api_key = await idea_interview.resolve_api_key(clerk_org_id, db)
    return StreamingResponse(
        _chat_stream(session, body.content, api_key, db),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
