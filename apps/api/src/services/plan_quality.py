"""Plan-quality telemetry (Initiative A, Wave 4 — SA-15).

Computes per-sprint override rate (count of plan overrides / count of assignments)
and persists the result on the Sprint row for later trend analysis on the Exec
Dashboard.

Definitions
-----------
* total_assignments  = COUNT(SprintTicket WHERE sprint_id == sprint.id).
  (SprintTicket is the established assignment source — see retro_ai.py, exec.py,
  velocity.py — so we follow that convention.)
* override_count     = COUNT(SprintPlanOverride WHERE sprint_id == sprint.id).
* override_rate      = override_count / total_assignments  (0.0 if no assignments).
* overrides_by_reason: dict[reason_code, count]; NULL reason_code → "unspecified".

TODO(Wave 6): wire `persist_plan_quality` from
``apps/api/src/integrations/jira/sync.py`` when a sprint transitions to COMPLETED.
"""
from __future__ import annotations

import uuid
from collections import Counter

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.sprint import Sprint, SprintStatus, SprintTicket
from src.models.sprint_plan_override import SprintPlanOverride


def _coerce_uuid(value: str | uuid.UUID) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _reason_key(reason_code) -> str:
    """Normalize a reason_code (str, Enum, or None) to its string key."""
    if reason_code is None:
        return "unspecified"
    if hasattr(reason_code, "value"):
        return str(reason_code.value)
    return str(reason_code)


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
    override_rate = (
        0.0
        if total_assignments == 0
        else round(override_count / total_assignments, 4)
    )

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

    TODO(Wave 6): wire from apps/api/src/integrations/jira/sync.py when a sprint
    transitions to COMPLETED.
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
