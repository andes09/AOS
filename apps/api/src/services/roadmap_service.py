"""
Roadmap service layer — the shared implementation behind both the REST
roadmap router (`src/routers/roadmap.py`) and the MCP tools
(`src/mcp_server/tools.py`). Extracted from roadmap.py (Stage 5, MCP server
build) so both surfaces call one implementation instead of duplicating org/
project/task resolution and JSON shaping.

Extracted against the CURRENT, already-project-scoped roadmap.py (from Stage
1's Project Hub): every lookup here takes a `Project` (not `Organization`)
and filters through Milestone.project_id, exactly like the router functions
this was lifted from. `list_tasks`/`get_members`/`get_roadmap_status`/
`claim_next_task`/`complete_task` are net-new — MCP needs them but no REST
route exposed the same shape before this stage.
"""

import uuid
from datetime import date, datetime, time

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.developer import Developer
from src.models.milestone import Milestone
from src.models.onboarding_session import OnboardingSession
from src.models.organization import Organization
from src.models.project import Project
from src.models.task import Task, TaskStatus
from src.models.team import Team
from src.services import idea_interview

# Must match LANE_COLOR_COUNT in apps/web/src/lib/laneColors.ts and the
# --lane-N-* triples in apps/web/src/styles/tokens.css.
_LANE_COLOR_COUNT = 10

# A task shorter than 5 minutes is unrenderable on the grid; longer than a day
# is a data-entry slip, not a plan.
_MIN_DURATION_MINUTES = 5
_MAX_DURATION_MINUTES = 1440

_VALID_STATUSES = {s.value for s in TaskStatus}


def _status_str(status) -> str:
    """The status as a plain string.

    `Task.status` is a SAEnum(native_enum=False) column, so a `Task` loaded
    from the DB carries the `TaskStatus` enum *member*, not its string value
    — comparing it with `==`/`!=` against a literal string silently
    misbehaves once the row has round-tripped. Normalize before any Python-
    side comparison (same helper shape as integrations/github/events.py's
    `_status_str` / roadmap_adjuster.py's private helper of the same name;
    kept as a separate copy here per project_common.py's own precedent of
    small shared helpers living next to their callers rather than a grab-bag
    utils module).
    """
    return status.value if isinstance(status, TaskStatus) else status


# ─── serialization ─────────────────────────────────────────────────────────────
def task_json(task: Task) -> dict:
    return {
        "id": str(task.id),
        "shortId": task.short_id,
        "title": task.title,
        "description": task.description,
        # _status_str, not task.status directly: REST responses get away
        # with the raw enum member because FastAPI's jsonable_encoder
        # auto-unwraps it, but MCP tool results are plain dicts with no such
        # encoder guaranteed downstream — normalize here so both surfaces
        # are correct regardless.
        "status": _status_str(task.status),
        "sortOrder": task.sort_order,
        "scheduledDate": task.scheduled_date.isoformat() if task.scheduled_date else None,
        # "%H:%M", not isoformat(): isoformat emits seconds ("09:30:00"), which
        # the frontend's time helpers would have to strip on every render.
        "scheduledTime": task.scheduled_time.strftime("%H:%M") if task.scheduled_time else None,
        "durationMinutes": task.duration_minutes,
        "parallel": bool(task.parallel),
        "assigneeId": str(task.assignee_id) if task.assignee_id else None,
        "feedback": task.feedback,
        "completedAt": task.completed_at.isoformat() if task.completed_at else None,
        "completionNote": task.completion_note,
    }


def initials(name: str) -> str:
    """First+last initial. Computed here so every surface agrees on the fallback."""
    parts = [p for p in (name or "").split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def member_json(dev: Developer, scheduled_count: int) -> dict:
    return {
        "id": str(dev.id),
        "name": dev.name,
        "role": dev.role,
        "email": dev.email,
        "colorIndex": (dev.color_index or 0) % _LANE_COLOR_COUNT,
        "avatarUrl": dev.avatar_url,
        "initials": initials(dev.name),
        "isActive": bool(dev.is_active),
        "scheduledCount": scheduled_count,
    }


def milestone_json(m: Milestone) -> dict:
    return {
        "id": str(m.id),
        "title": m.title,
        "description": m.description,
        "sortOrder": m.sort_order,
        "tasks": [task_json(t) for t in m.tasks],
    }


def project_json(project: Project) -> dict:
    return {
        "id": str(project.id),
        "name": project.name,
        "summary": project.summary,
        "purpose": project.purpose,
        "status": project.status,
        "milestones": [milestone_json(m) for m in project.milestones],
    }


# ─── shared lookups ─────────────────────────────────────────────────────────────
async def owned_task(task_id: str, project: Project, db: AsyncSession) -> Task:
    """Load a task, ensuring it belongs to `project`. 404 otherwise.

    Filtering on Milestone.project_id (not just the org) closes a real
    cross-tenant-within-org gap: a client could otherwise pass a valid
    project_id for project A but a task_id belonging to sibling project B in
    the same org, and an org-only check would wrongly authorize it.
    """
    try:
        tid = uuid.UUID(task_id) if isinstance(task_id, str) else task_id
    except ValueError:
        raise HTTPException(status_code=404, detail="task_not_found")
    task = await db.scalar(
        select(Task)
        .join(Milestone, Task.milestone_id == Milestone.id)
        .where(Task.id == tid, Milestone.project_id == project.id)
    )
    if task is None:
        raise HTTPException(status_code=404, detail="task_not_found")
    return task


async def owned_developer(dev_id: uuid.UUID, org: Organization, db: AsyncSession) -> Developer:
    """
    Load a developer, ensuring they belong to the caller's org. 404 otherwise.

    Stays org-scoped (not project-scoped): developers aren't project-scoped
    entities, they're shared across every project in the org. This is the
    cross-tenant guard for assignment — without it, a PATCH carrying an
    assigneeId guessed from another organization would succeed, silently
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


async def owned_tasks(task_ids: list[uuid.UUID], project: Project, db: AsyncSession) -> dict:
    """
    Bulk sibling of `owned_task` — one query for the whole batch rather than N.

    Returns {id: Task}. Callers are responsible for treating a short result as a
    failure; see the reschedule endpoint, which refuses to apply partially.
    """
    rows = (
        await db.execute(
            select(Task)
            .join(Milestone, Task.milestone_id == Milestone.id)
            .where(Task.id.in_(task_ids), Milestone.project_id == project.id)
        )
    ).scalars().all()
    return {t.id: t for t in rows}


async def owned_milestone(milestone_id: str, project: Project, db: AsyncSession) -> Milestone:
    """Load a milestone (with tasks), ensuring it belongs to `project`. 404 otherwise."""
    try:
        mid = uuid.UUID(milestone_id) if isinstance(milestone_id, str) else milestone_id
    except ValueError:
        raise HTTPException(status_code=404, detail="milestone_not_found")
    milestone = await db.scalar(
        select(Milestone)
        .where(Milestone.id == mid, Milestone.project_id == project.id)
        .options(selectinload(Milestone.tasks))
    )
    if milestone is None:
        raise HTTPException(status_code=404, detail="milestone_not_found")
    return milestone


async def task_blocked_by_earlier_sibling(task: Task, project: Project, db: AsyncSession) -> bool:
    """
    True if `task` is a sequential (non-parallel) task that can't be completed
    yet because an earlier sequential task in the plan is still unfinished.
    Mirrors the "waits its turn" gating the planner UI computes client-side
    (DayAgenda.tsx's continuous "Up next" stream) so the server enforces the
    same rule instead of trusting the UI alone.

    "Earlier" spans the whole project now, not a single calendar day — the
    planner has one unlimited queue rather than day-by-day silos. Same
    ordering convention as `claim_next_task` below: scheduled_date ascending
    (nulls last), then scheduled_time (untimed leads), then plan order.

    Never blocks parallel tasks — those have no dependency on what's before
    them, scheduled or not.
    """
    if task.parallel:
        return False

    siblings = (
        await db.scalars(
            select(Task)
            .join(Milestone, Task.milestone_id == Milestone.id)
            .where(Milestone.project_id == project.id)
            .order_by(
                Task.scheduled_date.is_(None),
                Task.scheduled_date,
                Task.scheduled_time.is_(None).desc(),
                Task.scheduled_time,
                Milestone.sort_order,
                Task.sort_order,
            )
        )
    ).all()

    for sibling in siblings:
        if sibling.id == task.id:
            return False
        if not sibling.parallel and _status_str(sibling.status) != TaskStatus.DONE.value:
            return True
    return False


def require_brief(session: OnboardingSession) -> None:
    if not session.project_brief:
        raise HTTPException(
            status_code=409,
            # Deliberately not "finish onboarding" — the planner's refine-chat
            # can supply the brief too, so onboarding isn't the only way out.
            detail="Add some project details first — there's no project brief to plan from yet.",
        )


async def resolve_project_team(project: Project, db: AsyncSession) -> Team:
    team = await db.scalar(select(Team).where(Team.id == project.team_id))
    if team is None:
        raise HTTPException(status_code=409, detail="no_team_for_org")
    return team


# ─── validators ─────────────────────────────────────────────────────────────────
def validate_status(v: str | None) -> str | None:
    if v is not None and v not in _VALID_STATUSES:
        raise ValueError(f"status must be one of {sorted(_VALID_STATUSES)}")
    return v


def validate_title(v: str | None) -> str | None:
    if v is not None:
        v = v.strip()
        if not (1 <= len(v) <= 255):
            raise ValueError("title must be 1-255 characters")
    return v


def validate_duration(v: int | None) -> int | None:
    if v is not None and not (_MIN_DURATION_MINUTES <= v <= _MAX_DURATION_MINUTES):
        raise ValueError(
            f"durationMinutes must be between {_MIN_DURATION_MINUTES} and {_MAX_DURATION_MINUTES}"
        )
    return v


# ─── members / status (extracted verbatim from the GET handlers) ────────────────
async def get_members(org: Organization, project: Project, db: AsyncSession) -> dict:
    """
    Every active person in the org, their lane color, and how much open
    scheduled work they're carrying *on this project*.

    Membership stays org-scoped (every developer in the org can be assigned),
    but the workload count is scoped to this project's tasks only — with
    multiple projects per org, counting org-wide would conflate unrelated
    projects' workloads into one badge.
    """
    scheduled_count = (
        select(func.count(Task.id))
        .join(Milestone, Task.milestone_id == Milestone.id)
        .where(
            Task.assignee_id == Developer.id,
            Milestone.project_id == project.id,
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

    return {"members": [member_json(dev, count or 0) for dev, count in rows]}


def get_roadmap_status(project: Project) -> dict:
    """Lightweight, side-effect-free readiness check for the planner's ? badge."""
    missing = idea_interview.missing_fields(project.onboarding_session.project_brief)
    return {
        "hasRoadmap": bool(project.milestones),
        "needsMoreInfo": len(missing) > 0,
        "missingFields": missing,
    }


# ─── MCP-only queries (no REST equivalent before this stage) ────────────────────
async def list_tasks(
    project: Project,
    db: AsyncSession,
    *,
    status: str | None = None,
    assignee_id: uuid.UUID | None = None,
    milestone_id: uuid.UUID | None = None,
    scheduled_after: date | None = None,
    scheduled_before: date | None = None,
) -> list[Task]:
    """Filtered task list, scoped to `project`. Used by the `list_tasks` MCP tool."""
    query = (
        select(Task)
        .join(Milestone, Task.milestone_id == Milestone.id)
        .where(Milestone.project_id == project.id)
    )
    if status is not None:
        query = query.where(Task.status == status)
    if assignee_id is not None:
        query = query.where(Task.assignee_id == assignee_id)
    if milestone_id is not None:
        query = query.where(Task.milestone_id == milestone_id)
    if scheduled_after is not None:
        query = query.where(Task.scheduled_date >= scheduled_after)
    if scheduled_before is not None:
        query = query.where(Task.scheduled_date <= scheduled_before)
    query = query.order_by(Milestone.sort_order, Task.sort_order)

    rows = (await db.execute(query)).scalars().all()
    return list(rows)


async def claim_next_task(project: Project, developer: Developer, db: AsyncSession) -> Task | None:
    """
    Claims the next `todo`, unassigned task in `project` by schedule order and
    self-assigns it to `developer`. Returns None if nothing's claimable.

    "Next" has no dependency-graph meaning yet (Task has no blocking model) —
    this is "next by schedule order": scheduled_date ascending (nulls last),
    then milestone sort_order, then task sort_order.
    """
    task = await db.scalar(
        select(Task)
        .join(Milestone, Task.milestone_id == Milestone.id)
        .where(
            Milestone.project_id == project.id,
            Task.status == TaskStatus.TODO.value,
            Task.assignee_id.is_(None),
        )
        .order_by(
            Task.scheduled_date.is_(None),  # False (has a date) sorts before True (null) — nulls last
            Task.scheduled_date,
            Milestone.sort_order,
            Task.sort_order,
        )
        .limit(1)
    )
    if task is None:
        return None
    task.assignee_id = developer.id
    await db.commit()
    await db.refresh(task)
    return task


async def complete_task(task: Task, note: str | None, db: AsyncSession) -> Task:
    """
    Marks `task` done. `completion_note` is only overwritten when `note` is
    not None, so re-calling without a note doesn't clobber a prior one —
    the idempotency contract the `complete_task` MCP tool relies on.
    """
    task.status = TaskStatus.DONE.value
    task.completed_at = datetime.utcnow()
    if note is not None:
        task.completion_note = note
    await db.commit()
    await db.refresh(task)
    return task
