"""
Roadmap generator — turns an onboarding project brief into a short-term,
day-by-day plan (projects → milestones → tasks) for the calendar view.

Runs on Groq's free, OpenAI-compatible API (same client/pattern as
services/idea_interview.py). One forced-tool call returns an ordered set of
milestones, each with small daily tasks tagged by weekday offset; we persist
them and schedule each task onto a concrete weekday starting today.
"""

import json
import logging
from datetime import date, timedelta

from openai import APIError, AsyncOpenAI, AuthenticationError, RateLimitError
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.models.milestone import Milestone
from src.models.onboarding_session import OnboardingSession
from src.models.project import Project
from src.models.task import Task
from src.models.team import Team

logger = logging.getLogger(__name__)

_MAX_TOKENS = 8192
# Guardrails so a runaway model can't create an enormous plan. The point is a
# short-term, finishable roadmap, not an exhaustive backlog.
_MAX_MILESTONES = 8
_MAX_TASKS_PER_MILESTONE = 10
_MAX_DAY_OFFSET = 30

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
- Order milestones and tasks the way they should actually be tackled (dependencies first).
- Ground everything in THIS project and its stated stack/constraints. Never invent facts the \
brief doesn't support; where the brief is silent, make a sensible, clearly-reasonable technical \
choice and state it."""

_PURPOSE_FRAMING = {
    "hobby": "This is a hobby project — keep scope small and motivating; favor the smallest satisfying version.",
    "startup": "This is a startup — bias toward a lean MVP that can ship and be tested with real users.",
    "learning": "This is a learning project — frame tasks around building the target skill, not feature completeness.",
}

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
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "description": {"type": "string"},
                            "tasks": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "title": {"type": "string", "description": "A small, concrete task (imperative, e.g. 'Set up Postgres schema')"},
                                        "description": {
                                            "type": "string",
                                            "description": (
                                                "Detailed, technical description (3-6 sentences): approach, "
                                                "technologies/libraries, files/modules to create, data models, "
                                                "API endpoints, key commands, and an acceptance criterion."
                                            ),
                                        },
                                        "dayOffset": {
                                            "type": "integer",
                                            "description": "0-based weekday index from the start date",
                                        },
                                    },
                                    "required": ["title", "description", "dayOffset"],
                                },
                            },
                        },
                        "required": ["title", "tasks"],
                    },
                },
            },
            "required": ["milestones"],
        },
    },
}


def resolve_groq_key() -> str | None:
    """The platform Groq key, or None if unset (router turns None into a 402)."""
    return settings.groq_api_key or None


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
    brief = json.dumps(session.project_brief or {})
    framing = _PURPOSE_FRAMING.get(session.project_purpose or "", "")
    parts = [f"Project brief (JSON):\n{brief}"]
    if framing:
        parts.append(framing)
    return "\n\n".join(parts)


async def generate_roadmap(
    session: OnboardingSession, team: Team, api_key: str, db: AsyncSession
) -> Project:
    """Generate and persist a roadmap for `session` under `team`. Returns the
    new Project with milestones+tasks flushed. Assumes no project exists yet for
    the session (the router enforces that)."""
    client = AsyncOpenAI(api_key=api_key, base_url=settings.groq_base_url)

    try:
        completion = await client.chat.completions.create(
            model=settings.groq_model,
            max_tokens=_MAX_TOKENS,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": _brief_prompt(session)},
            ],
            tools=[_ROADMAP_TOOL],
            tool_choice={"type": "function", "function": {"name": "build_roadmap"}},
        )
    except AuthenticationError as exc:
        raise ValueError("Invalid Groq API key.") from exc
    except RateLimitError as exc:
        raise RuntimeError("Groq API rate limit reached. Please try again in a moment.") from exc
    except APIError as exc:
        raise RuntimeError(f"Groq API error: {exc}") from exc

    tool_calls = completion.choices[0].message.tool_calls or []
    call = next((t for t in tool_calls if t.function.name == "build_roadmap"), None)
    if call is None:
        raise RuntimeError("The planner did not return a roadmap. Please try again.")
    try:
        data = json.loads(call.function.arguments)
    except json.JSONDecodeError as exc:
        raise RuntimeError("The planner returned an unreadable roadmap. Please try again.") from exc

    milestones_in = (data.get("milestones") or [])[:_MAX_MILESTONES]
    if not milestones_in:
        raise RuntimeError("The planner returned an empty roadmap. Please try again.")

    project = Project(
        team_id=team.id,
        onboarding_session_id=session.id,
        name=(data.get("projectName") or (session.project_brief or {}).get("projectName") or team.name or "My project")[:255],
        summary=data.get("summary"),
        purpose=session.project_purpose,
    )
    db.add(project)
    await db.flush()  # assign project.id

    start = date.today()
    for m_idx, m in enumerate(milestones_in):
        milestone = Milestone(
            project_id=project.id,
            title=str(m.get("title") or f"Phase {m_idx + 1}")[:255],
            description=m.get("description"),
            sort_order=m_idx,
        )
        db.add(milestone)
        await db.flush()  # assign milestone.id

        for t_idx, t in enumerate((m.get("tasks") or [])[:_MAX_TASKS_PER_MILESTONE]):
            try:
                offset = int(t.get("dayOffset", 0))
            except (TypeError, ValueError):
                offset = 0
            offset = min(max(offset, 0), _MAX_DAY_OFFSET)
            db.add(
                Task(
                    milestone_id=milestone.id,
                    title=str(t.get("title") or "Untitled task")[:255],
                    description=t.get("description"),
                    status="todo",
                    sort_order=t_idx,
                    scheduled_date=_weekday_after(start, offset),
                )
            )

    await db.commit()
    await db.refresh(project)
    return project
