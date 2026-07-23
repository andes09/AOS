"""
Onboarding v2 — the pivot's GitHub + profile + idea-interview flow.

The flow state is DERIVED from data, never stored as a step pointer:
GET /state computes each step from the GitHub connection row, the Developer
profile, and the idea-chat session, so any UI can render the flow from one
endpoint.

GET    /api/onboarding/v2/state          → full flow state (single source of truth)
POST   /api/onboarding/v2/github/skip    → mark the GitHub step skipped
PUT    /api/onboarding/v2/profile        → save name + phone on the caller's Developer
PUT    /api/onboarding/v2/purpose        → save the project's purpose (hobby/startup/learning)
POST   /api/onboarding/v2/chat/start     → idempotently start the idea interview
GET    /api/onboarding/v2/chat           → full transcript + extracted brief
POST   /api/onboarding/v2/chat/message   → send a message; SSE-streamed assistant reply
POST   /api/onboarding/v2/chat/complete  → user override: end the interview now
POST   /api/onboarding/v2/complete       → finish onboarding (requires profile only)
"""

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_user_id, get_current_org_id
from src.database import get_db
from src.integrations.github.router import get_active_connection
from src.models.developer import Developer
from src.models.github_connection import GithubConnection
from src.models.onboarding_session import OnboardingMessage, OnboardingSession
from src.models.organization import Organization
from src.models.team import Team
from src.services import idea_interview

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/onboarding/v2", tags=["onboarding-v2"])

_PHONE_RE = re.compile(r"^\+?[0-9][0-9\s\-().]{5,30}$")

STEP_GITHUB = "github_connect"
STEP_PROFILE = "profile"
STEP_PURPOSE = "purpose"
STEP_IDEA_CHAT = "idea_chat"

PROJECT_PURPOSES = ("hobby", "startup", "learning")


async def _get_org(clerk_org_id: str, db: AsyncSession) -> Organization:
    org = await db.scalar(
        select(Organization).where(Organization.clerk_org_id == clerk_org_id)
    )
    if not org:
        raise HTTPException(status_code=409, detail="org_not_provisioned")
    return org


async def _get_developer(org: Organization, user_id: str, db: AsyncSession) -> Developer | None:
    return await db.scalar(
        select(Developer)
        .join(Team, Developer.team_id == Team.id)
        .where(Team.organization_id == org.id, Developer.clerk_user_id == user_id)
    )


async def _get_session(org: Organization, db: AsyncSession) -> OnboardingSession | None:
    return await db.scalar(
        select(OnboardingSession).where(OnboardingSession.organization_id == org.id)
    )


async def _get_or_create_session(
    org: Organization, user_id: str, db: AsyncSession
) -> OnboardingSession:
    session = await _get_session(org, db)
    if session is None:
        session = OnboardingSession(
            organization_id=org.id,
            created_by_user_id=user_id,
            status="in_progress",
        )
        db.add(session)
        await db.flush()
    return session


def _profile_complete(developer: Developer | None) -> bool:
    # Auto-provisioned rows have name == clerk_user_id; a real name is one the
    # user actually typed, and phone is only ever set via PUT /profile.
    return bool(
        developer
        and developer.phone
        and developer.name
        and developer.name != developer.clerk_user_id
    )


async def _build_state(
    org: Organization, user_id: str, db: AsyncSession
) -> dict:
    connection = await get_active_connection(org, db)
    developer = await _get_developer(org, user_id, db)
    session = await _get_session(org, db)

    github_skipped = bool(session and session.github_skipped_at)
    needs_reconnect = bool(connection) and connection.installation_id is None
    github_done = (bool(connection) and connection.installation_id is not None) or github_skipped
    profile_done = _profile_complete(developer)
    purpose_done = bool(session and session.project_purpose)
    chat_done = bool(session and session.status == "completed")

    message_count = 0
    if session:
        message_count = (
            await db.scalar(
                select(func.count(OnboardingMessage.id)).where(
                    OnboardingMessage.session_id == session.id
                )
            )
            or 0
        )

    done_flags = [
        (STEP_GITHUB, github_done, True),
        (STEP_PROFILE, profile_done, False),
        (STEP_PURPOSE, purpose_done, False),
        (STEP_IDEA_CHAT, chat_done, False),
    ]
    steps = []
    current_assigned = False
    current_step = "done"
    for step_id, done, skippable in done_flags:
        if done:
            status = "complete"
        elif not current_assigned:
            status = "current"
            current_step = step_id
            current_assigned = True
        else:
            status = "pending"
        steps.append({"id": step_id, "status": status, "skippable": skippable})

    return {
        "currentStep": current_step,
        "steps": steps,
        "github": {
            "connected": bool(connection),
            "login": connection.github_login if connection else None,
            "skipped": github_skipped,
            "needsReconnect": needs_reconnect,
        },
        "profile": {
            # Auto-provisioned rows carry name == clerk_user_id; never echo that.
            "name": developer.name if developer and developer.name != developer.clerk_user_id else None,
            "phone": developer.phone if developer else None,
            "complete": profile_done,
        },
        "purpose": {
            "value": session.project_purpose if session else None,
            "complete": purpose_done,
        },
        "ideaChat": {
            "sessionId": str(session.id) if session else None,
            "status": session.status if session else "not_started",
            "messageCount": message_count,
            "brief": session.project_brief if session else None,
            "briefComplete": bool(session and session.brief_complete),
        },
        "onboardingCompleted": org.onboarding_completed_at is not None,
    }


@router.get("/state")
async def get_state(
    user_id: str = Depends(get_current_user_id),
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    org = await _get_org(clerk_org_id, db)
    return await _build_state(org, user_id, db)


@router.post("/github/skip")
async def skip_github(
    user_id: str = Depends(get_current_user_id),
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    org = await _get_org(clerk_org_id, db)
    session = await _get_or_create_session(org, user_id, db)
    if session.github_skipped_at is None:
        session.github_skipped_at = datetime.utcnow()
    await db.commit()
    return await _build_state(org, user_id, db)


class ProfileRequest(BaseModel):
    name: str
    phone: str

    @field_validator("name")
    @classmethod
    def _name_valid(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) > 255:
            raise ValueError("name must be 1-255 characters")
        return v

    @field_validator("phone")
    @classmethod
    def _phone_valid(cls, v: str) -> str:
        v = v.strip()
        if not _PHONE_RE.match(v):
            raise ValueError("phone must be a valid phone number")
        return v


@router.put("/profile")
async def put_profile(
    body: ProfileRequest,
    user_id: str = Depends(get_current_user_id),
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    org = await _get_org(clerk_org_id, db)
    developer = await _get_developer(org, user_id, db)
    if developer is None:
        team = await db.scalar(select(Team).where(Team.organization_id == org.id))
        if team is None:
            raise HTTPException(status_code=409, detail="org_not_provisioned")
        developer = Developer(
            id=uuid.uuid4(),
            team_id=team.id,
            clerk_user_id=user_id,
            name=body.name,
            app_role="developer",
        )
        db.add(developer)
    developer.name = body.name
    developer.phone = body.phone
    await db.commit()
    return await _build_state(org, user_id, db)


class PurposeRequest(BaseModel):
    purpose: str

    @field_validator("purpose")
    @classmethod
    def _purpose_valid(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in PROJECT_PURPOSES:
            raise ValueError(f"purpose must be one of {PROJECT_PURPOSES}")
        return v


@router.put("/purpose")
async def put_purpose(
    body: PurposeRequest,
    user_id: str = Depends(get_current_user_id),
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """Save the project's purpose. Collected explicitly (not chat-extracted)
    because it deterministically selects which interview strategy runs."""
    org = await _get_org(clerk_org_id, db)
    session = await _get_or_create_session(org, user_id, db)
    session.project_purpose = body.purpose
    await db.commit()
    return await _build_state(org, user_id, db)


async def _chat_messages(session: OnboardingSession, db: AsyncSession) -> list[OnboardingMessage]:
    return list(
        (
            await db.execute(
                select(OnboardingMessage)
                .where(OnboardingMessage.session_id == session.id)
                .order_by(OnboardingMessage.seq)
            )
        ).scalars().all()
    )


async def _chat_payload(session: OnboardingSession, db: AsyncSession) -> dict:
    messages = await _chat_messages(session, db)
    return {
        "sessionId": str(session.id),
        "status": session.status,
        "messages": [
            {
                "id": str(m.id),
                "role": m.role,
                "content": m.content,
                "createdAt": m.created_at.isoformat(),
            }
            for m in messages
        ],
        "brief": session.project_brief,
        "briefComplete": session.brief_complete,
    }


@router.post("/chat/start")
async def start_chat(
    user_id: str = Depends(get_current_user_id),
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """Idempotently start the idea interview with a canned opening message."""
    org = await _get_org(clerk_org_id, db)
    session = await _get_or_create_session(org, user_id, db)
    if not session.project_purpose:
        raise HTTPException(status_code=409, detail="purpose_not_set")
    existing = await db.scalar(
        select(func.count(OnboardingMessage.id)).where(
            OnboardingMessage.session_id == session.id
        )
    )
    if not existing:
        db.add(OnboardingMessage(
            session_id=session.id,
            role="assistant",
            content=idea_interview.opening_message(session.project_purpose),
            seq=0,
        ))
    await db.commit()
    return await _chat_payload(session, db)


@router.get("/chat")
async def get_chat(
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    org = await _get_org(clerk_org_id, db)
    session = await _get_session(org, db)
    if session is None:
        return {
            "sessionId": None,
            "status": "not_started",
            "messages": [],
            "brief": None,
            "briefComplete": False,
        }
    return await _chat_payload(session, db)


class ChatMessageRequest(BaseModel):
    content: str

    @field_validator("content")
    @classmethod
    def _content_valid(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) > 4000:
            raise ValueError("content must be 1-4000 characters")
        return v


def _sse_format(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


async def _chat_event_stream(
    session: OnboardingSession, content: str, api_key: str, db: AsyncSession
):
    """SSE generator: `token` events while Claude replies, then `brief`, then
    `done` — or a terminal `error`."""
    queue: asyncio.Queue = asyncio.Queue()

    async def on_token(text: str) -> None:
        await queue.put(("token", {"text": text}))

    async def runner() -> None:
        try:
            result = await idea_interview.run_interview_turn(
                session, content, api_key, db, on_token
            )
            await queue.put(("brief", {
                "brief": result["brief"],
                "missingFields": result["missing_fields"],
                "briefComplete": result["brief_complete"],
            }))
            await queue.put(("done", {
                "messageId": result["message_id"],
                "status": result["status"],
            }))
        except Exception as e:
            logger.exception("[idea-chat] turn failed for session %s", session.id)
            await queue.put(("error", {"message": str(e) or "Interview turn failed"}))
        finally:
            await queue.put(None)  # sentinel

    task = asyncio.create_task(runner())
    try:
        while True:
            item = await queue.get()
            if item is None:
                break
            event, data = item
            yield _sse_format(event, data)
    finally:
        if not task.done():
            task.cancel()


@router.post("/chat/message")
async def send_chat_message(
    body: ChatMessageRequest,
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """Send a user message; the assistant reply streams back as SSE."""
    org = await _get_org(clerk_org_id, db)
    session = await _get_session(org, db)
    if session is None:
        raise HTTPException(status_code=409, detail="chat_not_started")
    if not session.project_purpose:
        raise HTTPException(status_code=409, detail="purpose_not_set")
    if session.status == "completed":
        raise HTTPException(status_code=409, detail="chat_completed")

    user_count = await db.scalar(
        select(func.count(OnboardingMessage.id)).where(
            OnboardingMessage.session_id == session.id,
            OnboardingMessage.role == "user",
        )
    )
    if (user_count or 0) >= idea_interview.MAX_USER_MESSAGES:
        raise HTTPException(status_code=409, detail="message_cap_reached")

    api_key = await idea_interview.resolve_api_key(clerk_org_id, db)

    return StreamingResponse(
        _chat_event_stream(session, body.content, api_key, db),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/chat/complete")
async def complete_chat(
    user_id: str = Depends(get_current_user_id),
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """User override: end the interview even if the brief isn't judged complete."""
    org = await _get_org(clerk_org_id, db)
    session = await _get_session(org, db)
    if session is None:
        raise HTTPException(status_code=409, detail="chat_not_started")
    if session.status != "completed":
        session.status = "completed"
        session.completed_at = datetime.utcnow()
        await db.commit()
    return await _build_state(org, user_id, db)


@router.post("/complete")
async def complete_onboarding(
    user_id: str = Depends(get_current_user_id),
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """Finish onboarding. Only the profile is required — the flow must never
    brick on a GitHub outage or an LLM misjudging when the brief is done."""
    org = await _get_org(clerk_org_id, db)
    developer = await _get_developer(org, user_id, db)
    if not _profile_complete(developer):
        raise HTTPException(status_code=409, detail="profile_incomplete")
    if org.onboarding_completed_at is None:
        org.onboarding_completed_at = datetime.utcnow()
        await db.commit()
    return {"completedAt": org.onboarding_completed_at.isoformat()}
