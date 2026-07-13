"""
Idea interview — the LLM-driven onboarding questionnaire (onboarding v2).

Each turn makes two Claude calls:
1. A streaming conversational reply (tokens forwarded to the caller for SSE).
2. A non-streaming forced-tool extraction over the transcript that updates the
   structured ProjectBrief and judges whether the interview has enough.

Keeping extraction out of the streamed reply keeps the SSE protocol dumb and
the brief deterministic; onboarding runs once per org so the extra call is
negligible.
"""

import json
import logging
from datetime import datetime
from typing import Awaitable, Callable

import anthropic
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.models.onboarding_session import OnboardingMessage, OnboardingSession
from src.services.ai_client import get_anthropic_key
from src.services.cost_tracker import record_generation_cost

logger = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-6"
_REPLY_MAX_TOKENS = 1024
_EXTRACT_MAX_TOKENS = 2048

# Hard cap on user messages per session — bounds platform-key spend and stops
# runaway conversations. The UI should nudge completion well before this.
MAX_USER_MESSAGES = 40

_OPENING_MESSAGES = {
    "hobby": (
        "Hi! I'm here to help plan your project. Since this is a hobby project, "
        "let's keep it fun and manageable — tell me what you're building and "
        "what made you want to build it?"
    ),
    "startup": (
        "Hi! I'm here to help plan your project. Tell me about your idea — "
        "what are you building, who is it for, and what problem does it solve?"
    ),
    "learning": (
        "Hi! I'm here to help plan your project. Since this is about learning, "
        "tell me what you're building and what skill or technology you're hoping "
        "to get better at along the way."
    ),
}
DEFAULT_OPENING_MESSAGE = _OPENING_MESSAGES["startup"]


def opening_message(purpose: str | None) -> str:
    return _OPENING_MESSAGES.get(purpose or "", DEFAULT_OPENING_MESSAGE)

_BRIEF_LIST_FIELDS = [
    "coreFeatures",
    "outOfScope",
    "techConstraints",
    "existingAssets",
    "openQuestions",
]
_BRIEF_SCALAR_FIELDS = [
    "projectName",
    "problemStatement",
    "targetAudience",
    "scope",
    "timeline",
]
# Fields that must be filled before the interview counts as complete.
_REQUIRED_FIELDS = [
    "projectName",
    "problemStatement",
    "targetAudience",
    "coreFeatures",
    "scope",
    "timeline",
]

_BASE_SYSTEM_PROMPT = """You are Omada's project interviewer. A founder is describing a project idea; \
your job is to understand it well enough to plan a roadmap.

Rules:
- Ask exactly ONE question per turn. Never stack questions.
- Keep replies to 2-4 sentences plus the question. Be warm but efficient.
- Don't re-ask what the founder already answered; build on it.
- When every important area is covered, briefly summarize your understanding of \
the project in 3-5 bullet points and tell them they can finish onboarding — do \
not ask another question at that point.
"""

# The project's purpose changes what a "good roadmap" even means, so it changes
# what the interview should prioritize digging into. Collected via an explicit
# step before chat starts (see PUT /purpose) rather than inferred from
# conversation, since the whole interview strategy branches on it.
_PURPOSE_GUIDANCE = {
    "hobby": (
        "This is a HOBBY project — plan around personal enjoyment and free time, "
        "not business outcomes.\n"
        "Prioritize, in order: what problem it solves or why it's fun/motivating; "
        "the core features; what a minimal first version looks like; realistic "
        "time availability (evenings/weekends); existing code or resources.\n"
        "Actively discourage over-scoping — nudge toward the smallest version "
        "that's satisfying to finish. Don't ask about monetization, market size, "
        "or competitors unless the founder brings it up unprompted."
    ),
    "startup": (
        "This is a STARTUP idea — plan around a viable, launchable business.\n"
        "Prioritize, in order: the problem and who specifically has it (target "
        "audience/market); the core features; what belongs in an MVP versus later; "
        "timeline pressure (funding, launch dates, competitors); monetization or "
        "business model; technical constraints or existing assets.\n"
        "Push for a genuinely minimal MVP — resist scope creep and call it out "
        "when the founder describes something bigger than a first version needs."
    ),
    "learning": (
        "This is a LEARNING project — the primary goal is building a skill, not "
        "shipping a business or a perfect hobby app.\n"
        "Prioritize, in order: what skill or technology they want to get better "
        "at; their current experience level with it; what the project should do "
        "(enough to be a real, useful exercise); how deep vs. broad they want to "
        "go (depth on fundamentals vs. breadth across a stack); timeline.\n"
        "Frame scope around learning milestones and portfolio value rather than "
        "feature completeness — a working, well-understood slice beats an "
        "unfinished ambitious one."
    ),
}


def _system_prompt(purpose: str | None) -> str:
    guidance = _PURPOSE_GUIDANCE.get(purpose or "")
    if not guidance:
        return _BASE_SYSTEM_PROMPT
    return _BASE_SYSTEM_PROMPT + "\n" + guidance

_BRIEF_TOOL = {
    "name": "update_project_brief",
    "description": "Record everything learned so far about the founder's project.",
    "input_schema": {
        "type": "object",
        "properties": {
            "projectName": {"type": ["string", "null"], "description": "Working name of the project, if stated"},
            "problemStatement": {"type": ["string", "null"], "description": "The problem being solved, in the founder's terms"},
            "targetAudience": {"type": ["string", "null"], "description": "Who the project is for"},
            "coreFeatures": {"type": "array", "items": {"type": "string"}, "description": "Key features described so far"},
            "scope": {"type": ["string", "null"], "description": "What the first/MVP version includes"},
            "outOfScope": {"type": "array", "items": {"type": "string"}, "description": "Explicitly excluded from the first version"},
            "timeline": {"type": ["string", "null"], "description": "Target timeline or deadline"},
            "techConstraints": {"type": "array", "items": {"type": "string"}, "description": "Stack preferences, integrations, platform constraints"},
            "existingAssets": {"type": "array", "items": {"type": "string"}, "description": "Existing code, designs, repos, or resources"},
            "openQuestions": {"type": "array", "items": {"type": "string"}, "description": "Things still unclear that a planner would need"},
            "isComplete": {"type": "boolean", "description": "True when the brief has enough substance to plan a roadmap"},
        },
        "required": ["isComplete"],
    },
}


async def resolve_api_key(clerk_org_id: str, db: AsyncSession) -> str:
    """Org BYOK key if saved, else the platform key. 402 when neither exists.

    Onboarding runs before the org has had a chance to save its own key, so
    unlike other AI features this one may fall back to the platform key.
    """
    try:
        return await get_anthropic_key(clerk_org_id, db)
    except HTTPException:
        if settings.anthropic_api_key:
            return settings.anthropic_api_key
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="No Anthropic API key available for the idea interview.",
        )


def missing_fields(brief: dict | None) -> list[str]:
    brief = brief or {}
    missing = []
    for field in _REQUIRED_FIELDS:
        value = brief.get(field)
        if value is None or value == "" or value == []:
            missing.append(field)
    return missing


def merge_brief(current: dict | None, extracted: dict) -> dict:
    """Merge an extraction result into the stored brief.

    Lists are replaced wholesale when the extraction returned a non-empty list
    (the extractor sees the full transcript each turn, so its lists are
    authoritative); scalars are overwritten only when non-empty so a weak
    extraction pass can't erase earlier answers.
    """
    merged = dict(current or {})
    for field in _BRIEF_SCALAR_FIELDS:
        value = extracted.get(field)
        if value:
            merged[field] = value
    for field in _BRIEF_LIST_FIELDS:
        value = extracted.get(field)
        if value:
            merged[field] = value
    return merged


async def _next_seq(session: OnboardingSession, db: AsyncSession) -> int:
    from sqlalchemy import func

    max_seq = await db.scalar(
        select(func.max(OnboardingMessage.seq)).where(
            OnboardingMessage.session_id == session.id
        )
    )
    return (max_seq + 1) if max_seq is not None else 0


async def _transcript(session: OnboardingSession, db: AsyncSession) -> list[dict]:
    rows = (
        await db.execute(
            select(OnboardingMessage)
            .where(OnboardingMessage.session_id == session.id)
            .order_by(OnboardingMessage.seq)
        )
    ).scalars().all()
    return [{"role": m.role, "content": m.content} for m in rows]


def _turn_context(brief: dict | None) -> str:
    return (
        f"\n\nCurrent extracted brief (JSON): {json.dumps(brief or {})}"
        f"\nStill missing: {', '.join(missing_fields(brief)) or 'nothing — wrap up'}"
    )


async def run_interview_turn(
    session: OnboardingSession,
    user_content: str,
    api_key: str,
    db: AsyncSession,
    on_token: Callable[[str], Awaitable[None]],
) -> dict:
    """Run one interview turn. Persists both messages, streams reply tokens via
    `on_token`, updates the brief, and returns the turn outcome."""
    seq = await _next_seq(session, db)
    db.add(OnboardingMessage(session_id=session.id, role="user", content=user_content, seq=seq))
    await db.flush()

    transcript = await _transcript(session, db)
    client = anthropic.AsyncAnthropic(api_key=api_key)

    reply_parts: list[str] = []
    try:
        async with client.messages.stream(
            model=_MODEL,
            max_tokens=_REPLY_MAX_TOKENS,
            system=_system_prompt(session.project_purpose) + _turn_context(session.project_brief),
            messages=transcript,
        ) as stream:
            async for text in stream.text_stream:
                reply_parts.append(text)
                await on_token(text)
            reply_response = await stream.get_final_message()
    except anthropic.AuthenticationError as exc:
        raise ValueError("Invalid Anthropic API key.") from exc
    except anthropic.RateLimitError as exc:
        raise RuntimeError(
            "Anthropic API rate limit reached. Please wait a moment and try again."
        ) from exc
    except anthropic.APIError as exc:
        raise RuntimeError(f"Anthropic API error: {exc.message}") from exc

    reply_text = "".join(reply_parts)
    assistant_msg = OnboardingMessage(
        session_id=session.id, role="assistant", content=reply_text, seq=seq + 1
    )
    db.add(assistant_msg)
    await db.flush()

    # Extraction pass over the updated transcript.
    extract_usage = None
    try:
        extraction = await client.messages.create(
            model=_MODEL,
            max_tokens=_EXTRACT_MAX_TOKENS,
            system=(
                "Extract everything known about the founder's project from this "
                "onboarding interview transcript. Only record facts the founder "
                "actually stated — never invent details."
            ),
            messages=[{
                "role": "user",
                "content": "Transcript:\n" + json.dumps(transcript + [{"role": "assistant", "content": reply_text}]),
            }],
            tools=[_BRIEF_TOOL],
            tool_choice={"type": "tool", "name": "update_project_brief"},
        )
        extract_usage = extraction.usage
        tool_block = next(
            (b for b in extraction.content if b.type == "tool_use" and b.name == "update_project_brief"),
            None,
        )
        if tool_block is not None:
            extracted = tool_block.input
            session.project_brief = merge_brief(session.project_brief, extracted)
            # Trust the model's judgment only when the required fields back it up.
            if extracted.get("isComplete") and not missing_fields(session.project_brief):
                session.brief_complete = True
    except anthropic.APIError:
        # Extraction is best-effort — a failed pass must not lose the reply.
        logger.exception("idea_interview extraction failed for session %s", session.id)

    user_message_count = sum(1 for m in transcript if m["role"] == "user")
    if session.brief_complete or user_message_count >= MAX_USER_MESSAGES:
        session.status = "completed"
        if session.completed_at is None:
            session.completed_at = datetime.utcnow()

    record_generation_cost(
        "idea_interview",
        reply_response.usage,
        extract_usage,
        model=_MODEL,
        session_id=str(session.id),
    )

    await db.commit()

    return {
        "message_id": str(assistant_msg.id),
        "reply": reply_text,
        "brief": session.project_brief,
        "missing_fields": missing_fields(session.project_brief),
        "brief_complete": session.brief_complete,
        "status": session.status,
    }
