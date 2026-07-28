"""
Shared roadmap-shape module — the validate-before-persist contract for an
LLM-drafted roadmap (milestones + tasks), plus the "create a Project row and
persist its milestones under it" helper.

Extracted from roadmap_generator.py once artifact_import.py became a second
call site needing the exact same contract (a proposed roadmap must be
validated the same way regardless of whether it came from the idea-interview
brief or an imported document) — duplicating it would violate "minimal
impact" (see docs/plans/2026-07-20-import-artifacts.md). This is a plain
move, not a rewrite: `MAX_MILESTONES`/`MAX_TASKS_PER_MILESTONE`/
`MAX_DAY_OFFSET` and `validated_task`/`validated_milestone`/
`validated_milestones` lost their leading underscores because they're public
now; `roadmap_generator.py` re-imports them under their old private names so
every existing call site and test keeps working unchanged.

Deliberately NOT moved here: the Groq (OpenAI-compatible) `_call_planner`
caller and its `AsyncOpenAI` instantiation stay in roadmap_generator.py.
Existing tests patch `src.services.roadmap_generator.AsyncOpenAI`; moving the
client construction would silently break that patch target. artifact_import.py
instead imports `roadmap_generator._call_planner` directly — cross-module
reuse of a "private" helper already has precedent in this codebase (see
`routers/project_common.py`'s `_get_org`/`_owned_project`, imported by both
`routers/roadmap.py` and `routers/projects.py`).
"""

import re
from datetime import date, time, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.milestone import Milestone
from src.models.onboarding_session import OnboardingSession
from src.models.project import Project
from src.models.task import Task
from src.models.team import Team

# Guardrails so a runaway model can't create an enormous plan. The point is a
# short-term, finishable roadmap, not an exhaustive backlog.
MAX_MILESTONES = 8
MAX_TASKS_PER_MILESTONE = 10
MAX_DAY_OFFSET = 30

MILESTONE_SCHEMA = {
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
                    "startTime": {
                        "type": "string",
                        "description": "24h start time, HH:MM (e.g. 09:30), between 09:00 and 18:00",
                    },
                    "durationMinutes": {
                        "type": "integer",
                        "description": "How long the task should take, 15-240 minutes",
                    },
                    "parallel": {
                        "type": "boolean",
                        "description": "True if this task has no dependency on the task before it and can be worked on alongside its siblings; false if it must wait for earlier tasks.",
                    },
                },
                "required": ["title", "dayOffset"],
            },
        },
    },
    "required": ["title", "tasks"],
}


def _weekday_after(start: date, weekday_offset: int) -> date:
    """Return the date `weekday_offset` weekdays (Mon-Fri) on/after `start`.

    offset 0 is `start` itself if it's a weekday, else the next weekday.
    """
    d = start
    while d.weekday() >= 5:
        d += timedelta(days=1)
    remaining = max(0, weekday_offset)
    while remaining > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            remaining -= 1
    return d


_MIN_DURATION = 15
_MAX_DURATION = 240


def _parse_hhmm(raw) -> time | None:
    """Parse a model-supplied 'HH:MM' into a naive time, or None if unusable."""
    if not isinstance(raw, str):
        return None
    m = re.match(r"^\s*(\d{1,2}):(\d{2})", raw)
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if 0 <= h <= 23 and 0 <= mi <= 59:
        return time(hour=h, minute=mi)
    return None


def _clamp_duration(raw) -> int | None:
    try:
        d = int(raw)
    except (TypeError, ValueError):
        return None
    return min(max(d, _MIN_DURATION), _MAX_DURATION)


# ─── tool-output validation (always runs before any DB write) ──────────────────
def validated_task(raw: dict) -> dict:
    try:
        offset = int(raw.get("dayOffset", 0))
    except (TypeError, ValueError):
        offset = 0
    return {
        "title": str(raw.get("title") or "Untitled task")[:255],
        "description": raw.get("description"),
        "day_offset": min(max(offset, 0), MAX_DAY_OFFSET),
        "start_time": _parse_hhmm(raw.get("startTime")),
        "duration_minutes": _clamp_duration(raw.get("durationMinutes")),
        "parallel": bool(raw.get("parallel", False)),
    }


def validated_milestone(raw: dict, index: int) -> dict:
    tasks = [t for t in (raw.get("tasks") or [])[:MAX_TASKS_PER_MILESTONE] if isinstance(t, dict)]
    return {
        "title": str(raw.get("title") or f"Phase {index + 1}")[:255],
        "description": raw.get("description"),
        "tasks": [validated_task(t) for t in tasks],
    }


def validated_milestones(data: dict) -> list[dict]:
    raw = [m for m in (data.get("milestones") or [])[:MAX_MILESTONES] if isinstance(m, dict)]
    milestones = [validated_milestone(m, i) for i, m in enumerate(raw)]
    if not milestones:
        raise RuntimeError("The planner returned an empty roadmap. Please try again.")
    return milestones


# ─── JSON-safe (de)serialization, for storing a proposed roadmap in a JSON column ──
def milestones_to_json(milestones: list[dict]) -> list[dict]:
    """Camel-cased, JSON-safe view of validated milestones.

    Validated milestones carry a real `datetime.time` for `start_time`, which
    the stdlib JSON encoder can't serialize — this is what
    `OnboardingSession.proposed_roadmap` (a JSON/JSONB column) actually
    stores, and it's also the shape returned to the frontend (matching the
    camelCase the rest of this API uses).
    """
    out = []
    for m in milestones:
        tasks = []
        for t in m.get("tasks") or []:
            start_time = t.get("start_time")
            tasks.append({
                "title": t["title"],
                "description": t.get("description"),
                "dayOffset": t.get("day_offset", 0),
                "startTime": start_time.strftime("%H:%M") if start_time else None,
                "durationMinutes": t.get("duration_minutes"),
                "parallel": bool(t.get("parallel", False)),
            })
        out.append({"title": m["title"], "description": m.get("description"), "tasks": tasks})
    return out


def milestones_from_json(milestones: list[dict]) -> list[dict]:
    """Reverse of `milestones_to_json` — back to the internal validated shape
    `_persist_milestones` expects (snake_case, `start_time` as a real `time`).
    """
    out = []
    for m in milestones or []:
        tasks = []
        for t in m.get("tasks") or []:
            start_time = t.get("startTime")
            tasks.append({
                "title": t.get("title") or "Untitled task",
                "description": t.get("description"),
                "day_offset": t.get("dayOffset", 0),
                "start_time": _parse_hhmm(start_time) if isinstance(start_time, str) else None,
                "duration_minutes": t.get("durationMinutes"),
                "parallel": bool(t.get("parallel", False)),
            })
        out.append({
            "title": m.get("title") or "Untitled milestone",
            "description": m.get("description"),
            "tasks": tasks,
        })
    return out


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
                scheduled_time=t.get("start_time"),
                duration_minutes=t.get("duration_minutes"),
                parallel=t.get("parallel", False),
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


async def create_project_with_milestones(
    session: OnboardingSession,
    team: Team,
    name: str,
    summary: str | None,
    purpose: str | None,
    milestones: list[dict],
    db: AsyncSession,
) -> Project:
    """Create a Project row (linked to `session` via its 1:1 FK) under `team`
    and persist `milestones` (already validated) under it.

    Shared by `roadmap_generator.generate_roadmap` (chat path) and
    `artifact_import`'s `/import/apply` (import path) — both need exactly
    "make a Project + persist these milestones", just from different sources.
    Caller is responsible for committing.
    """
    project = Project(
        team_id=team.id,
        onboarding_session_id=session.id,
        name=(name or "My project")[:255],
        summary=summary,
        purpose=purpose,
    )
    db.add(project)
    await db.flush()  # assign project.id
    await _persist_milestones(project, milestones, db)
    return project
