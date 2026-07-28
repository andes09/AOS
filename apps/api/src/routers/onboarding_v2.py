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
from src.models.project import Project
from src.models.team import Team
from src.services import idea_interview, roadmap_generator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/onboarding/v2", tags=["onboarding-v2"])

_PHONE_RE = re.compile(r"^\+?[0-9][0-9\s\-().]{5,30}$")

STEP_GITHUB = "github_connect"
STEP_PROFILE = "profile"
STEP_PURPOSE = "purpose"
STEP_IDEA_CHAT = "idea_chat"
# The 4th step's id while no build_plan sub-flow has been chosen yet (see
# PUT /plan-source below). Additive, not a rename: STEP_IDEA_CHAT's own
# endpoints are untouched, this is just the new pre-choice state exposed at
# the same position in `steps[]`.
STEP_BUILD_PLAN = "build_plan"
STEP_IMPORT_ARTIFACT = "import_artifact"
# New, genuinely separate step after build_plan — skippable, mirrors
# github_connect (see docs/plans/2026-07-20-import-artifacts.md).
STEP_REPO_SELECT = "repo_select"

PROJECT_PURPOSES = ("hobby", "startup", "learning")
PLAN_SOURCES = ("chat", "import")


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
    """The org's founding session — always the earliest one.

    Orgs can now have more than one OnboardingSession (one per project, see
    the Project Hub plan), so this must stay ordered: org onboarding always
    means the first session ever created, even after project-creation
    sessions exist for the same org.
    """
    return await db.scalar(
        select(OnboardingSession)
        .where(OnboardingSession.organization_id == org.id)
        .order_by(OnboardingSession.created_at.asc())
        .limit(1)
    )


async def _resolve_team(org: Organization, db: AsyncSession) -> Team:
    team = await db.scalar(
        select(Team).where(Team.organization_id == org.id).order_by(Team.created_at)
    )
    if team is None:
        raise HTTPException(status_code=409, detail="no_team_for_org")
    return team


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


def _import_payload(session: OnboardingSession | None) -> dict:
    """Thin wrapper around the artifact-import analysis result, shared by
    `_build_state`'s `importArtifact` field and artifact_import.py's own
    `GET /import` (so the single onboarding state hook still covers
    everything, without artifact_import.py needing to import back from here
    in a circle). Lives here, not in artifact_import.py, purely to keep the
    import direction one-way: artifact_import.py imports from onboarding_v2,
    never the reverse.
    """
    analyzed = bool(session and session.import_analyzed_at)
    proposed = (session.proposed_roadmap if session else None) or {}
    brief = session.project_brief if session else None
    return {
        "analyzed": analyzed,
        "projectName": proposed.get("projectName") if analyzed else None,
        "summary": proposed.get("summary") if analyzed else None,
        "milestones": (proposed.get("milestones") or []) if analyzed else [],
        "missingFields": idea_interview.missing_fields(brief) if analyzed else [],
    }


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
    # Unifies both the chat and import paths on one signal: session.status ==
    # "completed" is already set by /chat/complete (chat) and now also by
    # artifact_import's /import/apply (import).
    chat_done = bool(session and session.status == "completed")

    # The 4th step's id depends on which build_plan sub-flow was chosen.
    # Sessions completed before this feature existed (onboarding_path is
    # still null) always went through chat, so a completed-but-unset session
    # is treated as "chat" here too — there's no other path it could have
    # taken.
    onboarding_path = session.onboarding_path if session else None
    if session and onboarding_path == "import":
        fourth_step_id = STEP_IMPORT_ARTIFACT
    elif session and (onboarding_path == "chat" or session.status == "completed"):
        fourth_step_id = STEP_IDEA_CHAT
    else:
        fourth_step_id = STEP_BUILD_PLAN

    # repo_select is auto-satisfied when there's no GitHub connection to pick
    # a repo from (github was never connected, whether skipped or just not
    # yet done) — mirrors github_connect's own skippability.
    repo_available = bool(connection)
    repo_selected = bool(session and session.selected_github_repo_full_name)
    repo_skipped = bool(session and session.repo_select_skipped_at)
    repo_done = repo_selected or repo_skipped or not repo_available

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
        (fourth_step_id, chat_done, False),
        (STEP_REPO_SELECT, repo_done, True),
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
        "onboardingPath": onboarding_path,
        "importArtifact": _import_payload(session) if session and session.import_analyzed_at else None,
        "repo": {
            "selected": session.selected_github_repo_full_name if session else None,
            "skipped": repo_skipped,
            "available": repo_available,
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


class PlanSourceRequest(BaseModel):
    source: str

    @field_validator("source")
    @classmethod
    def _source_valid(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in PLAN_SOURCES:
            raise ValueError(f"source must be one of {PLAN_SOURCES}")
        return v


@router.put("/plan-source")
async def put_plan_source(
    body: PlanSourceRequest,
    user_id: str = Depends(get_current_user_id),
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """Choose the build_plan sub-flow: chat with the AI, or import an existing
    plan. Mirrors PUT /purpose's shape exactly. No path-switching UI in v1 —
    once set and its sub-flow has started, the choice is fixed for the
    session (see docs/plans/2026-07-20-import-artifacts.md)."""
    org = await _get_org(clerk_org_id, db)
    session = await _get_or_create_session(org, user_id, db)
    session.onboarding_path = body.source
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
    brick on a GitHub outage or an LLM misjudging when the brief is done.

    Also drafts the first roadmap for the chat path here (the import path
    already created its Project synchronously in /import/apply) so the
    frontend can land the user straight on their new plan instead of the
    empty project hub. Generation is best-effort: same "never brick" rule
    applies, so a failure still completes onboarding and just leaves
    `projectId` null — the project hub's own "create new project" flow is
    the fallback in that case.
    """
    org = await _get_org(clerk_org_id, db)
    developer = await _get_developer(org, user_id, db)
    if not _profile_complete(developer):
        raise HTTPException(status_code=409, detail="profile_incomplete")

    session = await _get_session(org, db)
    project = None
    if session is not None:
        project = await db.scalar(
            select(Project).where(Project.onboarding_session_id == session.id)
        )
        if project is None and session.status == "completed" and session.project_brief:
            try:
                team = await _resolve_team(org, db)
                api_key = await idea_interview.resolve_api_key(clerk_org_id, db)
                project = await roadmap_generator.generate_roadmap(session, team, api_key, db)
            except Exception:
                logger.exception(
                    "[onboarding] roadmap generation failed for session %s", session.id
                )
                # Rollback expires every object already loaded on `db` (including
                # `org`) -- re-fetch it before touching it again below.
                await db.rollback()
                org = await _get_org(clerk_org_id, db)
                project = None

    if org.onboarding_completed_at is None:
        org.onboarding_completed_at = datetime.utcnow()
        await db.commit()

    return {
        "completedAt": org.onboarding_completed_at.isoformat(),
        "projectId": str(project.id) if project else None,
    }


class RepoRequest(BaseModel):
    repoFullName: str

    @field_validator("repoFullName")
    @classmethod
    def _repo_valid(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) > 255:
            raise ValueError("repoFullName must be 1-255 characters")
        return v


@router.put("/repo")
async def put_repo(
    body: RepoRequest,
    user_id: str = Depends(get_current_user_id),
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """Select a GitHub repo for the project.

    If a Project already exists for this session (true on the import path —
    artifact_import's /apply already ran), stamp it onto the Project
    immediately. On the chat path no Project exists yet at this point, so
    roadmap_generator.generate_roadmap copies
    session.selected_github_repo_full_name onto the new Project at creation
    time instead.
    """
    org = await _get_org(clerk_org_id, db)
    session = await _get_or_create_session(org, user_id, db)
    session.selected_github_repo_full_name = body.repoFullName

    project = await db.scalar(
        select(Project).where(Project.onboarding_session_id == session.id)
    )
    if project is not None:
        project.github_repo_full_name = body.repoFullName

    await db.commit()
    return await _build_state(org, user_id, db)


@router.post("/repo/skip")
async def skip_repo(
    user_id: str = Depends(get_current_user_id),
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """Mirrors POST /github/skip: mark the repo-select step skipped."""
    org = await _get_org(clerk_org_id, db)
    session = await _get_or_create_session(org, user_id, db)
    if session.repo_select_skipped_at is None:
        session.repo_select_skipped_at = datetime.utcnow()
    await db.commit()
    return await _build_state(org, user_id, db)
