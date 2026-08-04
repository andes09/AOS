"""
Activity tracking — the seam behind the anti-dormancy MVP.

Two concerns live here:
  1. *Touching* a developer's `last_active_at` when they do something. Kept as
     standalone functions (not inlined in a router) so the future GitHub
     task-autocomplete Celery path can import and call `touch_developer_activity`
     the moment it flips a task to `done` from a webhook — the dormancy signal
     then benefits from GitHub activity for free, no dormancy-job changes needed.
  2. Building the *re-engagement summary* the "welcome back" banner reads on the
     landing surface — org-scoped, because `last_active_at` is per-developer
     (one person, not one project) and an org can carry several projects.

Every write filters to `clerk_user_id IS NOT NULL`: `Developer` is shared with
the legacy Jira-roster feature, whose rows are placeholders with no real
signed-in account. Touching those would track phantoms.

See docs/plans/2026-07-20-anti-dormancy-mvp.md.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.developer import Developer
from src.models.milestone import Milestone
from src.models.organization import Organization
from src.models.project import Project, ProjectStatus
from src.models.task import Task, TaskStatus
from src.models.team import Team

# How long a developer must have been away before the in-app banner greets them
# as "returning." Below this we say nothing — a same-day revisit isn't a
# re-engagement moment. The push-based email job (Milestone 2/3) uses its own,
# longer thresholds; this one only governs the live banner.
RETURNING_THRESHOLD_DAYS = 2

# The banner shows a capped next-step list, not the whole tree — the direct
# antidote to "I opened my roadmap and felt overwhelmed."
NEXT_UP_LIMIT = 3


def _status_str(status) -> str:
    """Normalize a possibly-enum Task.status to its plain string value.

    `Task.status` is a SAEnum(native_enum=False) column, so a row loaded from
    the DB carries the `TaskStatus` *member*, not its string — a local copy of
    the same helper roadmap_service.py / integrations/github/events.py keep next
    to their own callers (this repo's precedent over a shared utils grab-bag).
    """
    return status.value if isinstance(status, TaskStatus) else status


async def touch_developer_activity(developer_id: uuid.UUID, db: AsyncSession) -> None:
    """Mark one developer active *now*, by id.

    No-op for a roster placeholder (null `clerk_user_id`) — those aren't real
    accounts. Does not commit: the caller's request/session owns the commit.
    Used for the assignee-touch on task completion, where the person credited
    isn't necessarily the caller.
    """
    dev = await db.get(Developer, developer_id)
    if dev is not None and dev.clerk_user_id is not None:
        dev.last_active_at = datetime.utcnow()


async def touch_by_clerk_user(clerk_user_id: str, db: AsyncSession) -> datetime | None:
    """Mark every developer row for this Clerk user active *now*.

    A Clerk user can own more than one `Developer` row (the model is keyed by
    team, and one person can sit on several teams), so all of them are touched.

    Returns the *previous* most-recent `last_active_at` across those rows
    (None if the user has never been active or has no real developer row) —
    captured before the overwrite so the caller can tell how long they were
    away. Does not commit: the request's session commit persists the writes.
    """
    devs = list(
        await db.scalars(
            select(Developer).where(Developer.clerk_user_id == clerk_user_id)
        )
    )
    previous = max(
        (d.last_active_at for d in devs if d.last_active_at is not None),
        default=None,
    )
    now = datetime.utcnow()
    for d in devs:
        d.last_active_at = now
    return previous


async def re_engagement_summary(
    org: Organization,
    previous_last_active: datetime | None,
    db: AsyncSession,
) -> dict:
    """The "welcome back" banner's payload, aggregated across the org's active
    projects.

    `previous_last_active` is the value read *before* this request touched it —
    so "completed since last visit" and "days away" reflect the gap the user
    was actually gone, not zero.
    """
    tasks = list(
        await db.scalars(
            select(Task)
            .join(Milestone, Task.milestone_id == Milestone.id)
            .join(Project, Milestone.project_id == Project.id)
            .join(Team, Project.team_id == Team.id)
            .where(
                Team.organization_id == org.id,
                Project.status == ProjectStatus.ACTIVE.value,
            )
        )
    )

    today = date.today()
    remaining = [t for t in tasks if _status_str(t.status) != TaskStatus.DONE.value]
    overdue = [t for t in remaining if t.scheduled_date is not None and t.scheduled_date < today]

    completed_since = 0
    if previous_last_active is not None:
        completed_since = sum(
            1
            for t in tasks
            if _status_str(t.status) == TaskStatus.DONE.value
            and t.completed_at is not None
            and t.completed_at > previous_last_active
        )

    todo = [t for t in tasks if _status_str(t.status) == TaskStatus.TODO.value]
    # Scheduled work first (earliest day), then unscheduled, then by sort order —
    # the same "what should I do next" ordering the planner's list view uses.
    todo.sort(key=lambda t: (t.scheduled_date is None, t.scheduled_date or date.max, t.sort_order))
    next_up = [
        {
            "id": str(t.id),
            "shortId": t.short_id,
            "title": t.title,
            "scheduledDate": t.scheduled_date.isoformat() if t.scheduled_date else None,
        }
        for t in todo[:NEXT_UP_LIMIT]
    ]

    if previous_last_active is not None:
        days_since = (datetime.utcnow() - previous_last_active).days
    else:
        days_since = None

    return {
        "isReturning": days_since is not None and days_since >= RETURNING_THRESHOLD_DAYS,
        "daysSinceLastActive": days_since,
        "tasksRemaining": len(remaining),
        "tasksCompletedSinceLastVisit": completed_since,
        "overdueCount": len(overdue),
        "nextUp": next_up,
    }
