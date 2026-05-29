"""
Sprint Brain AI service — Claude Opus 4.7 powered sprint planning.

Implements generate_sprint_plan() and simulate_what_if() using the Anthropic
API with adaptive thinking and tool_use for structured output.

BYOK model: the Anthropic API key is always supplied by the caller (fetched
from the Organisation record), never from environment.
"""

import logging
import uuid
from dataclasses import dataclass, field

import anthropic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.developer import Developer
from src.models.team import Team
from src.models.sprint import Sprint, SprintStatus
from src.models.capacity import DeveloperCapacityOverride
from src.models.ticket import Ticket, TicketStatus
from src.models.identifier import TicketSkillAnalysis
from src.models.sprint_plan_override import SprintPlanOverride
from src.services.cost_tracker import record_generation_cost

logger = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-6"

# ---------------------------------------------------------------------------
# Tool schema — forces Claude to return structured sprint plan output
# ---------------------------------------------------------------------------

_SPRINT_PLAN_TOOL: dict = {
    "name": "create_sprint_plan",
    "description": (
        "Output a structured sprint plan with per-ticket assignments, confidence "
        "scores, risk warnings, and what-if analysis."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "assignments": {
                "type": "array",
                "description": "Ordered list of ticket-to-developer assignments for this sprint.",
                "items": {
                    "type": "object",
                    "properties": {
                        "ticket_id": {"type": "string"},
                        "developer_id": {"type": "string"},
                        "reasoning": {
                            "type": "string",
                            "description": "Why this ticket was assigned to this developer.",
                        },
                        "confidence": {
                            "type": "number",
                            "description": "0.0–1.0 confidence for this specific assignment.",
                        },
                        "story_points": {"type": "number"},
                        "skill_match_reasoning": {
                            "type": "string",
                            "description": (
                                "One sentence: which skill(s) drove this dev choice and what "
                                "rating(s) supported it. Use 'capacity_only' if no skill signal."
                            ),
                        },
                    },
                    "required": [
                        "ticket_id",
                        "developer_id",
                        "reasoning",
                        "confidence",
                        "skill_match_reasoning",
                    ],
                    "additionalProperties": False,
                },
            },
            "confidence_score": {
                "type": "number",
                "description": (
                    "Overall sprint confidence 0.0–1.0. "
                    "≥0.8 is healthy; <0.6 is risky."
                ),
            },
            "summary": {
                "type": "string",
                "description": "2–3 sentence natural-language summary of the plan and key reasoning.",
            },
            "warnings": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Risk flags to surface to the user, e.g. overloaded developer, "
                    "missing skill coverage, high-uncertainty estimates."
                ),
            },
            "what_if_dropped": {
                "type": "object",
                "description": (
                    "For each assigned ticket_id, the new overall sprint confidence "
                    "if that ticket were removed from the plan."
                ),
                "additionalProperties": {"type": "number"},
            },
        },
        "required": [
            "assignments",
            "confidence_score",
            "summary",
            "warnings",
            "what_if_dropped",
        ],
        "additionalProperties": False,
    },
}

_COMPLEXITY_TOOL: dict = {
    "name": "analyse_tickets",
    "description": (
        "Analyse a list of tickets and return a complexity estimate for each one. "
        "Focus purely on the work itself — do not consider developer availability."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "ticket_analyses": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "ticket_id": {"type": "string"},
                        "effort": {
                            "type": "string",
                            "enum": ["low", "medium", "high"],
                            "description": "Overall implementation effort.",
                        },
                        "required_skills": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "Technical skills needed, e.g. ['backend', 'sql', 'api-design']. "
                                "Use domain names from: frontend, backend, infra. "
                                "Add specifics as extra tags."
                            ),
                        },
                        "complexity_notes": {
                            "type": "string",
                            "description": "One sentence explaining the main complexity driver.",
                        },
                        "estimated_days": {
                            "type": "number",
                            "description": "Estimated calendar days for a mid-level engineer.",
                        },
                    },
                    "required": ["ticket_id", "effort", "required_skills", "complexity_notes", "estimated_days"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["ticket_analyses"],
        "additionalProperties": False,
    },
}

_COMPLEXITY_SYSTEM_PROMPT = """\
You are a senior software engineer estimating implementation effort for sprint tickets.

For each ticket, assess:
1. Effort level: low (< 1 day), medium (1–3 days), high (3+ days)
2. Required skills: use domain terms (frontend, backend, infra) plus specific tags
3. Complexity notes: one sentence on the main driver of complexity
4. Estimated days: your best estimate for a mid-level engineer

Focus purely on the work. Ignore team composition and availability.
Always respond by calling the analyse_tickets tool.\
"""

_SYSTEM_PROMPT = """\
You are an expert agile sprint planning assistant with deep expertise in \
software engineering team dynamics and velocity-based capacity planning.

Your responsibilities:
1. Assign tickets to developers based on their velocity profiles, historical \
   performance, and skill fit.
2. Respect each developer's safe capacity — never overload.
3. Prioritise high-value, unblocked tickets first.
4. Surface risks proactively: overloaded developers, skill gaps, low-data \
   estimates, sequential dependencies.
5. Be conservative. A sprint with 80 % confidence is far better than one \
   that looks full on paper but will slip.
6. For EVERY assignment, include in your reasoning a direct citation of \
   the historical velocity data you used. \
   Example: "Based on 4 backend/bug sprints averaging 8.2 pts, this fits \
   within Alice's safe capacity of 24 pts."

Skill matching:
- If a ticket has NO skill_vector entries with weight >= 0.2 it is unconstrained;
  assign by capacity / velocity. Set `skill_match_reasoning` to "capacity_only".
- If a ticket has a SINGLE high skill (one entry with weight >= 0.6) prefer
  developers whose `skill_ratings[that_skill] >= 0.6`. If none qualify, surface
  this as a warning in `reasoning` and assign by capacity / velocity.
- If a ticket has MULTI-HIGH skills (>=2 entries with weight >= 0.6) prefer the
  developer with the highest combined rating across those skills. If no single
  developer hits >= 0.6 on all of them, flag a pair-program candidate in
  `reasoning`.
- Always cite the matching skill name and the developer's numeric rating in
  `skill_match_reasoning` (e.g. "SQL=0.9 matched required SQL=0.8").

PREVIOUS-SPRINT OVERRIDES
If the message contains a "Previous Sprint Overrides" section, factor recurring
patterns into your reasoning. If a developer is repeatedly reassigned AWAY from
a skill area, prefer not to assign similar tickets to them again. Cite the
pattern in your `reasoning` field when it influences a decision.

Always respond by calling the create_sprint_plan tool with your complete \
analysis. Do not respond in prose outside the tool call.\
"""

_CITATION_INSTRUCTION = (
    "For each assignment, cite the specific historical data you are using. "
    'Example: "Based on 4 backend/bug sprints averaging 8.2 pts, '
    "this fits within Alice's safe capacity of 24 pts.\""
)


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass
class SprintBrainInput:
    team_id: str
    candidate_tickets: list[dict]      # backlog ticket dicts
    developer_profiles: list[dict]     # output from velocity engine
    sprint_length_days: int
    sprint_start_date: str             # ISO-8601 date string
    pto_overrides: dict[str, float] = field(default_factory=dict)  # dev_id → pto_days
    historical_patterns: list[str] = field(default_factory=list)  # recurring failure pattern descriptions


@dataclass
class SprintBrainOutput:
    assignments: list[dict]            # [{ticket_id, developer_id, reasoning, confidence, story_points?}]
    confidence_score: float            # 0.0–1.0
    summary: str
    warnings: list[str]
    what_if_dropped: dict[str, float]  # ticket_id → new overall confidence if dropped
    insufficient_data_devs: list[dict] = field(default_factory=list)
    # Each entry: {developer_id, display_name, sprints_recorded, sprints_needed}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_MIN_SPRINTS = 0  # TODO: restore to 3 once cold-start fallback is implemented (tasks/todo.md)


def _apply_sprint_gate(
    developer_profiles: list[dict],
) -> tuple[list[dict], list[dict]]:
    """
    Split developer profiles into eligible and insufficient-data buckets.

    A developer is eligible if their top-level sprint_count >= _MIN_SPRINTS.
    Returns (eligible_profiles, insufficient_data_entries).
    """
    eligible: list[dict] = []
    insufficient: list[dict] = []

    for profile in developer_profiles:
        raw = profile.get("sprint_count") or 0
        try:
            recorded = int(raw)
        except (TypeError, ValueError):
            recorded = 0
        if recorded >= _MIN_SPRINTS:
            eligible.append(profile)
        else:
            needed = max(0, _MIN_SPRINTS - recorded)
            insufficient.append({
                "developer_id": profile.get("developer_id", "unknown"),
                "display_name": profile.get("display_name", "Unknown"),
                "sprints_recorded": recorded,
                "sprints_needed": needed,
            })

    return eligible, insufficient


def _extract_plan(response: anthropic.types.Message) -> SprintBrainOutput:
    tool_block = next(
        (
            b
            for b in response.content
            if b.type == "tool_use" and b.name == "create_sprint_plan"
        ),
        None,
    )
    if tool_block is None:
        raise RuntimeError(
            "Claude did not return a sprint plan tool call. "
            "This is unexpected — please try again."
        )
    plan: dict = tool_block.input  # SDK already parses to dict

    # Backward-compat: default skill_match_reasoning if the model omitted it
    # (older response shape, or before this field existed). Never raise.
    safe_assignments = []
    for a in plan.get("assignments", []):
        if isinstance(a, dict) and "skill_match_reasoning" not in a:
            a = {**a, "skill_match_reasoning": None}
        safe_assignments.append(a)

    return SprintBrainOutput(
        assignments=safe_assignments,
        confidence_score=float(plan["confidence_score"]),
        summary=plan["summary"],
        warnings=plan["warnings"],
        what_if_dropped={k: float(v) for k, v in plan["what_if_dropped"].items()},
    )


def _build_complexity_message(tickets: list[dict]) -> str:
    lines = ["## Tickets to Analyse", ""]
    for i, ticket in enumerate(tickets, 1):
        tid = ticket.get("id") or ticket.get("ticket_id") or f"ticket-{i}"
        title = ticket.get("summary") or ticket.get("title") or "(no title)"
        points = ticket.get("story_points") or ticket.get("points") or "?"
        priority = ticket.get("priority", "medium")
        labels = ticket.get("labels") or []

        lines.append(f"{i}. [{tid}] {title}")
        lines.append(f"   Story points: {points} | Priority: {priority}")
        if labels:
            lines.append(f"   Labels: {', '.join(labels)}")
        if ticket.get("description"):
            desc = str(ticket["description"])[:200]
            lines.append(f"   Description: {desc}")
        lines.append("")

    lines.append("Analyse each ticket and call the analyse_tickets tool with your assessment.")
    return "\n".join(lines)


def _extract_complexity(response: anthropic.types.Message) -> list[dict]:
    tool_block = next(
        (b for b in response.content if b.type == "tool_use" and b.name == "analyse_tickets"),
        None,
    )
    if tool_block is None:
        raise RuntimeError(
            "Claude did not return a complexity analysis tool call. "
            "Please try again."
        )
    raw = tool_block.input
    # Anthropic SDK occasionally hands back the raw list rather than the
    # wrapped {"ticket_analyses": [...]} shape — accept either.
    if isinstance(raw, list):
        return raw
    analyses = raw.get("ticket_analyses") or []
    if not analyses:
        # Empty / missing key → most likely Claude hit max_tokens
        # mid-serialisation. Don't 500; the planner can still produce
        # assignments without per-ticket complexity context.
        logger.warning(
            "analyse_tickets tool returned no ticket_analyses; "
            "tool_block.input=%r stop_reason=%r",
            raw, getattr(response, "stop_reason", None),
        )
    return analyses


async def _analyse_ticket_complexity(
    tickets: list[dict],
    client: anthropic.AsyncAnthropic,
) -> tuple[list[dict], object]:
    """
    Claude Call 1: analyse ticket complexity without developer context.
    Returns (per-ticket complexity dicts, response usage) so the caller can
    aggregate cost across the full generation.
    """
    response = await client.messages.create(
        model=_MODEL,
        max_tokens=8192,
        system=_COMPLEXITY_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _build_complexity_message(tickets)}],
        tools=[_COMPLEXITY_TOOL],
        tool_choice={"type": "tool", "name": "analyse_tickets"},
    )
    return _extract_complexity(response), response.usage


def _format_skill_inline(skill_map: dict, threshold: float = 0.2) -> str:
    """Format a {skill: weight} dict into 'SQL=0.8, Java=0.3' string, filtered by threshold."""
    if not isinstance(skill_map, dict):
        return ""
    items = []
    for skill, weight in skill_map.items():
        try:
            w = float(weight)
        except (TypeError, ValueError):
            continue
        if w >= threshold:
            items.append((skill, w))
    items.sort(key=lambda x: -x[1])
    return ", ".join(f"{s}={w:g}" for s, w in items)


_MAX_OVERRIDES_IN_PROMPT = 30


async def _fetch_recent_overrides(
    team_id: str,
    db: AsyncSession,
    n_sprints: int = 2,
) -> list[dict]:
    """
    Return overrides from the most recent N completed sprints for this team.

    Each item shape:
      {
        "ticket_key": "PROJ-123",
        "action": "reassign",
        "from_dev": "Alice" | None,
        "to_dev": "Bob" | None,
        "reason_code": "skill_fit" | None,
      }

    Ordered most-recent first. Returns [] when no overrides exist.
    """
    try:
        team_uuid = uuid.UUID(team_id) if isinstance(team_id, str) else team_id
    except (ValueError, TypeError):
        return []

    # Find the N most recent completed sprints for this team.
    recent_sprints_stmt = (
        select(Sprint.id)
        .where(
            Sprint.team_id == team_uuid,
            Sprint.status == SprintStatus.COMPLETED,
        )
        .order_by(Sprint.end_date.desc())
        .limit(n_sprints)
    )
    try:
        sprint_ids_result = await db.execute(recent_sprints_stmt)
        sprint_ids = [row[0] for row in sprint_ids_result.all()]
    except Exception:
        return []

    if not sprint_ids:
        return []

    # Aliased joins onto Developer twice (original + new) and Ticket once.
    from sqlalchemy.orm import aliased

    OriginalDev = aliased(Developer)
    NewDev = aliased(Developer)

    stmt = (
        select(
            SprintPlanOverride.action,
            SprintPlanOverride.reason_code,
            SprintPlanOverride.created_at,
            Ticket.jira_issue_key,
            OriginalDev.name,
            NewDev.name,
        )
        .join(Ticket, Ticket.id == SprintPlanOverride.ticket_id)
        .outerjoin(OriginalDev, OriginalDev.id == SprintPlanOverride.original_developer_id)
        .outerjoin(NewDev, NewDev.id == SprintPlanOverride.new_developer_id)
        .where(SprintPlanOverride.sprint_id.in_(sprint_ids))
        .order_by(SprintPlanOverride.created_at.desc())
    )

    try:
        result = await db.execute(stmt)
        rows = result.all()
    except Exception:
        return []

    out: list[dict] = []
    for action, reason_code, _created_at, ticket_key, original_name, new_name in rows:
        out.append({
            "ticket_key": ticket_key or "",
            "action": action,
            "from_dev": original_name,
            "to_dev": new_name,
            "reason_code": reason_code,
        })
    return out


def _format_overrides_section(overrides: list[dict]) -> str:
    """
    Format a list of override dicts into a prompt section.

    Returns '' for an empty list so callers can omit the section entirely.
    Caps at _MAX_OVERRIDES_IN_PROMPT and appends a truncation note when exceeded.
    """
    if not overrides:
        return ""

    total = len(overrides)
    truncated = overrides[:_MAX_OVERRIDES_IN_PROMPT]

    lines = [f"## Previous Sprint Overrides (last 2 sprints)", ""]
    for o in truncated:
        action = o.get("action") or ""
        ticket_key = o.get("ticket_key") or "?"
        from_dev = o.get("from_dev")
        to_dev = o.get("to_dev")
        reason = o.get("reason_code") or "unspecified"

        if action == "reassign":
            lines.append(
                f"- {ticket_key} reassigned {from_dev or '?'} → {to_dev or '?'} "
                f"(reason: {reason})"
            )
        elif action == "remove":
            lines.append(
                f"- {ticket_key} removed from {from_dev or '?'} (reason: {reason})"
            )
        elif action == "add":
            lines.append(
                f"- {ticket_key} added to {to_dev or '?'} (reason: {reason})"
            )
        else:
            # Unknown action — fall back to a generic line
            lines.append(f"- {ticket_key} {action} (reason: {reason})")

    if total > _MAX_OVERRIDES_IN_PROMPT:
        lines.append(
            f"... (+{total - _MAX_OVERRIDES_IN_PROMPT} more overrides omitted)"
        )
    lines.append("")
    return "\n".join(lines)


def _build_assignment_message(
    inp: SprintBrainInput,
    complexity_analysis: list[dict],
    eligible_profiles: list[dict],
    overrides_section: str = "",
) -> str:
    # Index complexity by ticket_id for quick lookup
    complexity_map = {c["ticket_id"]: c for c in complexity_analysis}

    lines: list[str] = [
        "## Sprint Planning Request",
        f"Team ID: {inp.team_id}",
        f"Sprint start: {inp.sprint_start_date}",
        f"Sprint length: {inp.sprint_length_days} days",
        "",
        "## Developer Profiles (eligible assignees only)",
        "",
    ]

    for profile in eligible_profiles:
        dev_id = profile.get("developer_id", "unknown")
        display = profile.get("display_name", dev_id)
        capacity = profile.get("safe_capacity_pts", "?")
        pto = inp.pto_overrides.get(dev_id, 0.0)

        lines.append(f"### {display}  (id: {dev_id})")
        lines.append(f"  Safe capacity : {capacity} pts this sprint")
        if pto > 0:
            lines.append(f"  PTO           : {pto} day(s)")

        breakdown = profile.get("velocity_breakdown") or []
        if breakdown:
            lines.append("  Historical velocity breakdown:")
            for row in breakdown:
                # Support both shapes: legacy (ticket_type/domain) and per-skill ({skill, avg_pts, sample_count}).
                if "skill" in row:
                    skill = row.get("skill", "?")
                    avg = row.get("avg_pts", "?")
                    count = row.get("sample_count", "?")
                    lines.append(f"    skill={skill} → {count} tickets, avg {avg} pts (weighted)")
                else:
                    ttype = row.get("ticket_type", "?")
                    domain = row.get("domain", "?")
                    avg = row.get("avg_pts", "?")
                    count = row.get("sample_count", "?")
                    lines.append(f"    {domain} / {ttype} → {count} sprints, avg {avg} pts/sprint")
        else:
            lines.append("  Historical velocity breakdown: no data recorded")

        # Skill ratings (from self-assessment / onboarding) — emit only if non-empty.
        skill_ratings_line = _format_skill_inline(profile.get("skill_ratings") or {})
        if skill_ratings_line:
            lines.append(f"  Skill ratings: {skill_ratings_line}")
        lines.append("")

    if overrides_section:
        # Insert before the candidate-tickets list so Claude sees override
        # patterns alongside developer + ticket context.
        lines.append(overrides_section)

    lines += ["## Candidate Tickets (with complexity analysis)", ""]
    for i, ticket in enumerate(inp.candidate_tickets, 1):
        tid = ticket.get("id") or ticket.get("ticket_id") or f"ticket-{i}"
        title = ticket.get("summary") or ticket.get("title") or "(no title)"
        points = ticket.get("story_points") or ticket.get("points") or "?"
        priority = ticket.get("priority", "medium")
        labels = ticket.get("labels") or []
        analysis = complexity_map.get(tid, {})

        lines.append(f"{i}. [{tid}] {title}")
        lines.append(f"   Points: {points} | Priority: {priority}")
        if labels:
            lines.append(f"   Labels: {', '.join(labels)}")
        if analysis:
            lines.append(f"   Effort    : {analysis.get('effort', '?')}")
            lines.append(f"   Est. days : {analysis.get('estimated_days', '?')}")
            lines.append(f"   Skills    : {', '.join(analysis.get('required_skills', []))}")
            lines.append(f"   Notes     : {analysis.get('complexity_notes', '')}")

        # Per-ticket skill_vector from TicketSkillAnalysis (optional enrichment).
        ticket_skill_line = _format_skill_inline(ticket.get("skill_vector") or {})
        if ticket_skill_line:
            lines.append(f"   Required skills: {ticket_skill_line}")
        lines.append("")

    if inp.historical_patterns:
        lines += ["## Known Recurring Team Issues (factor into assignments)", ""]
        for pattern in inp.historical_patterns:
            lines.append(f"- {pattern}")
        lines.append("")

    lines += [
        _CITATION_INSTRUCTION,
        "",
        "Please create the optimal sprint plan. For each ticket, assign it to the "
        "best-fit developer and include a citation of the specific historical data "
        "supporting your decision. Populate what_if_dropped for each assigned ticket.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Developer profile builder — capacity-aware
# ---------------------------------------------------------------------------


async def _compute_skill_velocity_breakdown(
    developer_id,
    team_id,
    db: AsyncSession,
) -> list[dict]:
    """
    Aggregate per-skill historical velocity for a developer from
    TicketSkillAnalysis rows joined to completed Tickets they were assigned to.

    Returns a list of {skill, avg_pts, sample_count} dicts. Empty list if
    the developer has no completed tickets with skill analyses.
    """
    dev_uuid = uuid.UUID(str(developer_id)) if not isinstance(developer_id, uuid.UUID) else developer_id

    stmt = (
        select(Ticket, TicketSkillAnalysis)
        .join(TicketSkillAnalysis, TicketSkillAnalysis.ticket_id == Ticket.id)
        .where(
            Ticket.assignee_id == dev_uuid,
            Ticket.status == TicketStatus.DONE,
        )
        .order_by(Ticket.completed_at.desc())
        .limit(100)
    )
    try:
        result = await db.execute(stmt)
        rows = result.all()
    except Exception:
        # Defensive: if the join fails (e.g. schema mismatch in tests), fall back to empty.
        return []

    # skill -> [weighted_pts_sum, weight_sum, count]
    accum: dict[str, list[float]] = {}
    for ticket, analysis in rows:
        story_points = float(ticket.story_points_estimated or 0.0)
        skill_vector = analysis.skill_vector or {}
        if not isinstance(skill_vector, dict):
            continue
        for skill, weight in skill_vector.items():
            try:
                w = float(weight)
            except (TypeError, ValueError):
                continue
            if w < 0.1:
                continue
            bucket = accum.setdefault(skill, [0.0, 0.0, 0])
            bucket[0] += story_points * w
            bucket[1] += w
            bucket[2] += 1

    breakdown: list[dict] = []
    for skill, (weighted_sum, weight_sum, count) in accum.items():
        if weight_sum <= 0:
            continue
        avg_pts = round(weighted_sum / weight_sum, 2)
        breakdown.append({
            "skill": skill,
            "avg_pts": avg_pts,
            "sample_count": count,
        })

    return breakdown


async def _get_developer_profiles(
    team_id: str,
    db: AsyncSession,
    sprint_id: str | None = None,
) -> list[dict]:
    """
    Build developer profiles for sprint planning, enriched with meeting overhead
    and capacity overrides.

    For each active developer on the team:
    1. Compute per_dev_velocity from completed sprint history (avg delivered_points / active devs).
    2. Load team.meeting_overhead_pct.
    3. Load DeveloperCapacityOverride for (developer_id, sprint_id) if one exists.
    4. Compute safe_capacity_pts = per_dev_velocity * capacity_pct * (1 - meeting_overhead_pct).
    5. Attach meetingOverheadPct and capacityOverridePct to the profile dict.

    Returns profiles sorted by display_name.
    """
    team_uuid = uuid.UUID(team_id) if isinstance(team_id, str) else team_id

    # Load team for meeting overhead
    team_result = await db.execute(select(Team).where(Team.id == team_uuid))
    team = team_result.scalar_one_or_none()
    meeting_overhead_pct = team.meeting_overhead_pct if team else 0.0

    # Load active developers
    devs_result = await db.execute(
        select(Developer).where(
            Developer.team_id == team_uuid,
            Developer.is_active.is_(True),
        )
    )
    developers = devs_result.scalars().all()
    if not developers:
        return []

    # Compute base velocity from completed sprints (team avg / dev count)
    sprints_result = await db.execute(
        select(Sprint).where(
            Sprint.team_id == team_uuid,
            Sprint.status == SprintStatus.COMPLETED,
            Sprint.delivered_points.isnot(None),
        ).order_by(Sprint.end_date.desc()).limit(6)
    )
    completed_sprints = sprints_result.scalars().all()

    if completed_sprints:
        team_avg = sum(s.delivered_points for s in completed_sprints) / len(completed_sprints)
        per_dev_velocity = round(team_avg / len(developers), 1)
        sprint_count = len(completed_sprints)
    else:
        per_dev_velocity = 8.0  # cold-start default
        sprint_count = 0

    # Load capacity overrides (sprint-specific or "next sprint" if sprint_id is None)
    sprint_uuid = uuid.UUID(sprint_id) if sprint_id else None
    dev_ids = [d.id for d in developers]
    overrides_query = select(DeveloperCapacityOverride).where(
        DeveloperCapacityOverride.developer_id.in_(dev_ids),
    )
    if sprint_uuid:
        overrides_query = overrides_query.where(
            DeveloperCapacityOverride.sprint_id == sprint_uuid
        )
    else:
        overrides_query = overrides_query.where(
            DeveloperCapacityOverride.sprint_id.is_(None)
        )
    overrides_result = await db.execute(overrides_query)
    overrides = {o.developer_id: o for o in overrides_result.scalars().all()}

    profiles = []
    for dev in sorted(developers, key=lambda d: d.name):
        override = overrides.get(dev.id)
        capacity_pct = (
            override.capacity_pct
            if override and override.capacity_pct is not None
            else 1.0
        )

        # Apply both meeting overhead and capacity override
        safe_capacity_pts = round(
            per_dev_velocity * capacity_pct * (1 - meeting_overhead_pct), 1
        )

        default_breakdown = [
            {
                "ticket_type": "general",
                "domain": dev.role or "Engineering",
                "avg_pts": per_dev_velocity,
                "sample_count": sprint_count,
            }
        ] if sprint_count > 0 else []

        # Try to enrich with per-skill aggregation. If no analysis data exists,
        # fall back to the single-row default above.
        skill_breakdown = await _compute_skill_velocity_breakdown(dev.id, team_uuid, db)
        velocity_breakdown = skill_breakdown if skill_breakdown else default_breakdown

        profiles.append({
            "developer_id": str(dev.id),
            "display_name": dev.name,
            "role": dev.role or "Engineer",
            "email": dev.email or "",
            "seniority": dev.seniority,
            "skill_ratings": dev.skill_ratings or {},
            "velocity": per_dev_velocity,
            "sprint_count": sprint_count,
            "avg_points_per_sprint": per_dev_velocity,
            "safe_capacity_pts": safe_capacity_pts,
            "meetingOverheadPct": meeting_overhead_pct,
            "capacityOverridePct": capacity_pct,
            "velocity_breakdown": velocity_breakdown,
        })

    return profiles


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def generate_sprint_plan(
    inp: SprintBrainInput,
    anthropic_api_key: str,
    db: AsyncSession | None = None,
) -> SprintBrainOutput:
    """
    Generate an AI-powered sprint plan using a two-step Claude Opus 4.6 pipeline.

    Step 1 — Analyse ticket complexity (no developer context).
    Step 2 — Generate assignments with velocity-grounded reasoning and citations.

    Developers with fewer than 3 sprints of data are gated out before either call.
    Their cards are returned in SprintBrainOutput.insufficient_data_devs.

    The anthropic_api_key must come from the customer (BYOK) — never from env.

    Raises:
        ValueError: if the API key is invalid.
        RuntimeError: if all developers fail the data gate, on rate limits,
                      API errors, or unexpected model output.
    """
    eligible_profiles, insufficient_data_devs = _apply_sprint_gate(inp.developer_profiles)

    # Only block if there ARE profiles but none pass the gate.
    # If profiles is empty (stub / new team), proceed — Claude assigns by complexity alone.
    if inp.developer_profiles and not eligible_profiles:
        raise RuntimeError(
            "Sprint plan cannot be generated: no eligible developers. "
            "All team members have fewer than 3 sprints of recorded data."
        )

    client = anthropic.AsyncAnthropic(api_key=anthropic_api_key)

    # Resolve override context (last-N completed sprints) when a DB session
    # is available. Safe no-op for legacy callers / tests that don't pass db.
    overrides_section = ""
    if db is not None:
        try:
            recent_overrides = await _fetch_recent_overrides(inp.team_id, db, n_sprints=2)
            overrides_section = _format_overrides_section(recent_overrides)
        except Exception:
            logger.warning("Failed to fetch sprint plan overrides; proceeding without.", exc_info=True)
            overrides_section = ""

    try:
        # --- Call 1: ticket complexity analysis ---
        complexity_analysis, complexity_usage = await _analyse_ticket_complexity(
            inp.candidate_tickets, client
        )

        # --- Call 2: assignment generation with historical citations ---
        assignment_message = _build_assignment_message(
            inp, complexity_analysis, eligible_profiles, overrides_section=overrides_section,
        )
        response = await client.messages.create(
            model=_MODEL,
            max_tokens=16384,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": assignment_message}],
            tools=[_SPRINT_PLAN_TOOL],
            # Note: thinking={"type": "adaptive"} is intentionally omitted here.
            # Forced tool_choice is incompatible with extended thinking in the Anthropic API.
            tool_choice={"type": "tool", "name": "create_sprint_plan"},
        )

    except anthropic.AuthenticationError as exc:
        raise ValueError(
            "Invalid Anthropic API key. Please update your key in Settings."
        ) from exc
    except anthropic.RateLimitError as exc:
        raise RuntimeError(
            "Anthropic API rate limit reached. Please wait a moment and try again."
        ) from exc
    except anthropic.APIError as exc:
        raise RuntimeError(f"Anthropic API error: {exc.message}") from exc

    plan = _extract_plan(response)
    plan.insufficient_data_devs = insufficient_data_devs

    record_generation_cost(
        "sprint_plan",
        complexity_usage,
        response.usage,
        model=_MODEL,
        team_id=inp.team_id,
        ticket_count=len(inp.candidate_tickets),
    )

    return plan


async def simulate_what_if(
    inp: SprintBrainInput,
    dropped_ticket_ids: list[str],
    anthropic_api_key: str,
    db: AsyncSession | None = None,
) -> SprintBrainOutput:
    """
    Re-run sprint planning with the specified tickets removed from the
    candidate list. Returns the revised plan so the caller can compare
    confidence and assignments before/after.
    """
    drop_set = set(dropped_ticket_ids)
    modified_tickets = [
        t
        for t in inp.candidate_tickets
        if (t.get("id") or t.get("ticket_id", "")) not in drop_set
    ]
    modified_input = SprintBrainInput(
        team_id=inp.team_id,
        candidate_tickets=modified_tickets,
        developer_profiles=inp.developer_profiles,
        sprint_length_days=inp.sprint_length_days,
        sprint_start_date=inp.sprint_start_date,
        pto_overrides=inp.pto_overrides,
    )
    if db is not None:
        return await generate_sprint_plan(modified_input, anthropic_api_key, db=db)
    return await generate_sprint_plan(modified_input, anthropic_api_key)
