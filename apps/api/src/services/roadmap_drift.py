"""
Drift detection — does the plan still describe what's actually being built?

A generated roadmap goes stale the moment reality diverges from it, and today
nothing notices: the plan sits unchanged until a human remembers to hit
regenerate. This module reads the two things we already know — what the plan
says should be happening (`Task.scheduled_date` / `status`) and what the repo
says *is* happening (`github_activity_events`, matched by
integrations/github/events.py) — and names the gaps.

It only ever reports. Nothing here mutates a plan; acting on a signal is a
human decision (`POST /roadmap/reconcile`). That's deliberate — a roadmap that
silently rewrites itself is worse than one that's out of date, because you can
no longer trust that what you read yesterday is what it says today.

Computed on read, with no snapshot table, mirroring
`activity.re_engagement_summary`. Drift is a pure function of rows that already
exist, so persisting it would create a second source of truth that can only be
wrong.

**`Milestone` has no dates and no status** — it is a title, a description and a
`sort_order` (models/milestone.py). Every notion of "when" a milestone was
meant to happen is therefore derived from its tasks' `scheduled_date`. A
milestone whose tasks are all unscheduled has no schedule to be behind, so it
reads as *not drifting* rather than permanently late; getting that backwards
would light up the banner for every user who never scheduled anything.
"""

import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.github_activity_event import GithubActivityEvent, MatchMethod
from src.models.github_connection import GithubConnection
from src.models.milestone import Milestone
from src.models.project import Project
from src.models.task import Task, TaskStatus

logger = logging.getLogger(__name__)

#: How far back the signals look. Two weeks is long enough that a quiet week
#: (holiday, day job) doesn't trip the alarm, short enough that a real stall
#: surfaces while it's still actionable.
DEFAULT_WINDOW_DAYS = 14

#: A milestone must be this far past its own scheduled work before "stalled"
#: means anything — a task slipping by a day or two is normal.
STALLED_GRACE_DAYS = 3

#: Below this share of unplanned events there's nothing to say; some
#: off-roadmap work (chores, fixes) is healthy and expected.
UNPLANNED_SHARE_THRESHOLD = 0.6
#: ...and a handful of commits isn't a trend, whatever the percentage.
UNPLANNED_MIN_EVENTS = 5

#: How early a task has to be finished before it says the plan was too
#: conservative rather than that someone had a good afternoon.
AHEAD_MIN_DAYS = 3
AHEAD_MIN_TASKS = 2

#: Cap on the examples attached to a signal — enough to make it concrete
#: without turning the banner into a commit log.
MAX_EVIDENCE = 5


@dataclass
class DriftSignal:
    kind: str
    severity: str  # "info" | "warning"
    headline: str
    detail: str
    milestone_ids: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        data = asdict(self)
        data["milestoneIds"] = data.pop("milestone_ids")
        return data


def _status_str(status) -> str:
    """`tasks.status` is a SAEnum column and reloads as the enum member, so a
    bare `== "done"` silently fails — same footgun as
    integrations/github/events.py's helper of this name."""
    return status.value if isinstance(status, TaskStatus) else status


def _is_done(task: Task) -> bool:
    return _status_str(task.status) == TaskStatus.DONE.value


def _plural(n: int, singular: str, plural: str | None = None) -> str:
    return f"{n} {singular}" if n == 1 else f"{n} {plural or singular + 's'}"


# ─── signals ─────────────────────────────────────────────────────────────────
def _stalled_milestones(
    milestones: list[Milestone],
    active_task_ids: set[uuid.UUID],
    today: date,
) -> DriftSignal | None:
    """Milestones whose scheduled work is overdue and which no recent commit
    touched.

    Both halves are required. Overdue alone is just an optimistic estimate —
    extremely common and not worth interrupting anyone over. Overdue *and*
    silent in the repo is the thing worth saying out loud: this milestone has
    stopped moving.
    """
    cutoff = today - timedelta(days=STALLED_GRACE_DAYS)
    stalled: list[Milestone] = []

    for milestone in milestones:
        open_tasks = [t for t in milestone.tasks if not _is_done(t)]
        if not open_tasks:
            continue
        # No scheduled work => no schedule to be behind. See module docstring.
        overdue = [t for t in open_tasks if t.scheduled_date and t.scheduled_date < cutoff]
        if not overdue:
            continue
        if any(t.id in active_task_ids for t in milestone.tasks):
            continue
        stalled.append(milestone)

    if not stalled:
        return None

    names = ", ".join(f'"{m.title}"' for m in stalled[:MAX_EVIDENCE])
    return DriftSignal(
        kind="stalled_milestone",
        severity="warning",
        headline=f"{_plural(len(stalled), 'milestone')} stalled",
        detail=(
            f"{names} {'has' if len(stalled) == 1 else 'have'} overdue tasks and no "
            f"matching commits in the last {DEFAULT_WINDOW_DAYS} days."
        ),
        milestone_ids=[str(m.id) for m in stalled],
    )


def _unplanned_work(events: list[GithubActivityEvent]) -> DriftSignal | None:
    """A high share of shipped work that maps to no task in the plan.

    This is the signal the whole matching pipeline exists to make trustworthy:
    before tiers 2 and 3 (heuristics, classifier) it would read ~100% for
    every user, because it only counted commits that named a task outright.
    """
    if len(events) < UNPLANNED_MIN_EVENTS:
        return None

    unplanned = [e for e in events if e.matched_task_id is None]
    share = len(unplanned) / len(events)
    if share < UNPLANNED_SHARE_THRESHOLD:
        return None

    examples = [
        (e.branch or e.title_or_message or "").strip().splitlines()[0][:120]
        for e in unplanned[:MAX_EVIDENCE]
    ]
    return DriftSignal(
        kind="unplanned_work",
        severity="warning",
        headline=f"{round(share * 100)}% of recent work isn't in the plan",
        detail=(
            f"{len(unplanned)} of the last {len(events)} commits and pull requests "
            "don't correspond to any roadmap task."
        ),
        evidence=[e for e in examples if e],
    )


def _silent_repo(
    project: Project,
    events: list[GithubActivityEvent],
    open_task_count: int,
    connection: GithubConnection | None,
    *,
    window_days: int,
    now: datetime,
) -> DriftSignal | None:
    """A linked repo with open work and nothing happening in it.

    Distinct from a stalled milestone: this fires even when nothing is
    scheduled, because a connected repo going quiet with work outstanding is
    the earliest sign a plan is being abandoned rather than executed.

    Guarded on the connection being older than the window. A repo linked
    yesterday legitimately has no events yet, and greeting someone with "no
    activity for 14 days" the day after they connected would be both wrong and
    the first thing they see after onboarding.
    """
    if not project.github_repo_full_name or connection is None:
        return None
    if events or open_task_count == 0:
        return None
    if connection.created_at is None or connection.created_at > now - timedelta(days=window_days):
        return None
    return DriftSignal(
        kind="silent_repo",
        severity="warning",
        headline="No repo activity",
        detail=(
            f"No commits or pull requests in {project.github_repo_full_name} for "
            f"{window_days} days, with {_plural(open_task_count, 'task')} still open."
        ),
    )


def _ahead_of_plan(milestones: list[Milestone], today: date) -> DriftSignal | None:
    """Tasks finishing well before their scheduled date.

    Drift is not only lateness. A plan that consistently over-estimates is
    just as stale, and it's the pleasant case a founder would never think to
    go looking for — later milestones could be pulled forward.
    """
    early: list[Task] = []
    for milestone in milestones:
        for task in milestone.tasks:
            if not _is_done(task) or task.completed_at is None or task.scheduled_date is None:
                continue
            days_early = (task.scheduled_date - task.completed_at.date()).days
            if days_early >= AHEAD_MIN_DAYS:
                early.append(task)

    if len(early) < AHEAD_MIN_TASKS:
        return None

    return DriftSignal(
        kind="ahead_of_plan",
        severity="info",
        headline="Running ahead of schedule",
        detail=(
            f"{_plural(len(early), 'task')} finished at least {AHEAD_MIN_DAYS} days early — "
            "the remaining milestones may be able to move up."
        ),
        evidence=[t.title[:120] for t in early[:MAX_EVIDENCE]],
    )


# ─── entry point ─────────────────────────────────────────────────────────────
async def compute_drift(
    org_id: uuid.UUID,
    project: Project,
    db: AsyncSession,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    today: date | None = None,
) -> dict:
    """The `GET /roadmap/drift` payload.

    `project` is expected to arrive with milestones and tasks eager-loaded
    (`project_common._owned_project` already does this), so this issues two
    queries: recent activity, and whether a GitHub connection exists at all.

    Side-effect free by construction — see the module docstring, and the note
    in docs/plans about composing with the dormancy job.
    """
    today = today or date.today()
    now = datetime.utcnow()
    since = now - timedelta(days=window_days)

    events = list(
        await db.scalars(
            select(GithubActivityEvent)
            .where(
                GithubActivityEvent.organization_id == org_id,
                GithubActivityEvent.occurred_at >= since,
            )
            .order_by(GithubActivityEvent.occurred_at.desc())
        )
    )
    connection = await db.scalar(
        select(GithubConnection).where(
            GithubConnection.organization_id == org_id,
            GithubConnection.is_active == True,  # noqa: E712
        )
    )

    milestones = list(project.milestones)
    active_task_ids = {e.matched_task_id for e in events if e.matched_task_id is not None}
    open_task_count = sum(1 for m in milestones for t in m.tasks if not _is_done(t))

    signals = [
        s
        for s in (
            _stalled_milestones(milestones, active_task_ids, today),
            _unplanned_work(events),
            _silent_repo(
                project, events, open_task_count, connection,
                window_days=window_days, now=now,
            ),
            _ahead_of_plan(milestones, today),
        )
        if s is not None
    ]
    # Warnings first — the banner shows the most consequential thing at the top.
    signals.sort(key=lambda s: (s.severity != "warning", s.kind))

    return {
        "hasDrift": any(s.severity == "warning" for s in signals),
        "computedAt": datetime.utcnow().isoformat(),
        "windowDays": window_days,
        "repoConnected": connection is not None and bool(project.github_repo_full_name),
        "signals": [s.to_json() for s in signals],
    }


async def build_reconcile_context(
    org_id: uuid.UUID,
    project: Project,
    db: AsyncSession,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> str | None:
    """Drift evidence, rendered as extra context for the roadmap adjuster.

    Returns None when there's nothing to say, so the caller can skip the LLM
    call entirely rather than paying for a no-op re-plan.

    This is deliberately *returned* rather than written into `Task.feedback`.
    That column belongs to the user — it's what they typed about their own
    progress — and having a background signal quietly overwrite it would
    destroy real input and then feed the destruction back into the planner on
    every subsequent adjust.
    """
    report = await compute_drift(org_id, project, db, window_days=window_days)
    signals = report["signals"]
    if not signals:
        return None

    lines = [
        "Observed activity in the connected GitHub repository over the last "
        f"{window_days} days, compared against this plan:",
    ]
    for signal in signals:
        lines.append(f"- {signal['headline']}: {signal['detail']}")
        for item in signal["evidence"]:
            lines.append(f"    · {item}")

    unplanned = next((s for s in signals if s["kind"] == "unplanned_work"), None)
    if unplanned:
        lines.append(
            "Work that isn't in the plan is still real work that got done. Where those "
            "commits describe something the plan is missing, add or amend tasks to "
            "reflect it rather than ignoring it."
        )
    if any(s["kind"] == "stalled_milestone" for s in signals):
        lines.append(
            "For stalled milestones, reconsider whether the remaining tasks are still "
            "the right next step, and re-date them from today."
        )
    if any(s["kind"] == "ahead_of_plan" for s in signals):
        lines.append("Work is landing ahead of schedule — pull the remaining tasks earlier.")

    return "\n".join(lines)
