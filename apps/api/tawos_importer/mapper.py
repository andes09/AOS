"""Pure mapping functions: TAWOS row dicts → Omada SQLAlchemy model instances.

These functions never touch a DB — they take plain dicts (as returned by
DictCursor) and return unpersisted SQLAlchemy objects. That keeps the mapping
logic unit-testable and keeps `importer.py` focused on transaction management.

TAWOS schema anchor points (v1.1, from the SOLAR-group paper and `inspect.py`
output — re-verify against actual column names in your dump):

  Project(ID, Name, Key, ...)
  Issue(ID, Project_ID, Jira_ID, Key, Title, Type, Status, Story_Point,
        Assignee_ID, Reporter_ID, Sprint_ID, Created_Date, Resolution_Date,
        Last_Updated)
  Sprint(ID, Project_ID, Name, Start_Date, End_Date, Complete_Date, State)
  User(ID, Username, Full_Name)        -- column names vary; mapper is tolerant
  Issue_Link(ID, Source_Issue_ID, Target_Issue_ID, Link_Type_ID)
  Link_Type(ID, Name, Inward_Description, Outward_Description)

Field name variations are handled via `_pick()` which tries a tuple of
candidate keys and returns the first non-None value.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable

from src.models import (
    Dependency,
    Developer,
    Organization,
    Sprint,
    SprintStatus,
    Team,
    TeamMember,
    Ticket,
    TicketStatus,
)
from src.models.dependency_radar import DependencyType, RiskLevel

# --------------------------------------------------------------------------- #
# Small utilities
# --------------------------------------------------------------------------- #

MAX_TITLE_LEN = 500           # spec: titles over 500 chars → truncate + warn
TICKET_DESCRIPTION_MAX = 5000  # spec: description truncation budget (unused — no Ticket.description)


def _pick(row: dict[str, Any], *keys: str) -> Any:
    """Return row[k] for the first k that exists AND has a non-None value."""
    for k in keys:
        if k in row and row[k] is not None:
            return row[k]
    return None


def _slugify(name: str) -> str:
    """Lowercase alnum + dashes. Used for Organization.slug uniqueness."""
    s = re.sub(r"[^a-zA-Z0-9]+", "-", name.lower()).strip("-")
    return s or f"tawos-{uuid.uuid4().hex[:8]}"


def _truncate(s: str | None, n: int, warnings: list[str], label: str) -> str | None:
    if s is None:
        return None
    if len(s) <= n:
        return s
    warnings.append(f"{label} truncated from {len(s)} to {n} chars")
    return s[:n]


def _to_date(v: Any) -> date | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return None


def _to_datetime(v: Any) -> datetime | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day)
    return None


# --------------------------------------------------------------------------- #
# Enum mappings
# --------------------------------------------------------------------------- #

# TAWOS sprint states vary in case/spelling across projects. Normalise.
_SPRINT_STATE_MAP = {
    "CLOSED": SprintStatus.COMPLETED,
    "COMPLETE": SprintStatus.COMPLETED,
    "COMPLETED": SprintStatus.COMPLETED,
    "ACTIVE": SprintStatus.ACTIVE,
    "IN_PROGRESS": SprintStatus.ACTIVE,
    "FUTURE": SprintStatus.PLANNING,
    "PLANNING": SprintStatus.PLANNING,
    "CANCELLED": SprintStatus.CANCELLED,
    "CANCELED": SprintStatus.CANCELLED,
}


def map_sprint_status(raw: str | None) -> SprintStatus:
    if not raw:
        return SprintStatus.PLANNING
    return _SPRINT_STATE_MAP.get(raw.strip().upper(), SprintStatus.PLANNING)


# TAWOS status is a free-form string per project. Normalise to the small set
# Omada cares about. Anything that doesn't match a known "done" pattern goes
# to TODO so velocity calculations don't accidentally count half-done work.
_DONE_TOKENS = {"done", "closed", "resolved", "fixed", "complete", "completed"}
_IN_PROGRESS_TOKENS = {"in progress", "in-progress", "inprogress", "started", "implementing"}
_IN_REVIEW_TOKENS = {"review", "code review", "in review", "pr open"}
_CANCELLED_TOKENS = {"cancelled", "canceled", "won't do", "wont do", "invalid", "duplicate"}


def map_ticket_status(raw: str | None) -> TicketStatus:
    if not raw:
        return TicketStatus.TODO
    lower = raw.strip().lower()
    if lower in _CANCELLED_TOKENS:
        return TicketStatus.CANCELLED
    if lower in _DONE_TOKENS:
        return TicketStatus.DONE
    if lower in _IN_REVIEW_TOKENS:
        return TicketStatus.IN_REVIEW
    if lower in _IN_PROGRESS_TOKENS:
        return TicketStatus.IN_PROGRESS
    return TicketStatus.TODO


_TICKET_TYPE_PASSTHROUGH = {"Story", "Bug", "Task", "Epic", "Sub-task", "Improvement"}


def map_ticket_type(raw: str | None) -> str | None:
    """Normalise to title-case, pass through. Unknown types preserved verbatim."""
    if not raw:
        return None
    t = raw.strip()
    # Case-insensitive match against known set first.
    for known in _TICKET_TYPE_PASSTHROUGH:
        if t.lower() == known.lower():
            return known
    return t


# --------------------------------------------------------------------------- #
# Mapping functions
# --------------------------------------------------------------------------- #

@dataclass
class MappedProject:
    """Result of map_project — keeps organization and team together."""
    organization: Organization
    team: Team


def map_project(row: dict[str, Any]) -> MappedProject:
    """TAWOS Project → Omada Organization + Team.

    is_simulated=TRUE and the "[TAWOS]" prefix make these orgs trivially
    identifiable (for --reset and so real-user views never accidentally include them).
    """
    raw_name = str(_pick(row, "Name", "name") or f"project-{row.get('ID', '?')}")
    raw_key = _pick(row, "Key", "key", "Project_Key") or raw_name

    org = Organization(
        clerk_org_id=f"tawos_{_slugify(raw_key)}_{uuid.uuid4().hex[:8]}",
        name=f"[TAWOS] {raw_name}",
        slug=f"tawos-{_slugify(raw_key)}-{uuid.uuid4().hex[:6]}",
        is_simulated=True,
    )
    team = Team(
        name=raw_name,
        jira_project_key=str(raw_key)[:100],
        sprint_length_days=14,
    )
    return MappedProject(organization=org, team=team)


def map_user(row: dict[str, Any]) -> tuple[Developer, TeamMember]:
    """TAWOS User → (Developer, TeamMember) pair, linked by display_name.

    Omada uses separate models for "app user with login" (Developer) and
    "Jira-sourced identity that can be assigned to a ticket" (TeamMember).
    The importer creates both so:
      - velocity / capacity features work (Developer)
      - Ticket.assignee_id resolves (TeamMember.id is the FK target)

    The two are linked via identical display_name + a shared tawos_account_id
    prefix, so resolution is O(1) via a lookup dict in the importer.

    The shipped TAWOS dump anonymizes users completely — the User table has
    only (ID, Project_ID). We synthesize `user_<ID>` as the handle so every
    assignee remains distinct and stable across re-imports. Earlier dataset
    versions carried Username/Full_Name columns, so the code still prefers
    real values when present.
    """
    tawos_id = row.get("ID")
    username_fallback = f"user_{tawos_id}" if tawos_id is not None else f"user_{uuid.uuid4().hex[:8]}"
    username = str(_pick(row, "Username", "username", "Name", "name") or username_fallback)
    full_name = str(_pick(row, "Full_Name", "full_name", "Display_Name") or username)
    account_id = f"tawos_{username.lower()}"

    dev = Developer(
        clerk_user_id=account_id,                      # fake Clerk ID — unique, recognisable
        name=full_name,
        email=f"{_slugify(username)}@tawos-import.local",
        app_role="developer",
        is_active=True,
    )
    member = TeamMember(
        jira_account_id=account_id,
        display_name=full_name,
        email=f"{_slugify(username)}@tawos-import.local",
    )
    return dev, member


def map_sprint(row: dict[str, Any]) -> Sprint | None:
    """TAWOS Sprint → Omada Sprint, or None if the row is unusable.

    Returns None for sprints where end_date < start_date (source-data errors).
    Caller logs a warning with the sprint name.
    """
    start = _to_date(_pick(row, "Start_Date", "start_date", "StartDate"))
    end = _to_date(_pick(row, "End_Date", "end_date", "EndDate", "Complete_Date"))

    if start and end and end < start:
        return None  # caller logs

    return Sprint(
        jira_sprint_id=str(_pick(row, "ID", "id") or ""),
        name=str(_pick(row, "Name", "name") or f"sprint-{row.get('ID', '?')}")[:255],
        start_date=start,
        end_date=end,
        status=map_sprint_status(_pick(row, "State", "state", "Status")),
    )


def map_issue(
    row: dict[str, Any],
    sprint_lookup: dict[str, uuid.UUID],
    member_lookup: dict[str, uuid.UUID],
    warnings: list[str],
) -> Ticket:
    """TAWOS Issue → Omada Ticket.

    `sprint_lookup`: TAWOS sprint ID (str) → Omada Sprint.id
    `member_lookup`: TAWOS user account_id (str) → Omada TeamMember.id

    Unknown assignees (e.g. unassigned tickets or reporters-only in an earlier
    sprint whose username vanished) resolve to None without raising.
    """
    # `tickets.jira_issue_id` has a global UNIQUE constraint, but TAWOS Jira_ID
    # values are only unique within one source Jira instance — across the 39
    # TAWOS projects (sourced from different Jiras: Apache, Atlassian,
    # Hyperledger, etc.) numeric Jira_IDs collide freely. TAWOS Issue.ID is the
    # TAWOS-internal PK and is globally unique, so we use it with a "tawos_"
    # prefix to guarantee uniqueness and mark provenance.
    tawos_pk = _pick(row, "ID", "id")
    jira_id = f"tawos_{tawos_pk}"
    jira_key = _pick(row, "Issue_Key", "Key", "key")

    title = _pick(row, "Title", "title", "Summary", "summary") or f"(no title) {jira_key or jira_id}"
    title = _truncate(str(title), MAX_TITLE_LEN, warnings, f"title {jira_key or jira_id}")

    story_points_raw = _pick(row, "Story_Point", "story_point", "Story_Points")
    story_points = float(story_points_raw) if story_points_raw is not None else None

    raw_sprint_id = _pick(row, "Sprint_ID", "sprint_id")
    sprint_id = sprint_lookup.get(str(raw_sprint_id)) if raw_sprint_id is not None else None

    raw_assignee = _pick(row, "Assignee_ID", "assignee_id")
    assignee_id = member_lookup.get(str(raw_assignee)) if raw_assignee is not None else None

    created = _to_datetime(_pick(row, "Creation_Date", "Created_Date", "created_date", "Created", "created_at"))
    resolved = _to_datetime(_pick(row, "Resolution_Date", "resolution_date", "Resolved"))
    updated = _to_datetime(_pick(row, "Last_Updated", "last_updated", "Updated"))

    return Ticket(
        jira_issue_id=jira_id,
        jira_issue_key=str(jira_key)[:50] if jira_key else None,
        title=title,
        status=map_ticket_status(_pick(row, "Status", "status")),
        ticket_type=map_ticket_type(_pick(row, "Type", "type", "Issue_Type")),
        story_points_estimated=story_points,
        sprint_id=sprint_id,
        assignee_id=assignee_id,
        created_at=created or datetime.utcnow(),
        completed_at=resolved,
        jira_updated_at=updated,
        is_carryover=False,  # populated in a second pass — depends on sprint history
    )


@dataclass
class MappedLink:
    ticket_key: str            # the blocked ticket (inward in Jira terms)
    blocked_by_key: str        # the blocking ticket (outward)
    dependency_type: str
    risk_level: str


_BLOCK_LINK_NAMES = {"blocks", "is blocked by", "is-blocked-by", "block", "blocked by"}


def is_block_link(link_type_name: str | None) -> bool:
    if not link_type_name:
        return False
    return link_type_name.strip().lower() in _BLOCK_LINK_NAMES


STALE_BLOCKER_AGE_DAYS = 60


def map_link_risk(
    blocker_resolved: datetime | None,
    blocker_sprint_end: date | None,
    blocked_sprint_start: date | None,
    blocker_created_at: datetime | None = None,
    blocker_is_done: bool = False,
) -> RiskLevel:
    """Classify dependency risk.

    LOW:
      - blocker resolved before the blocked ticket's sprint started.

    HIGH (two independent triggers — either one promotes the dep to HIGH):
      - sprint-based: blocker has slipped past its own sprint end (either
        still unresolved past that date, or resolved after it)
      - staleness-based: blocker is not done AND was created more than
        `STALE_BLOCKER_AGE_DAYS` before the blocked ticket's sprint_start
        (or before today if the blocked ticket has no sprint). This catches
        the common TAWOS/Jira pattern where the blocker is a long-lived
        backlog ticket that was never scheduled — the sprint-based trigger
        can't fire in that case because the blocker has no sprint_end.

    MEDIUM: everything else.
    """
    if blocker_resolved and blocked_sprint_start and blocker_resolved.date() <= blocked_sprint_start:
        return RiskLevel.LOW

    # HIGH branch 1 — sprint-based
    if blocker_sprint_end and not blocker_resolved and blocker_sprint_end < date.today():
        return RiskLevel.HIGH
    if (
        blocker_sprint_end
        and blocker_resolved
        and blocker_resolved.date() > blocker_sprint_end
    ):
        return RiskLevel.HIGH

    # HIGH branch 2 — staleness-based
    if not blocker_is_done and blocker_created_at:
        reference = blocked_sprint_start or date.today()
        age_days = (reference - blocker_created_at.date()).days
        if age_days > STALE_BLOCKER_AGE_DAYS:
            return RiskLevel.HIGH

    return RiskLevel.MEDIUM


def map_link(
    link_row: dict[str, Any],
    source_sprint_start: date | None,
    target_sprint_start: date | None,
    source_sprint_end: date | None,
    target_sprint_end: date | None,
) -> MappedLink | None:
    """TAWOS Issue_Link → Omada Dependency (or None if not a blocking link).

    Issue_Link in the shipped TAWOS dump stores, for each link, one row per
    side (e.g. {Name='Blocks', Description='is blocked by', Direction='INBOUND'}
    and a matching {Description='blocks', Direction='OUTBOUND'} row). The
    description text is authoritative about which end blocks which — we read
    it directly and let the importer dedupe by (blocked, blocker).

    `Issue_ID` is the viewer of the link (Source_Key); `Target_Issue_ID` is
    the other end (Target_Key).

    For risk classification we need the BLOCKER's sprint_end and the BLOCKED
    ticket's sprint_start. Which side is which flips based on the description
    text — we pick the right pair below.
    """
    name = (link_row.get("Link_Name") or "").strip().lower()
    desc = (link_row.get("Link_Description") or "").strip().lower()

    if "block" not in name and "block" not in desc:
        return None

    source_key = link_row.get("Source_Key")   # = Issue_ID's jira key
    target_key = link_row.get("Target_Key")   # = Target_Issue_ID's jira key
    if not source_key or not target_key:
        return None

    # Description describes Issue_ID's relationship to Target_Issue_ID.
    #   "is blocked by" → source is blocked, target is blocker
    #   "blocks"        → source blocks, target is blocked
    if "blocked by" in desc or "is blocked" in desc:
        blocked_key, blocker_key = source_key, target_key
        blocker_resolved = _to_datetime(link_row.get("Target_Resolved"))
        blocked_sprint_start = source_sprint_start
        blocker_sprint_end = target_sprint_end
        blocker_created_at = _to_datetime(link_row.get("Target_Created"))
        blocker_status_raw = link_row.get("Target_Status")
    else:
        blocked_key, blocker_key = target_key, source_key
        blocker_resolved = _to_datetime(link_row.get("Source_Resolved"))
        blocked_sprint_start = target_sprint_start
        blocker_sprint_end = source_sprint_end
        blocker_created_at = _to_datetime(link_row.get("Source_Created"))
        blocker_status_raw = link_row.get("Source_Status")

    blocker_is_done = map_ticket_status(blocker_status_raw) == TicketStatus.DONE
    risk = map_link_risk(
        blocker_resolved,
        blocker_sprint_end,
        blocked_sprint_start,
        blocker_created_at=blocker_created_at,
        blocker_is_done=blocker_is_done,
    )

    return MappedLink(
        ticket_key=str(blocked_key)[:50],
        blocked_by_key=str(blocker_key)[:50],
        dependency_type=DependencyType.BLOCKS.value,
        risk_level=risk.value,
    )


def build_dependency(mapped: MappedLink, team_id: uuid.UUID, ticket_title: str | None) -> Dependency:
    """Turn a MappedLink into a persistable Dependency row."""
    return Dependency(
        team_id=team_id,
        ticket_key=mapped.ticket_key,
        ticket_title=ticket_title,
        blocked_by_key=mapped.blocked_by_key,
        dependency_type=mapped.dependency_type,
        risk_level=mapped.risk_level,
        description=None,
        source="tawos",
    )


# --------------------------------------------------------------------------- #
# Derived-field computation (called after bulk insert, before commit)
# --------------------------------------------------------------------------- #

def compute_sprint_points(tickets_in_sprint: Iterable[Ticket]) -> tuple[float, float]:
    """Return (committed, delivered) = (sum of all SP, sum of Done SP).

    Called once per sprint after tickets are persisted. Skips None SP tickets
    so committed/delivered aren't polluted by unsized work.
    """
    committed = 0.0
    delivered = 0.0
    for t in tickets_in_sprint:
        sp = t.story_points_estimated
        if sp is None:
            continue
        committed += sp
        if t.status == TicketStatus.DONE:
            delivered += sp
    return committed, delivered


def compute_baseline_velocity(delivered_per_sprint: list[float]) -> float | None:
    """Mean delivered SP per sprint, ignoring sprints with zero delivery.

    Returns None if the developer never delivered anything — caller decides
    whether to still create a velocity profile row.
    """
    nonzero = [x for x in delivered_per_sprint if x > 0]
    if not nonzero:
        return None
    return sum(nonzero) / len(nonzero)
