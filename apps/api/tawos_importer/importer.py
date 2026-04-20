"""Import a single TAWOS project into Omada's Postgres.

Contract:
  - One async DB transaction per project; any error rolls back everything.
  - Order matters because of FK dependencies:
      1. Organization (needs org.id before team)
      2. Team (needs team.id before developers/sprints/tickets)
      3. Developers + TeamMembers (both reference team.id; TeamMember.id is
         the FK target for Ticket.assignee_id)
      4. Sprints (team_id)
      5. Tickets batched in 500s (team_id + sprint_id + team_member.id)
      6. SprintTicket rows (sprint_id + developer_id for velocity attribution)
      7. Dependencies (team_id)
      8. Derived: Sprint.committed_points / delivered_points
      9. Commit

  - Source DB (TAWOS MySQL) is fully read before any Postgres write begins,
    so a MySQL connection failure never leaves a dangling pg tx.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.database import AsyncSessionLocal
from src.models import (
    Sprint,
    SprintTicket,
    Ticket,
    TicketStatus,
)
from tawos_importer.config import setup_logging
from tawos_importer.mapper import (
    build_dependency,
    compute_sprint_points,
    map_issue,
    map_link,
    map_project,
    map_sprint,
    map_user,
)
from tawos_importer.source_db import tawos_connection
from tawos_importer.tawos_queries import (
    fetch_blocking_links,
    fetch_issue_sprint_history,
    fetch_issues,
    fetch_project,
    fetch_project_by_key,
    fetch_sprints,
    fetch_users_for_project,
)

log = setup_logging()

TICKET_BATCH_SIZE = 500


@dataclass
class ImportSummary:
    """One-shot result returned by import_project for callers/logging."""
    project_name: str
    organization_id: uuid.UUID
    team_id: uuid.UUID
    developers: int = 0
    sprints: int = 0
    sprints_skipped: int = 0
    tickets: int = 0
    sprint_tickets: int = 0
    dependencies: int = 0
    warnings: list[str] = field(default_factory=list)

    def as_log_line(self) -> str:
        return (
            f"[tawos] Imported {self.project_name}: "
            f"{self.developers} developers, "
            f"{self.sprints} sprints ({self.sprints_skipped} skipped), "
            f"{self.tickets} tickets, "
            f"{self.dependencies} dependencies"
        )


async def import_project(
    project_identifier: int | str,
    limit_issues: int | None = None,
) -> ImportSummary:
    """Import one project. `project_identifier` is either TAWOS Project.ID
    (int) or Project.Key (str like 'APACHE-KAFKA').

    Opens its own AsyncSessionLocal and wraps all writes in a single tx.
    """
    with tawos_connection() as mysql_conn:
        project_row = (
            fetch_project(mysql_conn, project_identifier)
            if isinstance(project_identifier, int)
            else fetch_project_by_key(mysql_conn, project_identifier)
        )
        if not project_row:
            raise ValueError(f"TAWOS project not found: {project_identifier!r}")

        project_pk = int(project_row["ID"])
        log.info("fetching users for project %s", project_pk)
        user_rows = fetch_users_for_project(mysql_conn, project_pk)
        log.info("fetching sprints for project %s", project_pk)
        sprint_rows = fetch_sprints(mysql_conn, project_pk)
        log.info("fetching issues for project %s (limit=%s)", project_pk, limit_issues)
        issue_rows = fetch_issues(mysql_conn, project_pk, limit=limit_issues)

        issue_ids = [int(r["ID"]) for r in issue_rows]
        log.info("fetching blocking links among %d issues", len(issue_ids))
        link_rows = fetch_blocking_links(mysql_conn, issue_ids)
        sprint_history = fetch_issue_sprint_history(mysql_conn, issue_ids)

    async with AsyncSessionLocal() as session:
        try:
            summary = await _do_import(
                session,
                project_row=project_row,
                user_rows=user_rows,
                sprint_rows=sprint_rows,
                issue_rows=issue_rows,
                link_rows=link_rows,
                sprint_history=sprint_history,
            )
            await session.commit()
        except Exception:
            await session.rollback()
            log.exception("import failed, rolling back")
            raise

    log.info(summary.as_log_line())
    for w in summary.warnings[:20]:
        log.warning("  %s", w)
    if len(summary.warnings) > 20:
        log.warning("  ... and %d more warnings", len(summary.warnings) - 20)
    return summary


async def _do_import(
    session: AsyncSession,
    *,
    project_row: dict[str, Any],
    user_rows: list[dict[str, Any]],
    sprint_rows: list[dict[str, Any]],
    issue_rows: list[dict[str, Any]],
    link_rows: list[dict[str, Any]],
    sprint_history: dict[int, list[int]],
) -> ImportSummary:
    warnings: list[str] = []

    # -------- 1. Organization + Team ---------------------------------- #
    mp = map_project(project_row)
    session.add(mp.organization)
    await session.flush()
    mp.team.organization_id = mp.organization.id
    session.add(mp.team)
    await session.flush()
    team_id = mp.team.id

    summary = ImportSummary(
        project_name=mp.team.name,
        organization_id=mp.organization.id,
        team_id=team_id,
    )

    # -------- 2. Developers + TeamMembers ----------------------------- #
    # Track (tawos_user_id, dev, member) triples so we can build lookups
    # after a single flush instead of re-mapping.
    user_triples: list[tuple[str, Any, Any]] = []
    for user_row in user_rows:
        dev, member = map_user(user_row)
        dev.team_id = team_id
        member.team_id = team_id
        session.add(dev)
        session.add(member)
        user_triples.append((str(user_row["ID"]), dev, member))
    await session.flush()

    member_lookup: dict[str, uuid.UUID] = {tid: m.id for tid, _, m in user_triples}
    dev_lookup: dict[str, uuid.UUID] = {tid: d.id for tid, d, _ in user_triples}
    summary.developers = len(user_triples)

    # -------- 3. Sprints --------------------------------------------- #
    sprint_to_id: dict[str, uuid.UUID] = {}
    sprint_objects: dict[str, Sprint] = {}
    sprint_start_by_sprint_id: dict[uuid.UUID, date | None] = {}

    for sprint_row in sprint_rows:
        sprint_obj = map_sprint(sprint_row)
        if sprint_obj is None:
            warnings.append(f"skipped sprint {sprint_row.get('Name')!r}: end_date < start_date")
            summary.sprints_skipped += 1
            continue
        sprint_obj.team_id = team_id
        session.add(sprint_obj)
        sprint_objects[str(sprint_row["ID"])] = sprint_obj

    await session.flush()
    for tid, sobj in sprint_objects.items():
        sprint_to_id[tid] = sobj.id
        sprint_start_by_sprint_id[sobj.id] = sobj.start_date
    summary.sprints = len(sprint_to_id)

    # -------- 4. Tickets (batched) ------------------------------------ #
    tickets_by_sprint: dict[uuid.UUID, list[Ticket]] = defaultdict(list)
    # (ticket, tawos_assignee_id_str) pairs so we can build SprintTicket rows later.
    ticket_for_sprint_ticket: list[tuple[Ticket, str | None]] = []

    multi_sprint_issue_ids = {
        iid for iid, sids in sprint_history.items() if len(set(sids)) > 1
    }
    if sprint_history:
        log.info("sprint history available — %d issues flagged as carryover",
                 len(multi_sprint_issue_ids))
    else:
        log.info("no Sprint_Issue history table — is_carryover defaults to FALSE")

    batch: list[Ticket] = []
    for issue_row in issue_rows:
        ticket = map_issue(issue_row, sprint_to_id, member_lookup, warnings)
        ticket.team_id = team_id
        if int(issue_row["ID"]) in multi_sprint_issue_ids:
            ticket.is_carryover = True
        batch.append(ticket)

        if ticket.sprint_id is not None:
            tickets_by_sprint[ticket.sprint_id].append(ticket)

        raw_assignee = issue_row.get("Assignee_ID")
        ticket_for_sprint_ticket.append(
            (ticket, str(raw_assignee) if raw_assignee is not None else None)
        )

        if len(batch) >= TICKET_BATCH_SIZE:
            session.add_all(batch)
            await session.flush()
            batch.clear()

    if batch:
        session.add_all(batch)
        await session.flush()
    summary.tickets = len(ticket_for_sprint_ticket)

    # -------- 5. SprintTicket rows (sprint → developer attribution) --- #
    # SprintTicket.assignee_id is FK to developers.id (not team_members.id),
    # so use dev_lookup. Rows without a sprint or assignee are skipped —
    # SprintTicket.sprint_id is NOT NULL.
    sprint_ticket_rows: list[SprintTicket] = []
    for ticket, tawos_assignee_id in ticket_for_sprint_ticket:
        if ticket.sprint_id is None:
            continue
        assignee_dev_id = dev_lookup.get(tawos_assignee_id) if tawos_assignee_id else None
        sprint_ticket_rows.append(
            SprintTicket(
                sprint_id=ticket.sprint_id,
                ticket_id=str(ticket.jira_issue_key or ticket.jira_issue_id),
                assignee_id=assignee_dev_id,
                estimated_points=ticket.story_points_estimated,
                actual_points=ticket.story_points_estimated
                    if ticket.status == TicketStatus.DONE else None,
                completed=ticket.status == TicketStatus.DONE,
            )
        )
    if sprint_ticket_rows:
        session.add_all(sprint_ticket_rows)
        await session.flush()
    summary.sprint_tickets = len(sprint_ticket_rows)

    # -------- 6. Dependencies ---------------------------------------- #
    # Build a ticket-key → Sprint lookup so map_link_risk has the blocked
    # ticket's sprint_start (the rule hinges on that date).
    key_to_sprint_start: dict[str, date | None] = {}
    for ticket, _ in ticket_for_sprint_ticket:
        if ticket.jira_issue_key and ticket.sprint_id is not None:
            key_to_sprint_start[ticket.jira_issue_key] = \
                sprint_start_by_sprint_id.get(ticket.sprint_id)

    dep_count = 0
    for link_row in link_rows:
        mapped = map_link(
            link_row=link_row,
            link_type_name=link_row.get("Link_Type_Name"),
            source_ticket_key=link_row.get("Source_Key"),
            target_ticket_key=link_row.get("Target_Key"),
            blocker_resolved=link_row.get("Source_Resolved"),
            blocker_sprint_end=None,
            blocked_sprint_start=key_to_sprint_start.get(
                str(link_row.get("Target_Key")) if link_row.get("Target_Key") else ""
            ),
        )
        if mapped is None:
            continue
        session.add(build_dependency(
            mapped,
            team_id=team_id,
            ticket_title=link_row.get("Target_Title"),
        ))
        dep_count += 1
    await session.flush()
    summary.dependencies = dep_count

    # -------- 7. Derived: Sprint committed/delivered points ---------- #
    # Iterate over the Sprint objects directly (we have them in sprint_objects)
    # rather than doing a reverse lookup.
    id_to_sprint_obj: dict[uuid.UUID, Sprint] = {s.id: s for s in sprint_objects.values()}
    for sprint_id, tix in tickets_by_sprint.items():
        sobj = id_to_sprint_obj.get(sprint_id)
        if sobj is None:
            continue
        committed, delivered = compute_sprint_points(tix)
        sobj.committed_points = committed
        sobj.delivered_points = delivered
    await session.flush()

    summary.warnings = warnings
    return summary
