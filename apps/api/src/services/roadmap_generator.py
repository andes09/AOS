"""
Roadmap generator — turns an onboarding project brief into a short-term,
day-by-day plan (project → milestones → tasks) for the calendar view.

One forced-tool Claude call returns an ordered set of milestones, each with
small daily tasks tagged by weekday offset. The tool output is fully validated
before anything is written, so a failed or malformed generation never leaves a
partial roadmap; persistence is a single transaction. Each task is scheduled
onto a concrete weekday starting today.

Key resolution follows the onboarding convention: the org's own (BYOK)
Anthropic key wins, with the platform ANTHROPIC_API_KEY as fallback — roadmap
generation happens right after onboarding, before most orgs have saved a key.

Regeneration comes in two grains: the whole roadmap (Project row kept, its
milestones/tasks replaced) and a single milestone (siblings untouched).
"""

import json
import logging
from datetime import date, timedelta

import anthropic
from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.models.milestone import Milestone
from src.models.onboarding_session import OnboardingSession
from src.models.project import Project
from src.models.task import Task
from src.models.team import Team
from src.services.ai_client import get_anthropic_key
from src.services.cost_tracker import record_generation_cost
from src.services.idea_interview import _PURPOSE_GUIDANCE

logger = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 4096
# Guardrails so a runaway model can't create an enormous plan. The point is a
# short-term, finishable roadmap, not an exhaustive backlog.
_MAX_MILESTONES = 8
_MAX_TASKS_PER_MILESTONE = 8
_MAX_DAY_OFFSET = 30

_SYSTEM_PROMPT = """You are Omada's project planner. Given a founder's project brief, produce a \
SHORT-TERM, day-by-day plan they can actually finish — think the next couple of weeks of \
weekdays, not an exhaustive backlog.

Rules:
- Break the work into a handful of ordered milestones (phases).
- Under each milestone, list small, concrete tasks — each doable in part of a day.
- Give every task a `dayOffset`: a 0-based index of WEEKDAYS from the start (0 = the first \
working day). Spread tasks so each day has only a few; keep the whole plan within ~2 weeks \
of weekdays where possible.
- Order milestones and tasks the way they should actually be tackled.
- Be specific to THIS project. Never invent facts the brief doesn't support; when unsure, \
keep tasks general but actionable."""


def _system_prompt(purpose: str | None) -> str:
    guidance = _PURPOSE_GUIDANCE.get(purpose or "")
    if not guidance:
        return _SYSTEM_PROMPT
    return _SYSTEM_PROMPT + "\n" + guidance


_MILESTONE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "description": {"type": "string"},
        "tasks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "A small, concrete task"},
                    "description": {"type": "string"},
                    "dayOffset": {
                        "type": "integer",
                        "description": "0-based weekday index from the start date",
                    },
                },
                "required": ["title", "dayOffset"],
            },
        },
    },
    "required": ["title", "tasks"],
}

_ROADMAP_TOOL = {
    "name": "build_roadmap",
    "description": "Produce a short-term, day-by-day roadmap for the project.",
    "input_schema": {
        "type": "object",
        "properties": {
            "projectName": {"type": "string", "description": "Short name for the project"},
            "summary": {"type": "string", "description": "One or two sentence summary of the plan"},
            "milestones": {
                "type": "array",
                "description": "Ordered phases of work",
                "items": _MILESTONE_SCHEMA,
            },
        },
        "required": ["milestones"],
    },
}

_MILESTONE_TOOL = {
    "name": "rebuild_milestone",
    "description": "Re-plan a single milestone of the roadmap, leaving the others untouched.",
    "input_schema": _MILESTONE_SCHEMA,
}


async def resolve_api_key(clerk_org_id: str, db: AsyncSession) -> str:
    """The Anthropic key for roadmap generation.

    The org's own (BYOK) key wins; the platform key is the fallback so
    generation works right after onboarding, before the org has saved its own
    key. 402 when neither exists.
    """
    try:
        return await get_anthropic_key(clerk_org_id, db)
    except HTTPException:
        if settings.anthropic_api_key:
            return settings.anthropic_api_key
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="No Anthropic API key available for roadmap generation.",
        )


def _weekday_after(start: date, weekday_offset: int) -> date:
    """Return the date `weekday_offset` weekdays (Mon–Fri) on/after `start`.

    offset 0 is `start` itself if it's a weekday, else the next weekday.
    """
    d = start
    # Advance to the first weekday if start lands on a weekend.
    while d.weekday() >= 5:
        d += timedelta(days=1)
    remaining = max(0, weekday_offset)
    while remaining > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            remaining -= 1
    return d


def _brief_prompt(session: OnboardingSession) -> str:
    return f"Project brief (JSON):\n{json.dumps(session.project_brief or {})}"


def _milestone_prompt(
    milestone: Milestone, siblings: list[Milestone], session: OnboardingSession
) -> str:
    outline = [
        {"title": m.title, "description": m.description, "isTarget": m.id == milestone.id}
        for m in siblings
    ]
    return "\n\n".join(
        [
            _brief_prompt(session),
            f"Current roadmap outline (JSON):\n{json.dumps(outline)}",
            "Re-plan ONLY the milestone marked isTarget — its title, description, and "
            "tasks. The other milestones are fixed context; do not change or repeat "
            f'their work. Call rebuild_milestone with the new plan for "{milestone.title}".',
        ]
    )


async def _call_planner(api_key: str, system: str, user_content: str, tool: dict):
    """One forced-tool Claude call. Returns (tool_input dict, usage)."""
    client = anthropic.AsyncAnthropic(api_key=api_key)
    try:
        response = await client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": user_content}],
            tools=[tool],
            tool_choice={"type": "tool", "name": tool["name"]},
        )
    except anthropic.AuthenticationError as exc:
        raise ValueError("Invalid Anthropic API key.") from exc
    except anthropic.RateLimitError as exc:
        raise RuntimeError(
            "Anthropic API rate limit reached. Please try again in a moment."
        ) from exc
    except anthropic.APIError as exc:
        raise RuntimeError(f"Anthropic API error: {exc.message}") from exc

    block = next(
        (b for b in response.content if b.type == "tool_use" and b.name == tool["name"]),
        None,
    )
    if block is None:
        raise RuntimeError("The planner did not return a roadmap. Please try again.")
    return block.input, response.usage


# ─── tool-output validation (always runs before any DB write) ──────────────────
def _validated_task(raw: dict) -> dict:
    try:
        offset = int(raw.get("dayOffset", 0))
    except (TypeError, ValueError):
        offset = 0
    return {
        "title": str(raw.get("title") or "Untitled task")[:255],
        "description": raw.get("description"),
        "day_offset": min(max(offset, 0), _MAX_DAY_OFFSET),
    }


def _validated_milestone(raw: dict, index: int) -> dict:
    tasks = [t for t in (raw.get("tasks") or [])[:_MAX_TASKS_PER_MILESTONE] if isinstance(t, dict)]
    return {
        "title": str(raw.get("title") or f"Phase {index + 1}")[:255],
        "description": raw.get("description"),
        "tasks": [_validated_task(t) for t in tasks],
    }


def _validated_milestones(data: dict) -> list[dict]:
    raw = [m for m in (data.get("milestones") or [])[:_MAX_MILESTONES] if isinstance(m, dict)]
    milestones = [_validated_milestone(m, i) for i, m in enumerate(raw)]
    if not milestones:
        raise RuntimeError("The planner returned an empty roadmap. Please try again.")
    return milestones


# ─── persistence ───────────────────────────────────────────────────────────────
def _add_tasks(milestone_id, tasks: list[dict], start: date, db: AsyncSession) -> None:
    for t_idx, t in enumerate(tasks):
        db.add(
            Task(
                milestone_id=milestone_id,
                title=t["title"],
                description=t["description"],
                sort_order=t_idx,
                scheduled_date=_weekday_after(start, t["day_offset"]),
            )
        )


async def _persist_milestones(
    project: Project, milestones: list[dict], db: AsyncSession
) -> None:
    start = date.today()
    for m_idx, m in enumerate(milestones):
        milestone = Milestone(
            project_id=project.id,
            title=m["title"],
            description=m["description"],
            sort_order=m_idx,
        )
        db.add(milestone)
        await db.flush()  # assign milestone.id
        _add_tasks(milestone.id, m["tasks"], start, db)


# ─── public API ────────────────────────────────────────────────────────────────
async def generate_roadmap(
    session: OnboardingSession, team: Team, api_key: str, db: AsyncSession
) -> Project:
    """Generate and persist a roadmap for `session` under `team`. Returns the
    new Project with milestones+tasks flushed. Assumes no project exists yet for
    the session (the router enforces that)."""
    data, usage = await _call_planner(
        api_key,
        _system_prompt(session.project_purpose),
        _brief_prompt(session),
        _ROADMAP_TOOL,
    )
    milestones = _validated_milestones(data)

    project = Project(
        team_id=team.id,
        onboarding_session_id=session.id,
        name=(
            data.get("projectName")
            or (session.project_brief or {}).get("projectName")
            or team.name
            or "My project"
        )[:255],
        summary=data.get("summary"),
        purpose=session.project_purpose,
    )
    db.add(project)
    await db.flush()  # assign project.id
    await _persist_milestones(project, milestones, db)

    record_generation_cost(
        "roadmap_generate", usage, model=_MODEL, session_id=str(session.id)
    )
    await db.commit()
    await db.refresh(project)
    return project


async def regenerate_roadmap(
    session: OnboardingSession, team: Team, api_key: str, db: AsyncSession
) -> Project:
    """Regenerate the whole roadmap. The Project row (and its id) is kept; its
    milestones and tasks are replaced wholesale, so task statuses reset.
    Generation and validation happen before anything is deleted — a failed call
    leaves the existing roadmap untouched. Falls back to `generate_roadmap`
    when no project exists yet."""
    project = await db.scalar(
        select(Project).where(Project.onboarding_session_id == session.id)
    )
    if project is None:
        return await generate_roadmap(session, team, api_key, db)

    data, usage = await _call_planner(
        api_key,
        _system_prompt(session.project_purpose),
        _brief_prompt(session),
        _ROADMAP_TOOL,
    )
    milestones = _validated_milestones(data)

    milestone_ids = select(Milestone.id).where(Milestone.project_id == project.id)
    await db.execute(delete(Task).where(Task.milestone_id.in_(milestone_ids)))
    await db.execute(delete(Milestone).where(Milestone.project_id == project.id))

    if data.get("projectName"):
        project.name = str(data["projectName"])[:255]
    if data.get("summary"):
        project.summary = data["summary"]
    await _persist_milestones(project, milestones, db)

    record_generation_cost(
        "roadmap_regenerate", usage, model=_MODEL, session_id=str(session.id)
    )
    await db.commit()
    await db.refresh(project)
    return project


async def regenerate_milestone(
    milestone: Milestone, session: OnboardingSession, api_key: str, db: AsyncSession
) -> Milestone:
    """Re-plan a single milestone; every other milestone is untouched. The
    target's tasks are replaced wholesale (statuses reset) and its title/
    description updated; its position (`sort_order`) is kept. Validation
    happens before any delete, so a failed call changes nothing."""
    siblings = (
        (
            await db.execute(
                select(Milestone)
                .where(Milestone.project_id == milestone.project_id)
                .order_by(Milestone.sort_order)
            )
        )
        .scalars()
        .all()
    )

    data, usage = await _call_planner(
        api_key,
        _system_prompt(session.project_purpose),
        _milestone_prompt(milestone, siblings, session),
        _MILESTONE_TOOL,
    )
    new = _validated_milestone(data, milestone.sort_order)
    if not new["tasks"]:
        raise RuntimeError("The planner returned an empty milestone. Please try again.")

    await db.execute(delete(Task).where(Task.milestone_id == milestone.id))
    milestone.title = new["title"]
    milestone.description = new["description"]
    _add_tasks(milestone.id, new["tasks"], date.today(), db)

    record_generation_cost(
        "roadmap_regenerate_milestone",
        usage,
        model=_MODEL,
        session_id=str(session.id),
        milestone_id=str(milestone.id),
    )
    await db.commit()
    await db.refresh(milestone)
    return milestone
