"""Plan-quality telemetry.

Two halves, one question — "how good was the plan we produced?" — asked of the
two planning domains this codebase has had.

**Task dependency graph (current).** The roadmap planner drafts a DAG of tasks
(`task_dependencies` / `Task.depends_on`), and `roadmap_shapes.
resolve_task_dependencies` throws away the edges that don't survive validation:
references to a task that isn't in the batch, and cycles. Those raw per-build
counts land on `projects.plan_quality` (see `roadmap_shapes.record_plan_quality`);
this module turns them into a *generation-fidelity* rate, and separately measures
the *shape* of the resulting graph — how much of the plan can be worked in
parallel, and how long the unavoidable sequential spine is.

Rates are derived here rather than stored, so the column holds facts and any
change to how a rate is defined applies retroactively to every existing row.

**Sprint overrides (legacy).** The Jira-era per-sprint override rate, below.
Still fed by `routers/sprints.py`'s override endpoint, but its original trigger
(``integrations/jira/sync.py``, on sprint → COMPLETED) was deleted in the pivot,
so nothing calls `persist_plan_quality` today. Left in place rather than removed;
the DAG half above reuses its `_coerce_uuid` and `_rate` helpers.

Sprint definitions
------------------
* total_assignments  = COUNT(SprintTicket WHERE sprint_id == sprint.id).
  (SprintTicket is the established assignment source — see retro_ai.py, exec.py,
  velocity.py — so we follow that convention.)
* override_count     = COUNT(SprintPlanOverride WHERE sprint_id == sprint.id).
* override_rate      = override_count / total_assignments  (0.0 if no assignments).
* overrides_by_reason: dict[reason_code, count]; NULL reason_code → "unspecified".
"""
from __future__ import annotations

import uuid
from collections import Counter

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.milestone import Milestone
from src.models.project import Project
from src.models.sprint import Sprint, SprintStatus, SprintTicket
from src.models.sprint_plan_override import SprintPlanOverride
from src.models.task import Task
from src.services.roadmap_service import task_is_blocked
from src.services.roadmap_shapes import topological_levels


def _coerce_uuid(value: str | uuid.UUID) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _rate(count: int, total: int) -> float:
    """`count / total` as a 4dp rate, 0.0 when there's nothing to divide by.

    An empty denominator means "no signal", not "perfect" — but 0.0 is the
    honest floor for both override rate and dropped-edge rate, since neither
    can have gone wrong if nothing was proposed in the first place.
    """
    return 0.0 if total == 0 else round(count / total, 4)


def _reason_key(reason_code) -> str:
    """Normalize a reason_code (str, Enum, or None) to its string key."""
    if reason_code is None:
        return "unspecified"
    if hasattr(reason_code, "value"):
        return str(reason_code.value)
    return str(reason_code)


# ─── task dependency graph (current planning domain) ──────────────────────────
def summarize_dependency_resolution(stored: dict | None) -> dict | None:
    """Derive the generation-fidelity block from a stored `projects.plan_quality`.

    `dropped_edge_rate` is to the DAG what `override_rate` is to a sprint: the
    share of what was proposed that didn't survive. Returns None when the
    project has no telemetry — a roadmap generated before this was recorded is
    genuinely unknown, which is not the same as a clean build, so it must not
    render as 0.0.
    """
    resolution = (stored or {}).get("resolution")
    if not isinstance(resolution, dict):
        return None

    proposed = int(resolution.get("edges_proposed") or 0)
    dropped = int(resolution.get("edges_dropped") or 0)
    by_reason = resolution.get("dropped_by_reason")
    return {
        "edgesProposed": proposed,
        "edgesKept": int(resolution.get("edges_kept") or 0),
        "edgesDropped": dropped,
        "droppedEdgeRate": _rate(dropped, proposed),
        "droppedByReason": by_reason if isinstance(by_reason, dict) else {},
        "source": (stored or {}).get("source"),
        "recordedAt": (stored or {}).get("recorded_at"),
    }


def compute_dag_shape(tasks: list[Task]) -> dict:
    """Structural quality of a task DAG, from `Task` rows with `depends_on` loaded.

    Pure and synchronous — the caller is responsible for the eager load (see
    `compute_plan_quality`).

    * `rootCount` — tasks with no prerequisites: the work that can start
      immediately, i.e. the width of the plan's opening parallel front.
    * `criticalPathLength` — the number of topological levels: the minimum
      number of sequential steps to finish, however many people are working.
    * `maxParallelWidth` — the widest level: the most work that can ever be in
      flight at once.
    * `isolatedCount` — tasks with no edges in either direction. Not inherently
      bad, but a plan that is *all* isolated tasks is one the planner never
      really sequenced.
    * `cyclicCount` — should always be 0: cycles are rejected at write time by
      `resolve_task_dependencies`. Reported anyway so a graph that somehow got
      one is visible rather than silently distorting the metrics above.

    Edges are counted only between tasks in `tasks`; an edge pointing outside
    the set (impossible for a whole project, since dependencies never cross a
    project boundary) is ignored rather than counted against the shape.
    """
    ids = {str(t.id) for t in tasks}
    graph = {
        str(t.id): {str(d.id) for d in t.depends_on if str(d.id) in ids} for t in tasks
    }
    levels, cyclic = topological_levels(graph)

    has_dependents = {dep for deps in graph.values() for dep in deps}
    return {
        "taskCount": len(tasks),
        "edgeCount": sum(len(deps) for deps in graph.values()),
        "rootCount": sum(1 for deps in graph.values() if not deps),
        "isolatedCount": sum(
            1 for tid, deps in graph.items() if not deps and tid not in has_dependents
        ),
        "criticalPathLength": len(levels),
        "maxParallelWidth": max((len(level) for level in levels), default=0),
        "blockedCount": sum(1 for t in tasks if task_is_blocked(t)),
        "cyclicCount": len(cyclic),
    }


async def compute_plan_quality(project_id, db: AsyncSession) -> dict:
    """Plan quality for one project: stored generation fidelity + live DAG shape.

    The two halves are deliberately sourced differently. Generation fidelity is
    a fact about the moment the plan was built and is unrecoverable afterwards,
    so it's read from the persisted column. DAG shape is recomputed from the
    current rows, so it reflects tasks the user has since added, deleted, or
    completed rather than a stale snapshot.

    Returns `{"generation": ... | None, "shape": ...}`. `generation` is None for
    a project with no recorded telemetry; `shape` is always present (an empty
    project reports zeroes).
    """
    project_uuid = _coerce_uuid(project_id)
    project = await db.scalar(select(Project).where(Project.id == project_uuid))
    if project is None:
        return {"generation": None, "shape": compute_dag_shape([])}

    tasks = list(
        (
            await db.scalars(
                select(Task)
                .join(Milestone, Task.milestone_id == Milestone.id)
                .where(Milestone.project_id == project_uuid)
                # Mandatory, not stylistic: Task.depends_on is a self-referential
                # `secondary=` relationship whose mapper-level selectin default
                # never fires, so without this every `d.id` below is a lazy load
                # that raises MissingGreenlet under asyncio. See models/task.py.
                .options(selectinload(Task.depends_on))
            )
        ).all()
    )

    return {
        "generation": summarize_dependency_resolution(project.plan_quality),
        "shape": compute_dag_shape(tasks),
    }


# ─── sprint overrides (legacy — see module docstring) ─────────────────────────
async def compute_sprint_override_rate(sprint_id, db: AsyncSession) -> dict:
    """Compute override-rate telemetry for a single sprint.

    Returns a dict:
      {
        "override_rate":      float,            # override_count / total_assignments
        "overrides_by_reason": dict[str, int],  # keyed by reason_code (or "unspecified")
        "override_count":     int,
        "total_assignments":  int,
      }
    """
    sprint_uuid = _coerce_uuid(sprint_id)

    overrides = list(
        (
            await db.scalars(
                select(SprintPlanOverride).where(
                    SprintPlanOverride.sprint_id == sprint_uuid
                )
            )
        ).all()
    )
    assignments = list(
        (
            await db.scalars(
                select(SprintTicket).where(SprintTicket.sprint_id == sprint_uuid)
            )
        ).all()
    )

    override_count = len(overrides)
    total_assignments = len(assignments)
    override_rate = _rate(override_count, total_assignments)

    counter: Counter[str] = Counter()
    for o in overrides:
        counter[_reason_key(getattr(o, "reason_code", None))] += 1

    return {
        "override_rate": override_rate,
        "overrides_by_reason": dict(counter),
        "override_count": override_count,
        "total_assignments": total_assignments,
    }


async def persist_plan_quality(sprint_id, db: AsyncSession) -> None:
    """Compute override-rate telemetry and persist it to the Sprint row.

    Writes:
      * sprints.plan_override_rate
      * sprints.plan_overrides_by_reason

    Commits the session. No-op (silent) if the sprint cannot be found.

    Currently uncalled: this was triggered from ``integrations/jira/sync.py`` on
    sprint → COMPLETED, and that module was deleted in the pivot to the roadmap
    planner. See the module docstring.
    """
    sprint_uuid = _coerce_uuid(sprint_id)
    sprint = await db.scalar(select(Sprint).where(Sprint.id == sprint_uuid))
    if sprint is None:
        return

    telemetry = await compute_sprint_override_rate(sprint_uuid, db)
    sprint.plan_override_rate = telemetry["override_rate"]
    sprint.plan_overrides_by_reason = telemetry["overrides_by_reason"]
    await db.commit()


async def get_trailing_override_rates(
    team_id, db: AsyncSession, n_sprints: int = 8
) -> list[dict]:
    """Return the last N completed sprints (oldest → newest) with their persisted
    plan-quality telemetry.

    Each row:
      {
        "sprint_id":          str,
        "sprint_name":        str,
        "completed_at":       datetime | None,
        "override_rate":      float | None,
        "overrides_by_reason": dict[str, int] | None,
      }
    """
    team_uuid = _coerce_uuid(team_id)

    # Query newest-first (so .limit() keeps the most recent N), then reverse.
    sprints = list(
        (
            await db.scalars(
                select(Sprint)
                .where(
                    Sprint.team_id == team_uuid,
                    Sprint.status == SprintStatus.COMPLETED,
                )
                .order_by(Sprint.end_date.desc().nullslast())
                .limit(n_sprints)
            )
        ).all()
    )
    sprints.reverse()  # oldest → newest

    return [
        {
            "sprint_id": str(s.id),
            "sprint_name": s.name,
            "completed_at": s.end_date,
            "override_rate": getattr(s, "plan_override_rate", None),
            "overrides_by_reason": getattr(s, "plan_overrides_by_reason", None),
        }
        for s in sprints
    ]
