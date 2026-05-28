"""Scope Cop revision-acceptance telemetry (Initiative B, Wave 4 — SB-14).

DB-derived telemetry (this codebase has NO PostHog / event bus). The
`ticket_revisions` table (Wave 0) is the event log: one row is written every
time a user pushes a Scope Cop revision through the inline-refinement flow, so
metrics are *derived* from it — we do not emit events.

Definitions
-----------
Per `ticket_revisions` row:
* proposed          — every row counts as a proposal (Scope Cop produced a
                      `suggested_revision`, which is what triggered the flow).
* accepted_verbatim — `applied_revision` equals `suggested_revision` on the
                      keys Scope Cop suggested (user pushed unchanged content).
* edited            — `applied_revision` differs from `suggested_revision` on a
                      suggested key but a non-empty edit was pushed (user
                      tweaked Scope Cop's content before pushing).
* acceptance_rate   — (accepted_verbatim + edited) / proposed. Both verbatim
                      and edited count as "landed": the plan's intent is "are
                      Scope Cop suggestions landing", so an edited-then-pushed
                      suggestion still landed. (0.0 if proposed == 0.)

Limitation — "dismissed"
------------------------
A dismissal (suggestion shown but never pushed) writes NO `ticket_revisions`
row, so there is no clean signal for it in this table. We therefore report
"dismissed" as N/A for v1 and do not fabricate a backing table. Because every
row was pushed in some form, `acceptance_rate` here is the *landed-given-pushed*
rate; true shown-vs-landed would require a separate impression log (v2).

Bucketing
---------
`ticket_revisions` has no `sprint_id`, so we bucket by the team's completed
`Sprint` date windows: for each of the last N completed sprints (ordered by
end_date), count revisions whose `applied_at` falls within
`[start_date, end_date]`. Sprints with a NULL start or end date capture no
revisions (window is undefined). Mirrors the shape/style of
`plan_quality.get_trailing_override_rates`.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.sprint import Sprint, SprintStatus
from src.models.ticket_revision import TicketRevision


def _coerce_uuid(value: str | uuid.UUID) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _normalize(value) -> object:
    """Normalize a suggested/applied field value for verbatim comparison.

    Strings are stripped (trailing whitespace from an editor shouldn't count as
    an edit); lists/dicts compare structurally; None and "" both read as empty.
    """
    if isinstance(value, str):
        return value.strip()
    return value


def _is_empty(value) -> bool:
    if value is None:
        return True
    if isinstance(value, (str, list, dict)):
        return len(value) == 0
    return False


def is_accepted_verbatim(suggested: dict | None, applied: dict | None) -> bool:
    """True when the applied revision matches the suggestion on every key that
    Scope Cop actually suggested (a non-empty suggested value).

    Compares only the suggested keys: extra keys the user added in `applied`
    don't count against verbatim, but every suggested key must match. An empty
    suggestion (nothing proposed) is not "verbatim accepted".
    """
    suggested = suggested or {}
    applied = applied or {}

    suggested_keys = [k for k, v in suggested.items() if not _is_empty(v)]
    if not suggested_keys:
        return False

    for key in suggested_keys:
        if _normalize(applied.get(key)) != _normalize(suggested.get(key)):
            return False
    return True


def _is_edited(suggested: dict | None, applied: dict | None) -> bool:
    """True when something non-empty was pushed but it differs from the
    suggestion on a suggested key (user tweaked Scope Cop's content)."""
    applied = applied or {}
    if all(_is_empty(v) for v in applied.values()):
        return False
    return not is_accepted_verbatim(suggested, applied)


def classify_revision(suggested: dict | None, applied: dict | None) -> str:
    """Classify a single revision row as 'accepted_verbatim' or 'edited'.

    Every row in `ticket_revisions` was pushed, so it is one of the two; there
    is no 'dismissed' bucket (see module docstring)."""
    if is_accepted_verbatim(suggested, applied):
        return "accepted_verbatim"
    return "edited"


def _to_datetime(value: date | datetime | None, *, end: bool = False) -> datetime | None:
    """Coerce a Sprint date (Date column) to a datetime window boundary so it
    can be compared against `applied_at` (a timestamp)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    # date → start-of-day for the lower bound, end-of-day for the upper bound.
    if end:
        return datetime(value.year, value.month, value.day, 23, 59, 59, 999999)
    return datetime(value.year, value.month, value.day)


def compute_acceptance_for_rows(rows: list) -> dict:
    """Compute acceptance counts/rate for a list of TicketRevision-like rows.

    Each row needs `suggested_revision` and `applied_revision` attributes.
    Returns: {proposed, accepted_verbatim, edited, acceptance_rate}.
    """
    proposed = len(rows)
    accepted_verbatim = 0
    edited = 0
    for r in rows:
        suggested = getattr(r, "suggested_revision", None)
        applied = getattr(r, "applied_revision", None)
        if classify_revision(suggested, applied) == "accepted_verbatim":
            accepted_verbatim += 1
        else:
            edited += 1

    landed = accepted_verbatim + edited
    acceptance_rate = 0.0 if proposed == 0 else round(landed / proposed, 4)
    return {
        "proposed": proposed,
        "accepted_verbatim": accepted_verbatim,
        "edited": edited,
        "acceptance_rate": acceptance_rate,
    }


async def get_revision_acceptance_rates(
    team_id, db: AsyncSession, n_sprints: int = 8
) -> list[dict]:
    """Return the last N completed sprints (oldest → newest) with Scope Cop
    revision-acceptance telemetry, bucketed by each sprint's date window.

    Each row:
      {
        "sprint_id":          str,
        "sprint_name":        str,
        "completed_at":       date | None,
        "proposed":           int,
        "accepted_verbatim":  int,
        "edited":             int,
        "acceptance_rate":    float,
      }
    """
    team_uuid = _coerce_uuid(team_id)

    # Newest-first so .limit() keeps the most recent N, then reverse.
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

    # All revisions for the team — bucketed in-memory by sprint window. Cheap:
    # one team's revision volume is small relative to a full-table scan per
    # sprint, and avoids N queries.
    revisions = list(
        (
            await db.scalars(
                select(TicketRevision).where(TicketRevision.team_id == team_uuid)
            )
        ).all()
    )

    points: list[dict] = []
    for s in sprints:
        window_start = _to_datetime(s.start_date)
        window_end = _to_datetime(s.end_date, end=True)

        if window_start is None or window_end is None:
            bucket: list = []
        else:
            bucket = [
                r
                for r in revisions
                if r.applied_at is not None
                and window_start <= r.applied_at <= window_end
            ]

        stats = compute_acceptance_for_rows(bucket)
        points.append(
            {
                "sprint_id": str(s.id),
                "sprint_name": s.name,
                "completed_at": s.end_date,
                **stats,
            }
        )

    return points
