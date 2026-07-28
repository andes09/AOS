"""
Roadmap adjuster — re-plans a project's UPCOMING tasks from the user's progress
feedback, non-destructively.

Unlike roadmap_generator (Anthropic, and its regenerate paths that delete and
rebuild everything), this runs on Groq and treats completed work as fixed
history: `done` / `in_progress` tasks are never changed or rescheduled, so their
status and assignee survive. Only `todo` tasks — in the milestones the model
actually returns — are replaced with a fresh, feedback-aware, timed schedule.

One forced-tool Groq call (OpenAI-compatible), validated before any DB write.
"""

import json
import logging
from datetime import date

from openai import APIError, AsyncOpenAI, AuthenticationError, RateLimitError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.config import settings
from src.models.milestone import Milestone
from src.models.project import Project
from src.models.task import Task
from src.services import roadmap_generator
from src.services.cost_tracker import record_generation_cost

logger = logging.getLogger(__name__)

_MODEL = settings.groq_model
_MAX_TOKENS = 8192

_SYSTEM_PROMPT = """You are Omada's project planner, adjusting a developer's day-by-day \
roadmap based on the progress feedback they've written on their tasks.

RULES:
- Tasks marked `done` or `in_progress` are FIXED history. Never restate, change, or \
reschedule them — they are given to you only as context for where the developer is.
- Re-plan ONLY the upcoming `todo` work. Read the feedback: if something took longer or is \
blocked, push dependent work out or add a task to unblock it; if the developer moved faster or \
changed scope, tighten, add, or drop upcoming tasks accordingly.
- Return the revised upcoming tasks grouped under their milestone titles. Use the EXACT \
existing milestone title when a phase already exists; only introduce a new milestone title for \
genuinely new work.
- Every returned task needs a detailed technical `description` (3-6 sentences), a 0-based \
`dayOffset` (weekdays from today; 0 = today/next weekday), a `startTime` (24h "HH:MM", 09:00-18:00), \
and a `durationMinutes` (15-240). Lay each day out as a realistic, non-overlapping schedule.
- Set `parallel: true` on tasks that don't depend on the task before them and could be picked \
up alongside their siblings; leave it false for work that must wait on earlier tasks.
- Keep it a short, finishable near-term plan (the next ~2 weeks of weekdays), not a backlog."""

# OpenAI/Groq function-tool form (mirrors idea_interview._BRIEF_TOOL).
_ADJUST_TOOL = {
    "type": "function",
    "function": {
        "name": "adjust_plan",
        "description": "Return the revised upcoming tasks, grouped by milestone.",
        "parameters": {
            "type": "object",
            "properties": {
                "milestones": {
                    "type": "array",
                    "description": "Milestones containing revised upcoming tasks.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string", "description": "Existing milestone title, or a new one"},
                            "tasks": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "title": {"type": "string"},
                                        "description": {"type": "string"},
                                        "dayOffset": {"type": "integer", "description": "0-based weekday index from today"},
                                        "startTime": {"type": "string", "description": '24h "HH:MM"'},
                                        "durationMinutes": {"type": "integer"},
                                        "parallel": {"type": "boolean", "description": "True if this task has no dependency on the task before it and can run alongside its siblings."},
                                    },
                                    "required": ["title", "dayOffset"],
                                },
                            },
                        },
                        "required": ["title", "tasks"],
                    },
                }
            },
            "required": ["milestones"],
        },
    },
}


def _status_str(status) -> str:
    """The status as a plain string.

    The `tasks.status` column is a SAEnum, so a loaded row returns the
    `TaskStatus` member, not the string — which is neither JSON-serializable nor
    equal to a literal like "todo". Normalize before comparing or serializing.
    """
    return getattr(status, "value", status)


def _plan_context(project: Project) -> str:
    """Serialize the current plan (with statuses + feedback) as model context."""
    milestones = []
    for m in sorted(project.milestones, key=lambda x: x.sort_order):
        milestones.append(
            {
                "title": m.title,
                "tasks": [
                    {
                        "title": t.title,
                        "status": _status_str(t.status),
                        "date": t.scheduled_date.isoformat() if t.scheduled_date else None,
                        "time": t.scheduled_time.strftime("%H:%M") if t.scheduled_time else None,
                        "feedback": t.feedback or None,
                    }
                    for t in sorted(m.tasks, key=lambda x: x.sort_order)
                ],
            }
        )
    return json.dumps({"today": date.today().isoformat(), "milestones": milestones})


async def _call_tool(api_key: str, system: str, user_content: str, tool: dict):
    """One forced-tool Groq call. Returns (parsed tool args, usage)."""
    tool_name = tool["function"]["name"]
    client = AsyncOpenAI(api_key=api_key, base_url=settings.groq_base_url)
    try:
        resp = await client.chat.completions.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            tools=[tool],
            tool_choice={"type": "function", "function": {"name": tool_name}},
        )
    except AuthenticationError as exc:
        raise ValueError("Invalid Groq API key.") from exc
    except RateLimitError as exc:
        raise RuntimeError("Groq rate limit reached. Please try again in a moment.") from exc
    except APIError as exc:
        raise RuntimeError(f"Groq API error: {exc}") from exc

    tool_calls = resp.choices[0].message.tool_calls or []
    call = next((t for t in tool_calls if t.function.name == tool_name), None)
    if call is None:
        raise RuntimeError("The planner did not return a result. Please try again.")
    try:
        return json.loads(call.function.arguments), resp.usage
    except json.JSONDecodeError as exc:
        raise RuntimeError("The planner returned malformed output. Please try again.") from exc


async def _call_adjuster(api_key: str, context: str):
    """One forced-tool Groq call for the feedback re-plan."""
    return await _call_tool(api_key, _SYSTEM_PROMPT, "Current plan and feedback:\n" + context, _ADJUST_TOOL)


async def adjust_roadmap(
    project: Project, api_key: str, db: AsyncSession, today: date | None = None
) -> Project:
    """
    Re-plan the project's `todo` tasks from feedback, preserving completed work.

    Generation + validation happen before any delete, so a failed or empty
    adjustment leaves the roadmap untouched.
    """
    today = today or date.today()

    # Eager-load so _plan_context and the merge below don't lazy-load mid-async.
    project = await db.scalar(
        select(Project)
        .where(Project.id == project.id)
        .options(selectinload(Project.milestones).selectinload(Milestone.tasks))
    )

    data, usage = await _call_adjuster(api_key, _plan_context(project))

    # Validate/normalize with the generator's helpers (title clamp, day clamp,
    # time parse, duration clamp) so the adjuster and generator agree on shape.
    returned = [m for m in (data.get("milestones") or []) if isinstance(m, dict)]
    validated = [
        roadmap_generator._validated_milestone(m, i) for i, m in enumerate(returned)
    ]
    validated = [m for m in validated if m["tasks"]]
    if not validated:
        # Nothing usable came back — treat as a no-op rather than wiping todos.
        logger.info("adjust_roadmap: empty/unusable model output for project %s", project.id)
        return project

    by_title = {m.title.strip().lower(): m for m in project.milestones}
    next_sort = (max((m.sort_order for m in project.milestones), default=-1)) + 1

    for m in validated:
        existing = by_title.get(m["title"].strip().lower())
        if existing is not None:
            # Preserve done/in_progress; replace only the todo tasks. Append the
            # new tasks after the kept ones so ordering stays deterministic.
            kept = [t for t in existing.tasks if _status_str(t.status) != "todo"]
            for stale in [t for t in existing.tasks if _status_str(t.status) == "todo"]:
                await db.delete(stale)
            base_sort = (max((t.sort_order for t in kept), default=-1)) + 1
            _add_todo_tasks(existing.id, m["tasks"], today, base_sort, db)
        else:
            milestone = Milestone(
                project_id=project.id, title=m["title"], description=m["description"], sort_order=next_sort
            )
            next_sort += 1
            db.add(milestone)
            await db.flush()
            _add_todo_tasks(milestone.id, m["tasks"], today, 0, db)

    record_generation_cost("roadmap_adjust", usage, model=_MODEL, session_id=str(project.id))
    await db.commit()
    await db.refresh(project)
    return project


def _add_todo_tasks(milestone_id, tasks: list[dict], today: date, base_sort: int, db: AsyncSession) -> None:
    """Create validated tasks as `todo`, timed, numbered from `base_sort`."""
    for i, t in enumerate(tasks):
        db.add(
            Task(
                milestone_id=milestone_id,
                title=t["title"],
                description=t["description"],
                status="todo",
                sort_order=base_sort + i,
                scheduled_date=roadmap_generator._weekday_after(today, t["day_offset"]),
                scheduled_time=t.get("start_time"),
                duration_minutes=t.get("duration_minutes"),
                parallel=t.get("parallel", False),
            )
        )


# ─── extend a single day (AI top-up when the user clears a day) ──────────────────
_EXTEND_SYSTEM_PROMPT = """You are Omada's project planner. The developer has finished \
everything planned for a specific day and wants a few more concrete, valuable tasks to fill \
the SAME day. Given their current plan and progress, propose 2-4 additional `todo` tasks that \
push the project forward from where they are — real engineering work, not filler. Each task \
needs a detailed technical `description` (3-6 sentences), a `durationMinutes` (15-240), and \
`parallel` (true if it has no dependency on the others). Do NOT restate existing or completed \
tasks."""

_EXTEND_TOOL = {
    "type": "function",
    "function": {
        "name": "extend_day",
        "description": "Return a few additional tasks to fill out the given day.",
        "parameters": {
            "type": "object",
            "properties": {
                "tasks": {
                    "type": "array",
                    "description": "2-4 additional tasks for the same day.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "description": {"type": "string"},
                            "durationMinutes": {"type": "integer"},
                            "parallel": {"type": "boolean"},
                        },
                        "required": ["title"],
                    },
                }
            },
            "required": ["tasks"],
        },
    },
}


def _milestone_for_day(project: Project, target_date: date) -> Milestone:
    """The milestone the new tasks should join: the one that owns the target
    day's work, else the first with unfinished tasks, else the last phase."""
    by_day_count = {}
    for m in project.milestones:
        by_day_count[m.id] = sum(1 for t in m.tasks if t.scheduled_date == target_date)
    owning = max(project.milestones, key=lambda m: by_day_count[m.id], default=None)
    if owning is not None and by_day_count[owning.id] > 0:
        return owning
    for m in sorted(project.milestones, key=lambda x: x.sort_order):
        if any(_status_str(t.status) != "done" for t in m.tasks):
            return m
    return max(project.milestones, key=lambda m: m.sort_order)


async def extend_day(
    project: Project, target_date: date, api_key: str, db: AsyncSession
) -> Project:
    """Ask Groq for a few more `todo` tasks scheduled on `target_date` and
    append them to the milestone that owns that day. Non-destructive: existing
    tasks are untouched, and empty/unusable output is a no-op."""
    project = await db.scalar(
        select(Project)
        .where(Project.id == project.id)
        .options(selectinload(Project.milestones).selectinload(Milestone.tasks))
    )

    context = (
        _plan_context(project)
        + f"\n\nThe developer finished everything scheduled for {target_date.isoformat()} "
        "and wants a few more tasks for that same day."
    )
    data, usage = await _call_tool(api_key, _EXTEND_SYSTEM_PROMPT, context, _EXTEND_TOOL)

    raw_tasks = [t for t in (data.get("tasks") or []) if isinstance(t, dict)]
    validated = [roadmap_generator._validated_task(t) for t in raw_tasks]
    validated = [t for t in validated if t["title"]]
    if not validated:
        logger.info("extend_day: empty/unusable model output for project %s", project.id)
        return project

    target = _milestone_for_day(project, target_date)
    base_sort = (max((t.sort_order for t in target.tasks), default=-1)) + 1
    for i, t in enumerate(validated):
        db.add(
            Task(
                milestone_id=target.id,
                title=t["title"],
                description=t["description"],
                status="todo",
                sort_order=base_sort + i,
                scheduled_date=target_date,
                scheduled_time=t.get("start_time"),
                duration_minutes=t.get("duration_minutes"),
                parallel=t.get("parallel", False),
            )
        )

    record_generation_cost("roadmap_extend_day", usage, model=_MODEL, session_id=str(project.id))
    await db.commit()
    await db.refresh(project)
    return project
