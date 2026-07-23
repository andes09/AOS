"""
Idea interview — the LLM-driven onboarding questionnaire (onboarding v2).

Each turn makes two LLM calls (Groq, via its OpenAI-compatible API):
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

from fastapi import HTTPException, status
from openai import APIError, AsyncOpenAI, AuthenticationError, RateLimitError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.models.onboarding_session import OnboardingMessage, OnboardingSession
from src.schemas.project_brief import anthropic_tool_properties, content_field_aliases
from src.services.cost_tracker import record_generation_cost

logger = logging.getLogger(__name__)

_MODEL = settings.groq_model
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


_BRIEF_SCALAR_FIELDS, _BRIEF_LIST_FIELDS = content_field_aliases()
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
the project in 3-5 bullet points, then ask a single closing question: whether \
there's anything else they'd like to add before you wrap up. Do not tell them \
onboarding is finished at this point — you're still waiting on their answer.
"""

# Appended only on the turn right after the assistant asked its closing
# question above. Whatever the founder says here, the interview ends this
# turn — see run_interview_turn's use of `was_awaiting_confirmation`.
_CONFIRMATION_SYSTEM_ADDENDUM = """

The founder was just asked if they have anything to add before wrapping up, \
and this message is their answer. Respond in 1-2 sentences: if they added new \
information, briefly confirm you've noted it; otherwise just acknowledge \
warmly. Either way, tell them onboarding is complete now. Do not ask another \
question — this is the final message of the interview."""

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


def _brief_tool_input_schema() -> dict:
    """Derive the forced-tool input_schema from ProjectBrief, then layer
    `isComplete` on top — it's an extraction-protocol control field, not
    project content, so it's intentionally not part of ProjectBrief itself.
    """
    properties = anthropic_tool_properties()
    properties["isComplete"] = {
        "type": "boolean",
        "description": "True when the brief has enough substance to plan a roadmap",
    }
    return {
        "type": "object",
        "properties": properties,
        "required": ["isComplete"],
    }


# OpenAI/Groq function-tool form. `_brief_tool_input_schema()` returns a plain
# JSON Schema object, which serves as the function `parameters` unchanged.
_BRIEF_TOOL = {
    "type": "function",
    "function": {
        "name": "update_project_brief",
        "description": "Record everything learned so far about the founder's project.",
        "parameters": _brief_tool_input_schema(),
    },
}


async def resolve_api_key(clerk_org_id: str, db: AsyncSession) -> str:
    """The platform Groq API key for the idea interview. 402 when unset.

    The interview runs on Groq's free API, before the org has saved any of its
    own AI keys, so there's no per-org BYOK path here — it always uses the
    platform key. `clerk_org_id`/`db` are kept for interface stability with the
    router (and a possible future per-org key).
    """
    if settings.groq_api_key:
        return settings.groq_api_key
    raise HTTPException(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        detail="No Groq API key configured for the idea interview. Set GROQ_API_KEY.",
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
        f"\nStill missing: {', '.join(missing_fields(brief)) or 'nothing — summarize and ask if they have anything to add'}"
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
    # Captured before this turn mutates it: True means the assistant's previous
    # message asked "anything else to add?" and this user message is the
    # answer — which always ends the interview, regardless of content.
    was_awaiting_confirmation = session.awaiting_confirmation

    seq = await _next_seq(session, db)
    db.add(OnboardingMessage(session_id=session.id, role="user", content=user_content, seq=seq))
    await db.flush()

    transcript = await _transcript(session, db)
    client = AsyncOpenAI(api_key=api_key, base_url=settings.groq_base_url)

    system_prompt = _system_prompt(session.project_purpose) + _turn_context(session.project_brief)
    if was_awaiting_confirmation:
        system_prompt += _CONFIRMATION_SYSTEM_ADDENDUM
    reply_parts: list[str] = []
    reply_usage = None
    try:
        stream = await client.chat.completions.create(
            model=_MODEL,
            max_tokens=_REPLY_MAX_TOKENS,
            messages=[{"role": "system", "content": system_prompt}, *transcript],
            stream=True,
            stream_options={"include_usage": True},
        )
        async for chunk in stream:
            # The final usage-only chunk carries no choices.
            if chunk.usage is not None:
                reply_usage = chunk.usage
            if not chunk.choices:
                continue
            text = chunk.choices[0].delta.content
            if text:
                reply_parts.append(text)
                await on_token(text)
    except AuthenticationError as exc:
        raise ValueError("Invalid Groq API key.") from exc
    except RateLimitError as exc:
        raise RuntimeError(
            "Groq API rate limit reached. Please wait a moment and try again."
        ) from exc
    except APIError as exc:
        raise RuntimeError(f"Groq API error: {exc}") from exc

    reply_text = "".join(reply_parts)
    assistant_msg = OnboardingMessage(
        session_id=session.id, role="assistant", content=reply_text, seq=seq + 1
    )
    db.add(assistant_msg)
    await db.flush()

    # Extraction pass over the updated transcript.
    extract_usage = None
    try:
        extraction = await client.chat.completions.create(
            model=_MODEL,
            max_tokens=_EXTRACT_MAX_TOKENS,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Extract everything known about the founder's project from this "
                        "onboarding interview transcript. Only record facts the founder "
                        "actually stated — never invent details."
                    ),
                },
                {
                    "role": "user",
                    "content": "Transcript:\n" + json.dumps(transcript + [{"role": "assistant", "content": reply_text}]),
                },
            ],
            tools=[_BRIEF_TOOL],
            tool_choice={"type": "function", "function": {"name": "update_project_brief"}},
        )
        extract_usage = extraction.usage
        tool_calls = extraction.choices[0].message.tool_calls or []
        tool_call = next(
            (t for t in tool_calls if t.function.name == "update_project_brief"),
            None,
        )
        if tool_call is not None:
            extracted = json.loads(tool_call.function.arguments)
            session.project_brief = merge_brief(session.project_brief, extracted)
            # Trust the model's judgment only when the required fields back it
            # up — and only the first time: once we're waiting on the founder's
            # confirmation, this flag has already done its job.
            if (
                not was_awaiting_confirmation
                and extracted.get("isComplete")
                and not missing_fields(session.project_brief)
            ):
                session.brief_complete = True
                session.awaiting_confirmation = True
    except (APIError, json.JSONDecodeError):
        # Extraction is best-effort — a failed pass must not lose the reply.
        logger.exception("idea_interview extraction failed for session %s", session.id)

    user_message_count = sum(1 for m in transcript if m["role"] == "user")
    if was_awaiting_confirmation or user_message_count >= MAX_USER_MESSAGES:
        session.status = "completed"
        session.awaiting_confirmation = False
        if session.completed_at is None:
            session.completed_at = datetime.utcnow()

    await record_generation_cost(
        "idea_interview",
        reply_usage,
        extract_usage,
        provider="groq",
        org_id=session.organization_id,
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
        "awaiting_confirmation": session.awaiting_confirmation,
        "status": session.status,
    }
