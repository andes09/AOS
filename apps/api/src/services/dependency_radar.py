"""
Dependency Radar service.

scan_jira_dependencies() — fetches Jira issue links for all non-completed
tickets belonging to a team, maps them to Dependency rows, upserts to DB,
and marks stale Jira deps as resolved.

compute_team_risk_score() — weighted sum (high=3, medium=2, low=1) of active
deps, normalised to 0–100 with a ceiling of 10 high-risk deps (raw=30).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.dependency_radar import Dependency, DependencyType, RiskLevel
from src.models.ticket import Ticket, TicketStatus

logger = logging.getLogger(__name__)

# Jira link type names that carry explicit block semantics.
_BLOCKS_TYPE = "Blocks"


@dataclass
class ScanResult:
    scanned_at: datetime
    dependencies_found: int
    risk_score: int


def _project_prefix(issue_key: str) -> str:
    """Return the project key portion of a Jira issue key, e.g. 'PROJ' from 'PROJ-123'."""
    return issue_key.split("-")[0] if "-" in issue_key else issue_key


def _classify_link(
    link: dict,
    team_project_key: str | None,
) -> tuple[DependencyType, RiskLevel, str | None] | None:
    """
    Map one Jira issuelink dict to (DependencyType, RiskLevel, blocked_by_key).

    Returns None if the link should be skipped.
    """
    link_type: str = link.get("type", "")
    inward = link.get("inwardIssue")
    outward = link.get("outwardIssue")

    if link_type == _BLOCKS_TYPE:
        if inward:
            # Another issue is blocking this one → IS_BLOCKED_BY
            return DependencyType.IS_BLOCKED_BY, RiskLevel.HIGH, inward.get("key")
        if outward:
            # This issue blocks another → BLOCKS
            return DependencyType.BLOCKS, RiskLevel.LOW, outward.get("key")
        return None

    # For non-"Blocks" link types, classify by project membership.
    linked_key = (inward or outward or {}).get("key")
    if not linked_key:
        return None

    if team_project_key and _project_prefix(linked_key) != team_project_key:
        return DependencyType.CROSS_TEAM, RiskLevel.MEDIUM, linked_key

    # Same project, non-block link type → treat as external service dependency.
    return DependencyType.EXTERNAL_SERVICE, RiskLevel.MEDIUM, linked_key


async def scan_jira_dependencies(
    team_id: str,
    jira_client,
    db: AsyncSession,
) -> ScanResult:
    """
    Scan Jira issue links for all non-completed tickets in the team.

    1. Load non-completed tickets from DB.
    2. Call jira_client.get_issue_links() for each ticket with a jira_issue_key.
    3. Map link types to DependencyType + RiskLevel.
    4. Upsert results to `dependencies` table with source='jira'.
    5. Mark previously-active Jira deps that no longer appear as resolved.
    6. Return ScanResult.
    """
    team_uuid = uuid.UUID(team_id) if isinstance(team_id, str) else team_id

    # --- 1. Load non-completed tickets -----------------------------------------
    result = await db.execute(
        select(Ticket).where(
            Ticket.team_id == team_uuid,
            Ticket.status.not_in([TicketStatus.DONE, TicketStatus.CANCELLED]),
        )
    )
    tickets = result.scalars().all()

    # Determine the team's primary Jira project key for cross-team detection.
    team_project_key: str | None = None
    if tickets:
        for t in tickets:
            if t.jira_issue_key:
                team_project_key = _project_prefix(t.jira_issue_key)
                break

    # --- 2. Fetch links from Jira and build new dep fingerprints ----------------
    # fingerprint: (ticket_key, blocked_by_key, dependency_type_value)
    new_deps: list[dict] = []  # each entry maps to one Dependency row

    for ticket in tickets:
        key = ticket.jira_issue_key
        if not key:
            continue
        try:
            links = await jira_client.get_issue_links(key)
        except Exception as exc:
            logger.warning("get_issue_links(%s) failed: %s", key, exc)
            continue

        for link in links:
            classified = _classify_link(link, team_project_key)
            if classified is None:
                continue
            dep_type, risk_level, linked_key = classified
            new_deps.append({
                "ticket_key": key,
                "ticket_title": ticket.title,
                "blocked_by_key": linked_key,
                "dependency_type": dep_type.value,
                "risk_level": risk_level.value,
            })

    # --- 3. Load existing Jira deps for this team --------------------------------
    existing_result = await db.execute(
        select(Dependency).where(
            Dependency.team_id == team_uuid,
            Dependency.source == "jira",
        )
    )
    existing: list[Dependency] = existing_result.scalars().all()

    # Build a lookup: fingerprint → existing row
    existing_map: dict[tuple, Dependency] = {
        (d.ticket_key, d.blocked_by_key, d.dependency_type): d
        for d in existing
    }

    # --- 4. Upsert new deps ------------------------------------------------------
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    seen_fingerprints: set[tuple] = set()

    for nd in new_deps:
        fp = (nd["ticket_key"], nd["blocked_by_key"], nd["dependency_type"])
        seen_fingerprints.add(fp)
        if fp in existing_map:
            row = existing_map[fp]
            # Re-open if it was previously resolved.
            if row.resolved_at is not None:
                row.resolved_at = None
                row.risk_level = nd["risk_level"]
        else:
            dep = Dependency(
                team_id=team_uuid,
                ticket_key=nd["ticket_key"],
                ticket_title=nd["ticket_title"],
                blocked_by_key=nd["blocked_by_key"],
                dependency_type=nd["dependency_type"],
                risk_level=nd["risk_level"],
                source="jira",
            )
            db.add(dep)

    # --- 5. Mark stale Jira deps as resolved -------------------------------------
    for fp, row in existing_map.items():
        if fp not in seen_fingerprints and row.resolved_at is None:
            row.resolved_at = now

    await db.flush()

    # --- 6. Reload to get accurate active count for risk score -------------------
    active_result = await db.execute(
        select(Dependency).where(
            Dependency.team_id == team_uuid,
            Dependency.resolved_at.is_(None),
        )
    )
    active_deps = active_result.scalars().all()

    return ScanResult(
        scanned_at=now,
        dependencies_found=len(new_deps),
        risk_score=compute_team_risk_score(active_deps),
    )


def compute_team_risk_score(deps: list[Dependency]) -> int:
    """
    Weighted sum of active (unresolved) dependencies, normalised to 0–100.

    high=3, medium=2, low=1.
    Denominator=30 → 10 high-risk deps → score 100. Capped at 100.
    """
    raw = sum(
        3 if d.risk_level == RiskLevel.HIGH.value else
        2 if d.risk_level == RiskLevel.MEDIUM.value else
        1
        for d in deps
        if d.resolved_at is None
    )
    return min(100, round(raw * 100 / 30))
