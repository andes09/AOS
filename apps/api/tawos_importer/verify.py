"""Post-import verification for simulated (TAWOS) orgs.

Run after an import to catch silent data-shape regressions. All checks are
read-only — this never mutates the DB.

Usage (from apps/api/):
    python -m tawos_importer.verify                       # every simulated org
    python -m tawos_importer.verify --team-id <uuid>      # a specific team
    python -m tawos_importer.verify --project-key APACHE-KAFKA

Exit code:
    0 = all green
    1 = at least one check reported issues (still prints details for all checks)
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import AsyncSessionLocal
from src.models import (
    Organization,
    Team,
    Ticket,
    TicketStatus,
)


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str = ""


async def check_empty_sprints(session: AsyncSession, team_ids: list[uuid.UUID]) -> CheckResult:
    """Sprints with zero tickets are valid but usually indicate a mapping bug."""
    rows = (await session.execute(text("""
        SELECT s.id, s.name
        FROM sprints s
        LEFT JOIN tickets t ON t.sprint_id = s.id
        WHERE s.team_id = ANY(:team_ids)
        GROUP BY s.id, s.name
        HAVING COUNT(t.id) = 0
    """), {"team_ids": team_ids})).all()
    if not rows:
        return CheckResult("empty_sprints", True, "every sprint has ≥1 ticket")
    sample = ", ".join(r.name for r in rows[:5])
    return CheckResult("empty_sprints", False,
                       f"{len(rows)} sprints have 0 tickets (e.g. {sample})")


async def check_ticket_statuses(session: AsyncSession, team_ids: list[uuid.UUID]) -> CheckResult:
    """Every ticket.status must be a valid TicketStatus enum."""
    valid = {s.name for s in TicketStatus}
    stmt = select(Ticket.status, func.count(Ticket.id)).where(Ticket.team_id.in_(team_ids)).group_by(Ticket.status)
    rows = (await session.execute(stmt)).all()
    invalid = [(s, n) for s, n in rows if (s.name if hasattr(s, "name") else str(s)) not in valid]
    if invalid:
        return CheckResult("ticket_status_enum", False,
                           f"invalid statuses: {invalid}")
    breakdown = ", ".join(f"{s.name if hasattr(s, 'name') else s}={n}" for s, n in rows)
    return CheckResult("ticket_status_enum", True, f"all statuses valid — {breakdown}")


async def check_sprint_points_match(session: AsyncSession, team_ids: list[uuid.UUID]) -> CheckResult:
    """Sprint.committed_points should equal sum of tickets' story_points_estimated.

    Tolerates floating-point noise (absolute diff < 0.01).
    """
    rows = (await session.execute(text("""
        SELECT s.id, s.name, s.committed_points,
               COALESCE(SUM(t.story_points_estimated), 0) AS computed
        FROM sprints s
        LEFT JOIN tickets t ON t.sprint_id = s.id
        WHERE s.team_id = ANY(:team_ids)
        GROUP BY s.id, s.name, s.committed_points
    """), {"team_ids": team_ids})).all()
    mismatches = [
        r for r in rows
        if r.committed_points is not None
        and abs((r.committed_points or 0) - (float(r.computed) or 0)) > 0.01
    ]
    if mismatches:
        sample = ", ".join(f"{r.name}({r.committed_points}vs{r.computed})" for r in mismatches[:3])
        return CheckResult("sprint_points_match", False,
                           f"{len(mismatches)} sprints have committed_points ≠ sum(story_points) — {sample}")
    return CheckResult("sprint_points_match", True,
                       f"committed_points matches tickets on {len(rows)} sprints")


async def check_dependency_ticket_keys(session: AsyncSession, team_ids: list[uuid.UUID]) -> CheckResult:
    """Every dependency's ticket_key and blocked_by_key should reference a
    real ticket in the same team (soft FK — there's no DB-level constraint)."""
    rows = (await session.execute(text("""
        WITH dep AS (
            SELECT d.id, d.ticket_key, d.blocked_by_key
            FROM dependencies d
            WHERE d.team_id = ANY(:team_ids)
        ),
        keys AS (
            SELECT jira_issue_key FROM tickets WHERE team_id = ANY(:team_ids)
        )
        SELECT d.id, d.ticket_key, d.blocked_by_key,
               (d.ticket_key    IN (SELECT jira_issue_key FROM keys)) AS ticket_exists,
               (d.blocked_by_key IN (SELECT jira_issue_key FROM keys)) AS blocker_exists
        FROM dep d
    """), {"team_ids": team_ids})).all()
    orphans = [r for r in rows if not r.ticket_exists or not r.blocker_exists]
    if not rows:
        return CheckResult("dependency_refs", True, "no dependencies to check")
    if orphans:
        return CheckResult("dependency_refs", False,
                           f"{len(orphans)}/{len(rows)} dependencies reference unknown tickets")
    return CheckResult("dependency_refs", True,
                       f"all {len(rows)} dependencies reference real tickets")


async def check_ticket_sprint_orphans(session: AsyncSession, team_ids: list[uuid.UUID]) -> CheckResult:
    """A ticket.sprint_id that points to a non-existent sprint is a bug — FKs
    should prevent this, but check defensively."""
    row = (await session.execute(text("""
        SELECT COUNT(*) AS n
        FROM tickets t
        WHERE t.team_id = ANY(:team_ids)
          AND t.sprint_id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM sprints s WHERE s.id = t.sprint_id)
    """), {"team_ids": team_ids})).first()
    if row.n:
        return CheckResult("ticket_sprint_orphans", False, f"{row.n} tickets point at missing sprints")
    return CheckResult("ticket_sprint_orphans", True, "no orphaned ticket.sprint_id")


async def check_developers_have_work(session: AsyncSession, team_ids: list[uuid.UUID]) -> CheckResult:
    """At least some developers should have completed work — if zero do, the
    status-mapping tokens are likely wrong for this project."""
    row = (await session.execute(text("""
        SELECT COUNT(DISTINCT st.assignee_id) AS n
        FROM sprint_tickets st
        JOIN sprints s ON s.id = st.sprint_id
        WHERE s.team_id = ANY(:team_ids) AND st.completed = TRUE AND st.assignee_id IS NOT NULL
    """), {"team_ids": team_ids})).first()
    total = (await session.execute(text("""
        SELECT COUNT(*) AS n FROM developers WHERE team_id = ANY(:team_ids)
    """), {"team_ids": team_ids})).first()
    if total.n == 0:
        return CheckResult("developers_have_work", True, "no developers to check")
    if row.n == 0:
        return CheckResult("developers_have_work", False,
                           "no developer has any completed sprint_tickets — check status mapping")
    return CheckResult("developers_have_work", True,
                       f"{row.n}/{total.n} developers have completed work")


# --------------------------------------------------------------------------- #

async def resolve_team_ids(session: AsyncSession, team_id_arg: str | None,
                           project_key_arg: str | None) -> list[uuid.UUID]:
    if team_id_arg:
        return [uuid.UUID(team_id_arg)]
    if project_key_arg:
        rows = (await session.execute(
            select(Team.id).where(Team.jira_project_key == project_key_arg)
        )).scalars().all()
        if not rows:
            raise SystemExit(f"no team found with jira_project_key={project_key_arg!r}")
        return list(rows)

    rows = (await session.execute(
        select(Team.id)
        .join(Organization, Team.organization_id == Organization.id)
        .where(Organization.is_simulated == True)  # noqa: E712
    )).scalars().all()
    if not rows:
        raise SystemExit("no simulated teams found — run an import first")
    return list(rows)


async def run() -> int:
    parser = argparse.ArgumentParser(description="Verify TAWOS imports")
    parser.add_argument("--team-id", help="verify one team (uuid)")
    parser.add_argument("--project-key", help="verify teams with this jira_project_key")
    args = parser.parse_args()

    async with AsyncSessionLocal() as session:
        team_ids = await resolve_team_ids(session, args.team_id, args.project_key)
        print(f"verifying {len(team_ids)} team(s)")

        checks = [
            check_empty_sprints(session, team_ids),
            check_ticket_statuses(session, team_ids),
            check_sprint_points_match(session, team_ids),
            check_dependency_ticket_keys(session, team_ids),
            check_ticket_sprint_orphans(session, team_ids),
            check_developers_have_work(session, team_ids),
        ]
        results = []
        for coro in checks:
            results.append(await coro)

    print()
    any_fail = False
    for r in results:
        marker = "OK " if r.ok else "FAIL"
        print(f"  [{marker}] {r.name}: {r.detail}")
        if not r.ok:
            any_fail = True
    return 1 if any_fail else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
