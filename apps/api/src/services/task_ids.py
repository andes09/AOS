"""
Task.short_id allocation — the human-referenceable handle ("AOS-142")
developers put in branch names / commit messages / PR titles so GitHub
activity can auto-complete a task (see
docs/plans/2026-07-20-github-task-autocomplete.md).

Shared by every Task-creation call site (routers/roadmap.py's quick-add,
services/roadmap_shapes.py's AI-drafted-roadmap persistence, and
services/roadmap_adjuster.py's re-plan/extend-day) so that *every* task gets
a short_id, not just the ones created through the manual "+" button —
otherwise the auto-complete feature would silently not work for the
AI-generated tasks that make up most of a plan.
"""

import re

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.organization import Organization


def _short_id_prefix(slug: str) -> str:
    """Uppercase, alnum-only, truncated to 8 chars. Falls back to "TASK" if
    the slug has no alnum characters — shouldn't happen (slugs are validated
    at org-creation time), but a short_id must never end up with an empty
    prefix like "-142"."""
    alnum = re.sub(r"[^A-Za-z0-9]", "", slug or "").upper()
    return alnum[:8] or "TASK"


async def allocate_short_ids(org: Organization, count: int, db: AsyncSession) -> list[str]:
    """Atomically reserve `count` sequence numbers from `org.next_task_seq`
    and return the resulting short_id strings, e.g. ["AOS-142", "AOS-143"].

    A single `UPDATE ... RETURNING` bumps the counter by the whole batch in
    one round trip under one row lock, so concurrent task creation for the
    same org (whether one task from the quick-add endpoint, or a few dozen
    from an AI-drafted roadmap) can never collide on a sequence number.
    """
    if count <= 0:
        return []
    last = await db.scalar(
        update(Organization)
        .where(Organization.id == org.id)
        .values(next_task_seq=Organization.next_task_seq + count)
        .returning(Organization.next_task_seq)
    )
    # Keep the in-memory instance consistent with what's now in the DB, in
    # case the caller reads org.next_task_seq again later in the same request.
    org.next_task_seq = last
    prefix = _short_id_prefix(org.slug)
    first = last - count + 1
    return [f"{prefix}-{seq}" for seq in range(first, last + 1)]


async def allocate_short_id(org: Organization, db: AsyncSession) -> str:
    """Single-task convenience wrapper around `allocate_short_ids`."""
    return (await allocate_short_ids(org, 1, db))[0]
