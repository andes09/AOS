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

import logging
import re
from collections import Counter
from datetime import date, datetime, time, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.milestone import Milestone
from src.models.onboarding_session import OnboardingSession
from src.models.organization import Organization
from src.models.project import Project
from src.models.task import Task
from src.models.team import Team
from src.services.task_ids import allocate_short_ids

logger = logging.getLogger(__name__)

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
                    "key": {
                        "type": "string",
                        "description": "A short, unique-within-this-response identifier for this task "
                        '(e.g. "setup-db"), used only so other tasks can reference it as a prerequisite.',
                    },
                    "dependsOn": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "The `key`s of other tasks in this response that must be "
                        "completed before this one can start. Omit or leave empty for a task with no "
                        "prerequisites — it can be worked on immediately or alongside any other "
                        "unblocked task.",
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
def validated_task(raw: dict, fallback_key: str) -> dict:
    try:
        offset = int(raw.get("dayOffset", 0))
    except (TypeError, ValueError):
        offset = 0
    raw_key = raw.get("key")
    key = str(raw_key)[:64] if isinstance(raw_key, str) and raw_key.strip() else fallback_key
    depends_on = [str(k) for k in (raw.get("dependsOn") or []) if isinstance(k, str)][:20]
    return {
        "title": str(raw.get("title") or "Untitled task")[:255],
        "description": raw.get("description"),
        "day_offset": min(max(offset, 0), MAX_DAY_OFFSET),
        "start_time": _parse_hhmm(raw.get("startTime")),
        "duration_minutes": _clamp_duration(raw.get("durationMinutes")),
        "key": key,
        "depends_on": depends_on,
    }


def validated_milestone(raw: dict, index: int) -> dict:
    tasks = [t for t in (raw.get("tasks") or [])[:MAX_TASKS_PER_MILESTONE] if isinstance(t, dict)]
    return {
        "title": str(raw.get("title") or f"Phase {index + 1}")[:255],
        "description": raw.get("description"),
        "tasks": [
            validated_task(t, fallback_key=f"m{index}-t{t_idx}") for t_idx, t in enumerate(tasks)
        ],
    }


def _dedupe_task_keys(milestones: list[dict]) -> None:
    """Guarantee every task's `key` is unique across the whole response. The
    model can omit or repeat keys; an undetected collision would silently
    merge two different tasks' identities when `dependsOn` edges are resolved."""
    seen: set[str] = set()
    for m_idx, m in enumerate(milestones):
        for t_idx, t in enumerate(m["tasks"]):
            key = t["key"]
            if key in seen:
                key = f"{key}-{m_idx}-{t_idx}"
            seen.add(key)
            t["key"] = key


def validated_milestones(data: dict) -> list[dict]:
    raw = [m for m in (data.get("milestones") or [])[:MAX_MILESTONES] if isinstance(m, dict)]
    milestones = [validated_milestone(m, i) for i, m in enumerate(raw)]
    if not milestones:
        raise RuntimeError("The planner returned an empty roadmap. Please try again.")
    _dedupe_task_keys(milestones)
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
                "key": t.get("key"),
                "dependsOn": t.get("depends_on") or [],
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
                "key": t.get("key"),
                "depends_on": [str(k) for k in (t.get("dependsOn") or []) if isinstance(k, str)],
            })
        out.append({
            "title": m.get("title") or "Untitled milestone",
            "description": m.get("description"),
            "tasks": tasks,
        })
    return out


# ─── dependency-graph resolution ────────────────────────────────────────────────
def topological_levels(graph: dict[str, set[str]]) -> tuple[list[list[str]], set[str]]:
    """`graph[key]` = the set of keys `key` depends on. Returns
    `(levels, cyclic)` via a straightforward Kahn's-algorithm topological peel:
    repeatedly remove every key with no remaining dependencies, one *level* at
    a time. Whatever's left when nothing more can be removed is cyclic.

    A level is the set of keys that become workable at the same time, so the
    peel answers both DAG-shape questions `plan_quality` asks: `len(levels)` is
    the critical-path length (minimum sequential steps to finish the plan) and
    the widest level is the maximum parallel width. Levels are sorted so the
    output is deterministic rather than dict-insertion-ordered.

    Dependencies pointing outside `graph` are ignored — an absent key can never
    be peeled, so leaving it in would misreport the whole downstream chain as
    cyclic. Plan sizes are small (<= MAX_MILESTONES * MAX_TASKS_PER_MILESTONE
    = 80 tasks), so the O(n^2) worst case here is fine.
    """
    remaining = {k: {d for d in deps if d in graph} for k, deps in graph.items()}
    levels: list[list[str]] = []
    while True:
        ready = sorted(k for k, deps in remaining.items() if not deps)
        if not ready:
            break
        levels.append(ready)
        for k in ready:
            del remaining[k]
        for deps in remaining.values():
            deps.difference_update(ready)
    return levels, set(remaining.keys())


def _find_cyclic_keys(graph: dict[str, set[str]]) -> set[str]:
    """Every key in `graph` that participates in a cycle."""
    return topological_levels(graph)[1]


def resolve_task_dependencies(
    tasks_by_key: dict[str, Task],
    edges_by_key: dict[str, list[str]],
    *,
    existing_tasks_by_id: dict[str, Task] | None = None,
    strict: bool,
) -> dict:
    """Resolve each task's `dependsOn` key list into real `Task.depends_on`
    ORM edges, validating references and rejecting cycles.

    Resolution order for each dep string: first `tasks_by_key` (a sibling task
    in this same batch), then `existing_tasks_by_id` (an already-persisted
    task, referenced by its real UUID string — only meaningful for the
    adjuster, which lets new tasks depend on already-`done`/`in_progress`
    history). Cycle detection only runs over edges internal to `tasks_by_key`
    — an already-persisted task can never be part of a newly-introduced
    cycle, since nothing existing can depend on a not-yet-created task.

    `strict=True` (fresh generation): an unknown reference or any cycle raises
    `RuntimeError`, which the router surfaces as a 502 — the same failure
    class as other malformed-model-output cases.
    `strict=False` (adjuster / partial import-apply): unknown references, and
    every edge touching a cyclic task, are silently dropped (and logged);
    everything else still persists. These paths never destructively fail on a
    graph hiccup.

    Returns generation-fidelity stats — how much of the graph the model
    proposed actually survived::

        {"edges_proposed": int, "edges_kept": int, "edges_dropped": int,
         "dropped_by_reason": {"dangling": int, "cyclic": int}}

    `dropped_by_reason` carries only reasons that actually fired (a `Counter`
    view, matching `plan_quality`'s `overrides_by_reason` convention), and
    `edges_proposed == edges_kept + edges_dropped` always holds. Under
    `strict=True` this raises before returning, so a returned dict there is
    necessarily all-kept. `plan_quality.summarize_dependency_resolution` turns
    this into the persisted telemetry block.
    """
    existing_tasks_by_id = existing_tasks_by_id or {}
    dropped: Counter[str] = Counter()
    edges_proposed = 0
    resolved: dict[str, list[Task]] = {}
    for key, task in tasks_by_key.items():
        targets: list[Task] = []
        for dep_key in edges_by_key.get(key, []):
            edges_proposed += 1
            target = tasks_by_key.get(dep_key) or existing_tasks_by_id.get(dep_key)
            if target is None or target is task:
                if strict:
                    raise RuntimeError(
                        "The planner referenced a task that doesn't exist in this batch."
                    )
                dropped["dangling"] += 1
                logger.warning("roadmap: dropping dangling task dependency %r -> %r", key, dep_key)
                continue
            targets.append(target)
        resolved[key] = targets

    key_by_internal_task = {t: k for k, t in tasks_by_key.items()}
    internal_graph = {
        key: {key_by_internal_task[t] for t in targets if t in key_by_internal_task}
        for key, targets in resolved.items()
    }
    cyclic = _find_cyclic_keys(internal_graph)
    if cyclic:
        if strict:
            raise RuntimeError(
                "The planner produced an invalid task dependency graph. Please try again."
            )
        logger.warning("roadmap: dropping cyclic task dependencies for keys %s", sorted(cyclic))

    edges_kept = 0
    for key, task in tasks_by_key.items():
        if key in cyclic:
            # Every edge out of a cyclic task goes, not just the one closing
            # the loop — there's no principled way to pick which edge was the
            # model's mistake.
            dropped["cyclic"] += len(resolved[key])
            continue
        for target in resolved[key]:
            task.depends_on.append(target)
            edges_kept += 1

    return {
        "edges_proposed": edges_proposed,
        "edges_kept": edges_kept,
        "edges_dropped": sum(dropped.values()),
        "dropped_by_reason": dict(dropped),
    }


# ─── persistence ───────────────────────────────────────────────────────────────
def _add_tasks(
    milestone_id, tasks: list[dict], start: date, short_ids: list[str], db: AsyncSession
) -> dict[str, Task]:
    """Create+add each task, returning {key: Task} for `resolve_task_dependencies`."""
    tasks_by_key: dict[str, Task] = {}
    for t_idx, t in enumerate(tasks):
        task = Task(
            milestone_id=milestone_id,
            short_id=short_ids[t_idx],
            title=t["title"],
            description=t["description"],
            sort_order=t_idx,
            scheduled_date=_weekday_after(start, t["day_offset"]),
            scheduled_time=t.get("start_time"),
            duration_minutes=t.get("duration_minutes"),
        )
        # Force `depends_on` "loaded" (empty) immediately, before this task
        # can ever become persistent — `_persist_milestones` flushes once per
        # milestone (to assign the next milestone's FK), which would flip an
        # earlier milestone's already-added tasks from transient to
        # persistent. A persistent object's *first* collection access always
        # queries to check for existing rows, even for a brand-new row that
        # can't have any — and that query has no synchronous fallback under
        # asyncio. Assigning here (not just relying on it being naturally
        # empty) marks it loaded so `resolve_task_dependencies`'s `.append()`
        # later never triggers that query, regardless of flush timing.
        task.depends_on = []
        db.add(task)
        tasks_by_key[t.get("key") or f"m?-t{t_idx}"] = task
    return tasks_by_key


def record_plan_quality(project: Project, resolution: dict, source: str) -> None:
    """Stash a DAG-build's generation-fidelity stats on `projects.plan_quality`.

    Raw counts only — no rates. `plan_quality` derives `dropped_edge_rate` (and
    the DAG-shape metrics) at *read* time, so this stays a plain fact about what
    the build did and needs no import from the telemetry module. That direction
    matters: `plan_quality` imports `topological_levels` from here, so an import
    back the other way would be a cycle.

    `source` names the path that produced the graph ("generate", "regenerate",
    "regenerate_milestone", "adjust", "import"), because they don't all cover
    the same scope — `adjust` and `regenerate_milestone` only rebuild part of
    the plan, so their counts describe that part, not the whole project.

    The caller commits.
    """
    project.plan_quality = {
        "resolution": resolution,
        "source": source,
        "recorded_at": datetime.utcnow().isoformat(),
    }


async def _persist_milestones(
    project: Project,
    milestones: list[dict],
    org: Organization,
    db: AsyncSession,
    *,
    strict: bool = True,
    source: str = "generate",
) -> None:
    start = date.today()
    # One atomic batch reservation for every task in the plan, rather than one
    # round trip per task — see src/services/task_ids.py.
    total_tasks = sum(len(m["tasks"]) for m in milestones)
    short_ids = iter(await allocate_short_ids(org, total_tasks, db))
    tasks_by_key: dict[str, Task] = {}
    edges_by_key: dict[str, list[str]] = {}
    for m_idx, m in enumerate(milestones):
        milestone = Milestone(
            project_id=project.id,
            title=m["title"],
            description=m["description"],
            sort_order=m_idx,
        )
        db.add(milestone)
        await db.flush()  # assign milestone.id
        task_short_ids = [next(short_ids) for _ in m["tasks"]]
        tasks_by_key.update(_add_tasks(milestone.id, m["tasks"], start, task_short_ids, db))
        for t in m["tasks"]:
            edges_by_key[t.get("key")] = t.get("depends_on") or []
    resolution = resolve_task_dependencies(tasks_by_key, edges_by_key, strict=strict)
    record_plan_quality(project, resolution, source)


async def create_project_with_milestones(
    session: OnboardingSession,
    team: Team,
    name: str,
    summary: str | None,
    purpose: str | None,
    milestones: list[dict],
    db: AsyncSession,
    *,
    strict: bool = True,
    source: str = "generate",
) -> Project:
    """Create a Project row (linked to `session` via its 1:1 FK) under `team`
    and persist `milestones` (already validated) under it.

    Shared by `roadmap_generator.generate_roadmap` (chat path) and
    `artifact_import`'s `/import/apply` (import path) — both need exactly
    "make a Project + persist these milestones", just from different sources.
    Caller is responsible for committing.

    `strict` governs dependency-graph resolution (see `resolve_task_dependencies`):
    the import path passes `strict=False` since accepting only a subset of
    proposed milestones legitimately produces dangling `dependsOn` references
    to milestones the user rejected. `source` labels the recorded plan-quality
    telemetry (see `record_plan_quality`) — note the import path's dangling
    edges are expected, so its dropped-edge counts read differently from a
    strict generate's.
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
    org = await db.get(Organization, team.organization_id)
    await _persist_milestones(project, milestones, org, db, strict=strict, source=source)
    return project
