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
from src.models.organization import Organization
from src.models.project import Project
from src.models.task import Task
from src.models.team import Team
from src.services import roadmap_generator
from src.services.cost_tracker import record_generation_cost
from src.services.llm_errors import RATE_LIMIT_MESSAGE, LLMRateLimitError
from src.services.roadmap_shapes import record_plan_quality, resolve_task_dependencies
from src.services.task_ids import allocate_short_ids

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
- Give every task a `key` (short, unique in this response). When a task genuinely depends on \
other specific work finishing first, list those tasks' `key`s in `dependsOn` — you may also \
reference an existing task's `id` (given in the current plan below) if new work depends on \
already-done or in-progress history. Independent tasks should have no `dependsOn` between \
them, so they can be worked in parallel.
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
                                        "key": {
                                            "type": "string",
                                            "description": "Short, unique-within-this-response id for this task.",
                                        },
                                        "dependsOn": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                            "description": "Keys of other new tasks in this response, or "
                                            "`id`s of existing tasks from the current plan, that must "
                                            "complete before this one can start.",
                                        },
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
                        "id": str(t.id),
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
        raise LLMRateLimitError(RATE_LIMIT_MESSAGE) from exc
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


async def _org_for_project(project: Project, db: AsyncSession) -> Organization:
    """Task.short_id needs the owning org (for its slug prefix + next_task_seq
    counter) — Project only carries team_id, so hop through Team."""
    return await db.scalar(
        select(Organization).join(Team, Team.organization_id == Organization.id).where(Team.id == project.team_id)
    )


async def _call_adjuster(api_key: str, context: str, extra_context: str | None = None):
    """One forced-tool Groq call for the feedback re-plan.

    `extra_context` is appended as an additional evidence block — used by the
    drift reconcile path (services/roadmap_drift.build_reconcile_context) to
    hand the planner what the repo actually shows, alongside what the user
    typed. It is passed here rather than merged into `Task.feedback` so the
    user's own words are never overwritten by a derived signal.
    """
    user_content = "Current plan and feedback:\n" + context
    if extra_context:
        user_content += "\n\n" + extra_context
    return await _call_tool(api_key, _SYSTEM_PROMPT, user_content, _ADJUST_TOOL)


async def adjust_roadmap(
    project: Project,
    api_key: str,
    db: AsyncSession,
    today: date | None = None,
    extra_context: str | None = None,
) -> Project:
    """
    Re-plan the project's `todo` tasks from feedback, preserving completed work.

    Generation + validation happen before any delete, so a failed or empty
    adjustment leaves the roadmap untouched.

    `extra_context` adds a second evidence source to the same call — see
    `_call_adjuster`. Everything else about the contract is unchanged, which is
    why the drift reconcile endpoint reuses this rather than adding a parallel
    generation path that would have to re-derive "done is fixed history".
    """
    today = today or date.today()

    # Eager-load so _plan_context and the merge below don't lazy-load mid-async.
    project = await db.scalar(
        select(Project)
        .where(Project.id == project.id)
        .options(selectinload(Project.milestones).selectinload(Milestone.tasks))
    )

    data, usage = await _call_adjuster(api_key, _plan_context(project), extra_context)

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

    # Already-persisted, non-todo tasks a new todo task may declare a
    # dependency on (via its real id) — fixed history, never deleted below.
    existing_tasks_by_id = {
        str(t.id): t
        for m in project.milestones
        for t in m.tasks
        if _status_str(t.status) != "todo"
    }

    # One atomic batch reservation for every task this adjustment will create.
    org = await _org_for_project(project, db)
    total_tasks = sum(len(m["tasks"]) for m in validated)
    short_ids = iter(await allocate_short_ids(org, total_tasks, db))

    tasks_by_key: dict[str, Task] = {}
    edges_by_key: dict[str, list[str]] = {}
    for m in validated:
        existing = by_title.get(m["title"].strip().lower())
        if existing is not None:
            # Preserve done/in_progress; replace only the todo tasks. Append the
            # new tasks after the kept ones so ordering stays deterministic.
            kept = [t for t in existing.tasks if _status_str(t.status) != "todo"]
            for stale in [t for t in existing.tasks if _status_str(t.status) == "todo"]:
                await db.delete(stale)
            base_sort = (max((t.sort_order for t in kept), default=-1)) + 1
            task_short_ids = [next(short_ids) for _ in m["tasks"]]
            tasks_by_key.update(_add_todo_tasks(existing.id, m["tasks"], today, base_sort, task_short_ids, db))
        else:
            milestone = Milestone(
                project_id=project.id, title=m["title"], description=m["description"], sort_order=next_sort
            )
            next_sort += 1
            db.add(milestone)
            await db.flush()
            task_short_ids = [next(short_ids) for _ in m["tasks"]]
            tasks_by_key.update(_add_todo_tasks(milestone.id, m["tasks"], today, 0, task_short_ids, db))
        for t in m["tasks"]:
            edges_by_key[t.get("key")] = t.get("depends_on") or []

    resolution = resolve_task_dependencies(
        tasks_by_key, edges_by_key, existing_tasks_by_id=existing_tasks_by_id, strict=False
    )
    # Covers only the todo tasks this adjustment rebuilt — done/in_progress
    # history is never re-resolved, so these counts describe the re-plan, not
    # the project's whole graph.
    record_plan_quality(project, resolution, "adjust")

    await record_generation_cost(
        "roadmap_adjust",
        usage,
        provider="groq",
        org_id=org.id,
        team_id=project.team_id,
        model=_MODEL,
        session_id=str(project.id),
    )
    await db.commit()
    await db.refresh(project)
    return project


def _add_todo_tasks(
    milestone_id, tasks: list[dict], today: date, base_sort: int, short_ids: list[str], db: AsyncSession
) -> dict[str, Task]:
    """Create validated tasks as `todo`, timed, numbered from `base_sort`.
    Returns {key: Task} for `resolve_task_dependencies`."""
    tasks_by_key: dict[str, Task] = {}
    for i, t in enumerate(tasks):
        task = Task(
            milestone_id=milestone_id,
            short_id=short_ids[i],
            title=t["title"],
            description=t["description"],
            status="todo",
            sort_order=base_sort + i,
            scheduled_date=roadmap_generator._weekday_after(today, t["day_offset"]),
            scheduled_time=t.get("start_time"),
            duration_minutes=t.get("duration_minutes"),
        )
        # See roadmap_shapes._add_tasks's comment: force depends_on "loaded"
        # before this task can ever become persistent (adjust_roadmap flushes
        # per-milestone), so the later resolve_task_dependencies().append()
        # never triggers an async-incompatible lazy load.
        task.depends_on = []
        db.add(task)
        tasks_by_key[t.get("key") or f"t{i}"] = task
    return tasks_by_key
