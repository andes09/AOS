"""
Sprint Brain AI service — Claude Opus 4.6 powered sprint planning.

Implements generate_sprint_plan() and simulate_what_if() using the Anthropic
API with adaptive thinking and tool_use for structured output.

BYOK model: the Anthropic API key is always supplied by the caller (fetched
from the Organisation record), never from environment.
"""

from dataclasses import dataclass, field

import anthropic

_MODEL = "claude-opus-4-6"

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
                    },
                    "required": ["ticket_id", "developer_id", "reasoning", "confidence"],
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
2. Respect each developer's recommended capacity — never overload.
3. Prioritise high-value, unblocked tickets first.
4. Surface risks proactively: overloaded developers, skill gaps, low-data \
   estimates, sequential dependencies.
5. Be conservative. A sprint with 80 % confidence is far better than one \
   that looks full on paper but will slip.

Always respond by calling the create_sprint_plan tool with your complete \
analysis. Do not respond in prose outside the tool call.\
"""


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

_MIN_SPRINTS = 3


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


def _build_user_message(inp: SprintBrainInput) -> str:
    lines: list[str] = [
        "## Sprint Planning Request",
        f"Team ID: {inp.team_id}",
        f"Sprint start: {inp.sprint_start_date}",
        f"Sprint length: {inp.sprint_length_days} days",
        "",
        "## Developer Profiles",
    ]

    for profile in inp.developer_profiles:
        dev_id = profile.get("developer_id", "unknown")
        display = profile.get("display_name", dev_id)
        velocity = profile.get("velocity", {})
        pto = inp.pto_overrides.get(dev_id, 0.0)

        lines.append(f"\n### {display}  (id: {dev_id})")
        if velocity.get("has_sufficient_data"):
            lines.append(f"  Mean velocity : {velocity.get('mean_velocity')} pts/sprint")
            lines.append(f"  Std deviation : {velocity.get('std_dev')} pts")
            lines.append(f"  Safe capacity : {velocity.get('confidence_capacity')} pts  "
                         f"(based on {velocity.get('sprint_count')} sprints)")
        else:
            needed = velocity.get("sprints_needed", "unknown")
            lines.append(f"  Velocity data : insufficient ({needed} more sprints needed)")
        if pto > 0:
            lines.append(f"  PTO this sprint: {pto} day(s)")

    lines += ["", "## Candidate Tickets  (ordered by priority)"]
    for i, ticket in enumerate(inp.candidate_tickets, 1):
        tid = ticket.get("id") or ticket.get("ticket_id") or f"ticket-{i}"
        title = ticket.get("summary") or ticket.get("title") or "(no title)"
        points = ticket.get("story_points") or ticket.get("points") or "?"
        priority = ticket.get("priority", "medium")
        labels = ticket.get("labels") or []

        lines.append(f"\n{i}. [{tid}] {title}")
        lines.append(f"   Points: {points} | Priority: {priority}")
        if labels:
            lines.append(f"   Labels: {', '.join(labels)}")
        if ticket.get("description"):
            desc = str(ticket["description"])[:200]
            lines.append(f"   Description: {desc}")

    lines += [
        "",
        "Please create the optimal sprint plan. For each ticket you include, "
        "assign it to the best-fit developer. Also populate what_if_dropped: "
        "for each assigned ticket, what would the overall confidence be if "
        "we removed only that ticket?",
    ]
    return "\n".join(lines)


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
    return SprintBrainOutput(
        assignments=plan["assignments"],
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
    return tool_block.input["ticket_analyses"]


async def _analyse_ticket_complexity(
    tickets: list[dict],
    client: anthropic.AsyncAnthropic,
) -> list[dict]:
    """
    Claude Call 1: analyse ticket complexity without developer context.
    Returns a list of per-ticket complexity dicts.
    """
    response = await client.messages.create(
        model=_MODEL,
        max_tokens=4096,
        system=_COMPLEXITY_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _build_complexity_message(tickets)}],
        tools=[_COMPLEXITY_TOOL],
        tool_choice={"type": "tool", "name": "analyse_tickets"},
    )
    return _extract_complexity(response)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def generate_sprint_plan(
    inp: SprintBrainInput,
    anthropic_api_key: str,
) -> SprintBrainOutput:
    """
    Generate an AI-powered sprint plan using Claude Opus 4.6 with adaptive
    thinking and structured output via tool_use.

    The anthropic_api_key must come from the customer (BYOK) — never from env.

    Raises:
        ValueError: if the API key is invalid.
        RuntimeError: on rate limits, API errors, or unexpected model output.
    """
    client = anthropic.AsyncAnthropic(api_key=anthropic_api_key)
    user_message = _build_user_message(inp)

    try:
        response = await client.messages.create(
            model=_MODEL,
            max_tokens=16384,
            thinking={"type": "adaptive"},
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
            tools=[_SPRINT_PLAN_TOOL],
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

    return _extract_plan(response)


async def simulate_what_if(
    inp: SprintBrainInput,
    dropped_ticket_ids: list[str],
    anthropic_api_key: str,
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
    return await generate_sprint_plan(modified_input, anthropic_api_key)
