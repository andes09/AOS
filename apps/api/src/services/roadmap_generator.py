"""
Roadmap generator — turns an onboarding project brief into a short-term,
day-by-day plan (project → milestones → tasks) for the calendar view.

One forced-tool Groq call (OpenAI-compatible) returns an ordered set of
milestones, each with small daily tasks tagged by weekday offset. The tool
output is fully validated before anything is written, so a failed or
malformed generation never leaves a partial roadmap; persistence is a single
transaction. Each task is scheduled onto a concrete weekday starting today.

Key resolution is platform-only Groq (see idea_interview.resolve_api_key) —
roadmap generation happens right after onboarding, before most orgs have
saved any BYOK key.

Regeneration comes in two grains: the whole roadmap (Project row kept, its
milestones/tasks replaced) and a single milestone (siblings untouched).
"""

import json
import logging
from datetime import date

from openai import APIError, AsyncOpenAI, AuthenticationError, BadRequestError, RateLimitError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.models.milestone import Milestone
from src.models.onboarding_session import OnboardingSession
from src.models.organization import Organization
from src.models.project import Project
from src.models.task import Task
from src.models.team import Team
from src.services.cost_tracker import record_generation_cost
from src.services.idea_interview import _PURPOSE_GUIDANCE
from src.services.roadmap_shapes import (
    MAX_DAY_OFFSET as _MAX_DAY_OFFSET,
    MAX_MILESTONES as _MAX_MILESTONES,
    MAX_TASKS_PER_MILESTONE as _MAX_TASKS_PER_MILESTONE,
    MILESTONE_SCHEMA as _MILESTONE_SCHEMA,
    _add_tasks,
    _persist_milestones,
    _weekday_after,
    create_project_with_milestones,
    validated_milestone as _validated_milestone,
    validated_milestones as _validated_milestones,
    validated_task as _validated_task,
)
from src.services.task_ids import allocate_short_ids

logger = logging.getLogger(__name__)

_MODEL = settings.groq_model
# 8192, not 4096: a full plan is up to 8 milestones × 10 tasks, each carrying a
# 3-6 sentence technical description. At 4096 the tool call gets truncated and
# the roadmap comes back short.
_MAX_TOKENS = 8192

_SYSTEM_PROMPT = """You are Omada's technical project planner. Given a founder's project brief, \
produce a SHORT-TERM, day-by-day plan a developer can actually execute — think the next couple \
of weeks of weekdays, not an exhaustive backlog.

Make it genuinely DETAILED and TECHNICAL:
- Break the work into a handful of ordered milestones (phases).
- Under each milestone, list concrete engineering tasks — each doable in part of a day.
- For EVERY task, write a detailed, technical `description` (3-6 sentences). Name the specific \
approach, technologies/libraries/frameworks, the files or modules to create, data models or \
schema, API endpoints, and key commands — and end with a crisp acceptance criterion for "done". \
Write for a technical reader; be concrete, never generic filler.
- Give every task a `dayOffset`: a 0-based index of WEEKDAYS from the start (0 = the first \
working day). Spread tasks so each day has only a few; keep the whole plan within ~2 weeks \
of weekdays where possible.
- Lay out each day as a realistic schedule: give every task a `startTime` (24h "HH:MM", \
between 09:00 and 18:00) and a `durationMinutes` (15–240). Order tasks within a day by time \
and don't overlap them — a developer should be able to follow the day top to bottom.
- Order milestones and tasks the way they should actually be tackled (dependencies first).
- Set `parallel: true` on tasks that don't depend on the task before them and could be \
picked up alongside their siblings; leave it false for work that must wait on earlier tasks.
- Ground everything in THIS project and its stated stack/constraints. Never invent facts the \
brief doesn't support; where the brief is silent, make a sensible, clearly-reasonable technical \
choice and state it."""


def _system_prompt(purpose: str | None) -> str:
    guidance = _PURPOSE_GUIDANCE.get(purpose or "")
    if not guidance:
        return _SYSTEM_PROMPT
    return _SYSTEM_PROMPT + "\n" + guidance


_ROADMAP_TOOL = {
    "type": "function",
    "function": {
        "name": "build_roadmap",
        "description": "Produce a short-term, day-by-day roadmap for the project.",
        "parameters": {
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
    },
}

_MILESTONE_TOOL = {
    "type": "function",
    "function": {
        "name": "rebuild_milestone",
        "description": "Re-plan a single milestone of the roadmap, leaving the others untouched.",
        "parameters": _MILESTONE_SCHEMA,
    },
}


def _tech_stack_prompt(session: OnboardingSession) -> str | None:
    """Renders the founder's explicit tech-stack answer (see PUT /tech-stack
    in onboarding_v2.py) as prompt guidance. Returns None when unset — either
    the tech_stack_step flag was off for this session, or it predates the
    feature — so older sessions keep generating exactly as before.

    Distinct from ProjectBrief.tech_constraints (chat-extracted, free text
    about hard requirements/integrations): this is about tool familiarity.
    """
    experience = session.tech_experience
    if experience == "experienced":
        stack = ", ".join(session.known_tech_stack or [])
        return (
            f"The founder already knows: {stack}. Prefer these tools; only introduce "
            "something new if there's a clear, well-justified gap in what they listed, "
            "and say why in the task description."
        )
    if experience == "new":
        return (
            "The founder is new to building software — this may be their first project. "
            "Recommend a simple, well-documented, beginner-friendly stack, and make the "
            "early setup/installation/account-creation steps explicit tasks in the first "
            "milestone, not assumed prior knowledge."
        )
    return None


def _brief_prompt(session: OnboardingSession) -> str:
    parts = [f"Project brief (JSON):\n{json.dumps(session.project_brief or {})}"]
    tech_stack_guidance = _tech_stack_prompt(session)
    if tech_stack_guidance:
        parts.append(tech_stack_guidance)
    return "\n\n".join(parts)


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


# A full multi-milestone roadmap is a large, deeply-nested tool call, and Groq's
# tool-calling occasionally emits it in a form its own parser rejects
# (400 tool_use_failed) even though the underlying JSON was well-formed —
# Groq's own guidance is to retry. A single milestone rarely hits this.
_MAX_TOOL_RETRIES = 2


async def _call_planner(api_key: str, system: str, user_content: str, tool: dict):
    """One forced-tool Groq call, retried on tool_use_failed. Returns (tool_input dict, usage)."""
    tool_name = tool["function"]["name"]
    client = AsyncOpenAI(api_key=api_key, base_url=settings.groq_base_url)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_content},
    ]

    response = None
    for attempt in range(_MAX_TOOL_RETRIES + 1):
        try:
            response = await client.chat.completions.create(
                model=_MODEL,
                max_tokens=_MAX_TOKENS,
                messages=messages,
                tools=[tool],
                tool_choice={"type": "function", "function": {"name": tool_name}},
            )
            break
        except AuthenticationError as exc:
            raise ValueError("Invalid Groq API key.") from exc
        except RateLimitError as exc:
            raise RuntimeError(
                "Groq API rate limit reached. Please try again in a moment."
            ) from exc
        except BadRequestError as exc:
            if getattr(exc, "code", None) == "tool_use_failed" and attempt < _MAX_TOOL_RETRIES:
                continue
            raise RuntimeError(f"Groq API error: {exc}") from exc
        except APIError as exc:
            raise RuntimeError(f"Groq API error: {exc}") from exc

    tool_calls = response.choices[0].message.tool_calls or []
    call = next((t for t in tool_calls if t.function.name == tool_name), None)
    if call is None:
        raise RuntimeError("The planner did not return a roadmap. Please try again.")
    try:
        return json.loads(call.function.arguments), response.usage
    except json.JSONDecodeError as exc:
        raise RuntimeError("The planner returned malformed output. Please try again.") from exc


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

    name = (
        data.get("projectName")
        or (session.project_brief or {}).get("projectName")
        or team.name
        or "My project"
    )
    project = await create_project_with_milestones(
        session, team, name, data.get("summary"), session.project_purpose, milestones, db,
    )
    # A repo may already have been picked during onboarding's repo-select step
    # before this project existed (PUT /repo just stashes it on the session in
    # that case) — copy it onto the freshly created Project now.
    if session.selected_github_repo_full_name:
        project.github_repo_full_name = session.selected_github_repo_full_name

    await record_generation_cost(
        "roadmap_generate",
        usage,
        provider="anthropic",
        org_id=team.organization_id,
        team_id=team.id,
        model=_MODEL,
        session_id=str(session.id),
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
    org = await db.get(Organization, team.organization_id)
    await _persist_milestones(project, milestones, org, db)

    await record_generation_cost(
        "roadmap_regenerate",
        usage,
        provider="anthropic",
        org_id=team.organization_id,
        team_id=team.id,
        model=_MODEL,
        session_id=str(session.id),
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
    org_row = (
        await db.execute(
            select(Organization, Team.id)
            .join(Team, Team.organization_id == Organization.id)
            .join(Project, Project.team_id == Team.id)
            .where(Project.id == milestone.project_id)
        )
    ).first()
    org, milestone_team_id = org_row
    short_ids = await allocate_short_ids(org, len(new["tasks"]), db)
    _add_tasks(milestone.id, new["tasks"], date.today(), short_ids, db)

    await record_generation_cost(
        "roadmap_regenerate_milestone",
        usage,
        provider="anthropic",
        org_id=org.id,
        team_id=milestone_team_id,
        model=_MODEL,
        session_id=str(session.id),
        milestone_id=str(milestone.id),
    )
    await db.commit()
    await db.refresh(milestone)
    return milestone
