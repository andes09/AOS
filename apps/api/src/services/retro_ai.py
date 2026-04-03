"""
Retro AI service — Claude Opus 4.6 generates structured sprint retrospectives.

generate_retrospective():
  1. Loads sprint row; 422 if sprint is not COMPLETED
  2. Loads all sprint tickets and computes velocity summary + per-developer breakdown
  3. Sends sprint metrics to Claude Opus 4.6; receives structured retro JSON via tool_use
  4. Upserts Retrospective row idempotently on sprint_id
  5. Upserts RetroPatterns (increments occurrence_count for new occurrences; no-ops on re-run)
  6. Returns RetroResponse
"""

import logging
import uuid
from datetime import datetime, timezone

import anthropic
from fastapi import HTTPException, status
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.organization import Organization
from src.models.retro import PatternStatus, PatternType, RetroPattern, Retrospective
from src.models.sprint import Sprint, SprintStatus, SprintTicket
from src.models.team import Team
from src.services.encryption import decrypt

logger = logging.getLogger(__name__)

_MODEL = "claude-opus-4-6"


# ---------------------------------------------------------------------------
# Pydantic response models
# ---------------------------------------------------------------------------


class ActionItem(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    action: str
    owner: str | None = None
    priority: str  # "high" | "medium" | "low"


class PatternResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    pattern_type: str
    description: str
    occurrence_count: int


class VelocitySummary(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    committed: float
    delivered: float
    completion_rate: float


class RetroResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    retro_id: str
    sprint_id: str
    sprint_name: str
    generated_at: str
    went_well: list[str]
    went_poorly: list[str]
    action_items: list[ActionItem]
    patterns: list[PatternResponse]
    velocity_summary: VelocitySummary


# ---------------------------------------------------------------------------
# Claude tool schema — forces structured retrospective output
# ---------------------------------------------------------------------------

_RETRO_TOOL: dict = {
    "name": "generate_retrospective",
    "description": (
        "Generate a structured sprint retrospective based on sprint metrics "
        "and team performance data."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "wentWell": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Things that went well in the sprint.",
            },
            "wentPoorly": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Things that did not go well in the sprint.",
            },
            "actionItems": {
                "type": "array",
                "description": "Concrete improvement actions for the next sprint.",
                "items": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string"},
                        "owner": {
                            "type": ["string", "null"],
                            "description": "Name or role of the owner, or null if unassigned.",
                        },
                        "priority": {
                            "type": "string",
                            "enum": ["high", "medium", "low"],
                        },
                    },
                    "required": ["action", "owner", "priority"],
                    "additionalProperties": False,
                },
            },
            "detectedPatterns": {
                "type": "array",
                "description": "Recurring issues or patterns detected in this sprint.",
                "items": {
                    "type": "object",
                    "properties": {
                        "patternType": {
                            "type": "string",
                            "enum": [pt.value for pt in PatternType],
                            "description": (
                                "One of: over_commitment, scope_creep, velocity_drop, "
                                "blocker_recurrence, skill_gap"
                            ),
                        },
                        "description": {"type": "string"},
                    },
                    "required": ["patternType", "description"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["wentWell", "wentPoorly", "actionItems", "detectedPatterns"],
        "additionalProperties": False,
    },
}

_SYSTEM_PROMPT = """\
You are an expert agile coach generating a sprint retrospective from quantitative sprint data.

Your task is to analyse the sprint metrics provided and produce:
1. **wentWell**: 3–5 specific things that worked well, grounded in the data.
2. **wentPoorly**: 3–5 specific things that did not go well, backed by evidence from the metrics.
3. **actionItems**: 2–4 concrete, owner-assigned action items to improve next sprint.
4. **detectedPatterns**: Any recurring patterns from the available pattern types:
   - over_commitment: team consistently commits more points than it delivers
   - scope_creep: tickets were added or expanded mid-sprint
   - velocity_drop: delivered points significantly below historical average
   - blocker_recurrence: tickets stalled or slipped due to blockers
   - skill_gap: tickets lacked appropriate skill coverage or required unavailable expertise

Only include a pattern if there is clear evidence in the sprint data.
Always respond by calling the generate_retrospective tool.\
"""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _get_anthropic_key(team_id: str, db: AsyncSession) -> str:
    """Resolve team → org → decrypted Anthropic key. Raises HTTP 402 if unset."""
    team = await db.scalar(select(Team).where(Team.id == uuid.UUID(team_id)))
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found.")

    org = await db.scalar(
        select(Organization).where(Organization.id == team.organization_id)
    )
    if not org or not org.encrypted_anthropic_key:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="No Anthropic API key configured. Please add your key in Settings.",
        )
    return decrypt(org.encrypted_anthropic_key)


def _build_prompt(
    sprint: Sprint,
    sprint_tickets: list[SprintTicket],
    velocity_summary: dict,
    dev_breakdown: list[dict],
    stalled_tickets: list[SprintTicket],
    overloaded_devs: list[str],
) -> str:
    """Build the retrospective prompt from sprint data."""
    committed = velocity_summary["committed"]
    delivered = velocity_summary["delivered"]
    rate = velocity_summary["completionRate"]

    lines = [
        f"## Sprint: {sprint.name}",
        "",
        "## Velocity Summary",
        f"- Committed points : {committed}",
        f"- Delivered points : {delivered}",
        f"- Completion rate  : {rate:.1%}",
        "",
    ]

    if dev_breakdown:
        lines.append("## Per-Developer Breakdown")
        for dev in dev_breakdown:
            lines.append(
                f"- Developer {dev['id']}: assigned {dev['assigned']} pts, "
                f"delivered {dev['delivered']} pts"
            )
        lines.append("")

    if overloaded_devs:
        lines.append("## Overloaded Developers (assigned > delivered)")
        for dev_id in overloaded_devs:
            lines.append(f"- Developer {dev_id}")
        lines.append("")

    if stalled_tickets:
        lines.append("## Stalled / Incomplete Tickets")
        for t in stalled_tickets:
            pts = t.estimated_points or "?"
            slip = f" (cause: {t.slip_cause})" if t.slip_cause else ""
            lines.append(f"- Ticket {t.ticket_id} ({pts} pts){slip}")
        lines.append("")

    lines += [
        "Based on the sprint data above, generate a structured retrospective.",
        "Call the generate_retrospective tool with your analysis.",
    ]
    return "\n".join(lines)


async def _upsert_patterns(
    team_id: str,
    detected_patterns: list[dict],
    sprint: Sprint,
    db: AsyncSession,
) -> list[RetroPattern]:
    """
    Upsert RetroPattern rows idempotently on (team_id, pattern_type, status='active').

    - New pattern type: INSERT with occurrence_count=1.
    - Existing active pattern, different sprint: increment occurrence_count, update last_seen.
    - Existing active pattern, same sprint (regeneration): no-op (idempotent).
    """
    team_uuid = uuid.UUID(team_id)
    result_patterns: list[RetroPattern] = []

    for pattern_data in detected_patterns:
        pattern_type_str = pattern_data["patternType"]
        description = pattern_data["description"]

        existing = await db.scalar(
            select(RetroPattern).where(
                RetroPattern.team_id == team_uuid,
                RetroPattern.pattern_type == pattern_type_str,
                RetroPattern.status == PatternStatus.ACTIVE.value,
            )
        )

        if existing:
            if existing.last_seen_sprint_id != sprint.id:
                # New occurrence for this pattern — increment and track
                existing.occurrence_count += 1
                existing.last_seen_sprint_id = sprint.id
                names = list(existing.affected_sprint_names or [])
                if sprint.name not in names:
                    names.append(sprint.name)
                existing.affected_sprint_names = names
            # Same sprint re-run: skip increment (idempotent)
            result_patterns.append(existing)
        else:
            new_pattern = RetroPattern(
                team_id=team_uuid,
                pattern_type=pattern_type_str,
                description=description,
                occurrence_count=1,
                first_seen_sprint_id=sprint.id,
                last_seen_sprint_id=sprint.id,
                affected_sprint_names=[sprint.name],
                status=PatternStatus.ACTIVE.value,
            )
            db.add(new_pattern)
            result_patterns.append(new_pattern)

    return result_patterns


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def generate_retrospective(
    sprint_id: str,
    team_id: str,
    db: AsyncSession,
) -> RetroResponse:
    """
    Generate a Claude-powered retrospective for a completed sprint.

    Raises:
        HTTPException 402: org has no Anthropic API key configured.
        HTTPException 404: sprint not found.
        HTTPException 422: sprint is not COMPLETED.
        ValueError: invalid Anthropic API key.
        RuntimeError: Claude API error or unexpected response.
    """
    sprint_uuid = uuid.UUID(sprint_id)

    # 1. Load and validate sprint
    sprint = await db.scalar(select(Sprint).where(Sprint.id == sprint_uuid))
    if not sprint:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sprint not found.")
    if sprint.status != SprintStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Sprint must be in COMPLETED status to generate a retrospective.",
        )

    # 2. Load all sprint tickets
    sprint_tickets: list[SprintTicket] = list(
        await db.scalars(select(SprintTicket).where(SprintTicket.sprint_id == sprint_uuid))
    )

    # Compute velocity summary
    committed = sprint.committed_points or sum(
        (t.estimated_points or 0) for t in sprint_tickets
    )
    delivered = sprint.delivered_points or sum(
        (t.actual_points or t.estimated_points or 0) for t in sprint_tickets if t.completed
    )
    completion_rate = (delivered / committed) if committed else 0.0

    velocity_summary = {
        "committed": committed,
        "delivered": delivered,
        "completionRate": completion_rate,
    }

    # Per-developer breakdown
    dev_map: dict[str, dict] = {}
    for ticket in sprint_tickets:
        if ticket.assignee_id is None:
            continue
        dev_id = str(ticket.assignee_id)
        if dev_id not in dev_map:
            dev_map[dev_id] = {"id": dev_id, "assigned": 0.0, "delivered": 0.0}
        dev_map[dev_id]["assigned"] += ticket.estimated_points or 0
        if ticket.completed:
            dev_map[dev_id]["delivered"] += ticket.actual_points or ticket.estimated_points or 0

    dev_breakdown = list(dev_map.values())
    overloaded_devs = [d["id"] for d in dev_breakdown if d["assigned"] > d["delivered"]]
    stalled_tickets = [t for t in sprint_tickets if not t.completed]

    # 3. Resolve Anthropic key and call Claude
    anthropic_api_key = await _get_anthropic_key(team_id, db)
    client = anthropic.AsyncAnthropic(api_key=anthropic_api_key)

    prompt = _build_prompt(
        sprint, sprint_tickets, velocity_summary, dev_breakdown, stalled_tickets, overloaded_devs
    )

    try:
        response = await client.messages.create(
            model=_MODEL,
            max_tokens=4096,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            tools=[_RETRO_TOOL],
            tool_choice={"type": "tool", "name": "generate_retrospective"},
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

    # Extract Claude's structured tool call output
    tool_block = next(
        (
            b
            for b in response.content
            if b.type == "tool_use" and b.name == "generate_retrospective"
        ),
        None,
    )
    if tool_block is None:
        raise RuntimeError("Claude did not return a retrospective. Please try again.")

    retro_data: dict = tool_block.input

    # 4. Upsert Retrospective row (idempotent on sprint_id)
    now = datetime.now(timezone.utc)
    team_uuid = uuid.UUID(team_id)

    existing_retro = await db.scalar(
        select(Retrospective).where(Retrospective.sprint_id == sprint_uuid)
    )

    if existing_retro:
        existing_retro.generated_at = now
        existing_retro.went_well = retro_data["wentWell"]
        existing_retro.went_poorly = retro_data["wentPoorly"]
        existing_retro.action_items = retro_data["actionItems"]
        existing_retro.velocity_summary = velocity_summary
        retro = existing_retro
    else:
        retro = Retrospective(
            sprint_id=sprint_uuid,
            team_id=team_uuid,
            generated_at=now,
            went_well=retro_data["wentWell"],
            went_poorly=retro_data["wentPoorly"],
            action_items=retro_data["actionItems"],
            velocity_summary=velocity_summary,
        )
        db.add(retro)

    # 5. Upsert patterns
    detected_patterns: list[dict] = retro_data.get("detectedPatterns", [])
    upserted_patterns = await _upsert_patterns(team_id, detected_patterns, sprint, db)

    await db.commit()
    await db.refresh(retro)

    # 6. Build and return RetroResponse
    return RetroResponse(
        retro_id=str(retro.id),
        sprint_id=str(retro.sprint_id),
        sprint_name=sprint.name,
        generated_at=retro.generated_at.isoformat(),
        went_well=retro.went_well or [],
        went_poorly=retro.went_poorly or [],
        action_items=[
            ActionItem(
                action=item["action"],
                owner=item.get("owner"),
                priority=item["priority"],
            )
            for item in retro_data["actionItems"]
        ],
        patterns=[
            PatternResponse(
                pattern_type=p.pattern_type,
                description=p.description or "",
                occurrence_count=p.occurrence_count,
            )
            for p in upserted_patterns
        ],
        velocity_summary=VelocitySummary(
            committed=committed,
            delivered=delivered,
            completion_rate=completion_rate,
        ),
    )
