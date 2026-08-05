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
PUT    /api/onboarding/v2/tech-stack     → save known tech stack, or that the founder is new (flag-gated)
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

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_user_id, get_current_org_id
from src.config import settings
from src.database import get_db
from src.integrations.github.client import GithubClient
from src.integrations.github.router import _get_valid_access_token, get_active_connection
from src.models.developer import Developer
from src.models.github_connection import GithubConnection
from src.models.onboarding_session import OnboardingMessage, OnboardingSession
from src.models.organization import Organization
from src.models.project import Project
from src.models.team import Team
from src.services import idea_interview, roadmap_generator
from src.services.llm_errors import LLMRateLimitError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/onboarding/v2", tags=["onboarding-v2"])

_PHONE_RE = re.compile(r"^\+?[0-9][0-9\s\-().]{5,30}$")

STEP_PROFILE = "profile"
STEP_PURPOSE = "purpose"
# Gated behind experimental.tech_stack_step (see PUT /tech-stack below) — only
# inserted into _build_state's step list when the flag is on, so sessions
# started while it's off see the unchanged legacy step order.
STEP_TECH_STACK = "tech_stack"
STEP_IDEA_CHAT = "idea_chat"
# The 4th step's id while no build_plan sub-flow has been chosen yet (see
# PUT /plan-source below). Additive, not a rename: STEP_IDEA_CHAT's own
# endpoints are untouched, this is just the new pre-choice state exposed at
# the same position in `steps[]`.
STEP_BUILD_PLAN = "build_plan"
STEP_IMPORT_ARTIFACT = "import_artifact"
# Connect GitHub, then pick/create a repo — one skippable step covering both
# halves (see `github_done`/`repo_done` below). Deliberately placed after
# build_plan rather than at the very front: by this point onboardingPath is
# already known, so the repo picker can be path-aware (offer "create a repo"
# only on the chat/greenfield path) from the moment it's shown.
STEP_GITHUB_REPO = "github_repo"
# Gated behind the plan_review flag — the last step before "done". The
# founder reviews (and can regenerate) the drafted roadmap before it's
# committed, instead of it being generated silently at POST /complete. Only
# inserted into _build_state's step list when the flag is on, so sessions
# started while it's off finish exactly as before.
STEP_PLAN_REVIEW = "plan_review"

PROJECT_PURPOSES = ("hobby", "startup", "learning")
PLAN_SOURCES = ("chat", "import")
TECH_EXPERIENCES = ("experienced", "new")


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


def _maybe_prewarm_roadmap(session: OnboardingSession) -> None:
    """Fire a background roadmap generation the moment the interview
    completes, so POST /plan/draft usually finds it already sitting there
    instead of paying for the Groq call on the review step's critical path
    (see services/roadmap_generator.prewarm_roadmap). Best-effort: an enqueue
    failure (e.g. Redis briefly down) must never break onboarding.
    """
    if not settings.is_feature_enabled("plan_review") or not session.project_brief:
        return
    try:
        roadmap_generator.prewarm_roadmap.delay(str(session.id))
    except Exception:
        logger.exception(
            "[onboarding] failed to enqueue roadmap prewarm for session %s", session.id
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
    tech_stack_step_enabled = settings.is_feature_enabled("experimental.tech_stack_step")
    tech_stack_done = bool(session and session.tech_experience)
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

    # The repo half of STEP_GITHUB_REPO is auto-satisfied when there's no
    # GitHub connection to pick a repo from (github was never connected,
    # whether skipped or just not yet done) — so skipping the GitHub half
    # alone completes the whole merged step in one action.
    repo_available = bool(connection)
    repo_selected = bool(session and session.selected_github_repo_full_name)
    repo_skipped = bool(session and session.repo_select_skipped_at)
    repo_done = repo_selected or repo_skipped or not repo_available

    # The project drafted for this session, if any. On the chat path it doesn't
    # exist until the plan-review step drafts it (POST /plan/draft) or, with the
    # step off, until POST /complete; on the import path it already exists.
    project = None
    if session:
        project = await db.scalar(
            select(Project).where(Project.onboarding_session_id == session.id)
        )
    plan_review_enabled = settings.is_feature_enabled("plan_review")
    plan_confirmed = bool(session and session.plan_confirmed_at)

    # API repo-creation is only possible on Organization installs (see
    # create_repo / integrations/github/client.create_repo). Personal-account
    # installs fall back to connect-only. Gated behind the repo_create flag.
    repo_create_enabled = settings.is_feature_enabled("repo_create")
    can_create_repo = (
        repo_create_enabled and bool(connection) and connection.account_type == "Organization"
    )

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

    # Both halves must be done for the merged step to complete — see the
    # repo_done/github_done cases documented on STEP_GITHUB_REPO above.
    github_repo_done = github_done and repo_done

    done_flags = [
        (STEP_PROFILE, profile_done, False),
        (STEP_PURPOSE, purpose_done, False),
        *([(STEP_TECH_STACK, tech_stack_done, False)] if tech_stack_step_enabled else []),
        (fourth_step_id, chat_done, False),
        (STEP_GITHUB_REPO, github_repo_done, True),
        *([(STEP_PLAN_REVIEW, plan_confirmed, False)] if plan_review_enabled else []),
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
        "techStack": {
            "stack": (session.known_tech_stack if session else None) or [],
            "experience": session.tech_experience if session else None,
            "complete": tech_stack_done,
        },
        "ideaChat": {
            "sessionId": str(session.id) if session else None,
            "status": session.status if session else "not_started",
            "messageCount": message_count,
            "brief": session.project_brief if session else None,
            "briefComplete": bool(session and session.brief_complete),
            "awaitingConfirmation": bool(session and session.awaiting_confirmation),
        },
        "onboardingPath": onboarding_path,
        "importArtifact": _import_payload(session) if session and session.import_analyzed_at else None,
        "repo": {
            "selected": session.selected_github_repo_full_name if session else None,
            "skipped": repo_skipped,
            "available": repo_available,
            # Whether the chat path can offer "create a new repo" (org install
            # + flag on), and the org login repos would be created under.
            "canCreate": can_create_repo,
            "ownerLogin": connection.github_login if connection else None,
        },
        # The drafted project's id, so the plan-review step knows which
        # roadmap to fetch/regenerate. Null until a project exists.
        "projectId": str(project.id) if project else None,
        "planReview": {
            "confirmed": plan_confirmed,
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


class TechStackRequest(BaseModel):
    stack: list[str]
    experience: str

    @field_validator("experience")
    @classmethod
    def _experience_valid(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in TECH_EXPERIENCES:
            raise ValueError(f"experience must be one of {TECH_EXPERIENCES}")
        return v

    @field_validator("stack")
    @classmethod
    def _stack_valid(cls, v: list[str]) -> list[str]:
        return [s.strip() for s in v if s.strip()]

    @model_validator(mode="after")
    def _mutually_exclusive(self) -> "TechStackRequest":
        # "new" (I'm new to this) and a picked stack are mutually exclusive —
        # enforced here, not just in the UI, since this deterministically
        # steers the roadmap generator's prompt (see _tech_stack_prompt).
        if self.experience == "new" and self.stack:
            raise ValueError("stack must be empty when experience is 'new'")
        if self.experience == "experienced" and not self.stack:
            raise ValueError("stack must be non-empty when experience is 'experienced'")
        return self


def _require_tech_stack_step_enabled() -> None:
    if not settings.is_feature_enabled("experimental.tech_stack_step"):
        raise HTTPException(status_code=404, detail="not_found")


def _require_plan_review_enabled() -> None:
    if not settings.is_feature_enabled("plan_review"):
        raise HTTPException(status_code=404, detail="not_found")


def _require_repo_create_enabled() -> None:
    if not settings.is_feature_enabled("repo_create"):
        raise HTTPException(status_code=404, detail="not_found")


@router.put("/tech-stack", dependencies=[Depends(_require_tech_stack_step_enabled)])
async def put_tech_stack(
    body: TechStackRequest,
    user_id: str = Depends(get_current_user_id),
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """Save the founder's known tech stack, or that they're new to this.
    Collected explicitly (not chat-extracted), same reasoning as PUT /purpose —
    too load-bearing for the roadmap generator to leave to LLM inference."""
    org = await _get_org(clerk_org_id, db)
    session = await _get_or_create_session(org, user_id, db)
    session.known_tech_stack = body.stack
    session.tech_experience = body.experience
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
        "awaitingConfirmation": session.awaiting_confirmation,
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
            "awaitingConfirmation": False,
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
                "awaitingConfirmation": result["awaiting_confirmation"],
            }))
            await queue.put(("done", {
                "messageId": result["message_id"],
                "status": result["status"],
            }))
            if result["status"] == "completed":
                _maybe_prewarm_roadmap(session)
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


async def _plan_draft_event_stream(
    session: OnboardingSession, team: Team, api_key: str, db: AsyncSession
):
    """SSE generator: `progress` events (0-95%) while the roadmap streams in
    from Groq, then `done` — or a terminal `error`. Only used on the
    actually-generating path; see draft_plan for the idempotent fast path."""
    queue: asyncio.Queue = asyncio.Queue()

    async def on_progress(pct: int) -> None:
        await queue.put(("progress", {"pct": pct}))

    async def runner() -> None:
        try:
            project = await roadmap_generator.generate_roadmap_once(
                session, team, api_key, db, on_progress
            )
            await queue.put(("done", {"projectId": str(project.id)}))
        except LLMRateLimitError:
            # Distinct from a generic failure: nothing is wrong with the brief
            # and there's nothing to retry right now, so the step says so
            # instead of offering a regenerate that would fail the same way.
            logger.warning(
                "[onboarding] plan draft rate-limited for session %s", session.id
            )
            await db.rollback()
            await queue.put(("error", {"message": "rate_limited"}))
        except Exception:
            logger.exception(
                "[onboarding] plan draft generation failed for session %s", session.id
            )
            await db.rollback()
            await queue.put(("error", {"message": "roadmap_generation_failed"}))
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
        session.awaiting_confirmation = False
        session.completed_at = datetime.utcnow()
        await db.commit()
        _maybe_prewarm_roadmap(session)
    return await _build_state(org, user_id, db)


@router.post("/chat/reopen")
async def reopen_chat(
    user_id: str = Depends(get_current_user_id),
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """Recovery path for a session that reached "completed" without a usable
    brief — e.g. `/chat/complete` overrode a too-short interview, or every
    extraction call failed. Without this, IdeaChatStep's disabled input left
    the founder stuck: no way to add detail, and /plan/draft 409s forever.

    Refuses once a project already exists for this session: at that point
    the interview transcript is historical record, not something generation
    reads from, so reopening it wouldn't do anything.
    """
    org = await _get_org(clerk_org_id, db)
    session = await _get_session(org, db)
    if session is None:
        raise HTTPException(status_code=409, detail="chat_not_started")
    if session.status == "completed":
        project = await db.scalar(
            select(Project).where(Project.onboarding_session_id == session.id)
        )
        if project is not None:
            raise HTTPException(status_code=409, detail="project_already_created")
        session.status = "in_progress"
        session.completed_at = None
        session.awaiting_confirmation = False
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
            except Exception as exc:
                # A rate limit is expected traffic, not a defect — log it flat
                # so it doesn't read as a bug in the traces.
                if isinstance(exc, LLMRateLimitError):
                    logger.warning(
                        "[onboarding] roadmap generation rate-limited for session %s", session.id
                    )
                else:
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


class RepoCreateRequest(BaseModel):
    name: str
    private: bool = True

    @field_validator("name")
    @classmethod
    def _name_valid(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) > 100:
            raise ValueError("name must be 1-100 characters")
        if not re.match(r"^[A-Za-z0-9._-]+$", v):
            raise ValueError("name may only contain letters, numbers, '.', '_' and '-'")
        return v


@router.post("/repo/create", dependencies=[Depends(_require_repo_create_enabled)])
async def create_repo(
    body: RepoCreateRequest,
    user_id: str = Depends(get_current_user_id),
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """Create a new GitHub repo and select it for the project (greenfield chat
    path). Only works on Organization installs — a personal-account
    installation token can't create repos, so those are rejected with 422 and
    the UI falls back to connect-only (see the repo.canCreate flag in
    _build_state, and github_app_repo_create_constraint). Stamps the new repo
    onto the session/Project exactly like PUT /repo.
    """
    org = await _get_org(clerk_org_id, db)
    connection = await get_active_connection(org, db)
    if connection is None or connection.installation_id is None:
        raise HTTPException(status_code=409, detail="github_not_connected")
    if connection.account_type != "Organization":
        raise HTTPException(status_code=422, detail="repo_create_requires_org_install")

    session = await _get_or_create_session(org, user_id, db)
    token = await _get_valid_access_token(connection, db)
    client = GithubClient(token)
    try:
        repo = await client.create_repo(connection.github_login, body.name, body.private)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 422:
            # Name already taken / invalid on GitHub's side.
            raise HTTPException(status_code=422, detail="repo_name_unavailable")
        raise HTTPException(status_code=502, detail="github_repo_create_failed")
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="github_repo_create_failed")

    full_name = repo["full_name"]
    session.selected_github_repo_full_name = full_name
    project = await db.scalar(
        select(Project).where(Project.onboarding_session_id == session.id)
    )
    if project is not None:
        project.github_repo_full_name = full_name

    await db.commit()
    return await _build_state(org, user_id, db)


@router.post("/plan/draft", dependencies=[Depends(_require_plan_review_enabled)])
async def draft_plan(
    user_id: str = Depends(get_current_user_id),
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """Ensure a drafted roadmap exists so the plan-review step can show it, and
    return its projectId.

    Idempotent. On the import path the Project already exists (created by
    /import/apply), so this is a no-op lookup returning plain JSON. On the
    chat path no Project exists yet, so this is where generation actually
    happens — moved out of POST /complete so the founder reviews the plan
    *before* it's committed. That generating case streams back as SSE
    (`progress`/`done`/`error` events, see _plan_draft_event_stream) so the
    UI can show real generation progress instead of a fake timer; team/key
    resolution still happen synchronously first so those failures stay plain
    JSON errors rather than being swallowed into a generic stream `error`.

    Unlike /complete's best-effort generation, a failure here is terminal for
    this call: the review UI surfaces it and offers "continue anyway", which
    falls through to /complete's own generation as a second chance (and the
    project-hub fallback if that also fails). The flow still never bricks.
    """
    org = await _get_org(clerk_org_id, db)
    session = await _get_session(org, db)
    if session is None:
        raise HTTPException(status_code=409, detail="no_session")

    project = await db.scalar(
        select(Project).where(Project.onboarding_session_id == session.id)
    )
    if project is not None:
        return {"projectId": str(project.id)}

    if session.status != "completed" or not session.project_brief:
        raise HTTPException(status_code=409, detail="brief_incomplete")

    team = await _resolve_team(org, db)
    api_key = await idea_interview.resolve_api_key(clerk_org_id, db)
    return StreamingResponse(
        _plan_draft_event_stream(session, team, api_key, db),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/plan/confirm", dependencies=[Depends(_require_plan_review_enabled)])
async def confirm_plan(
    user_id: str = Depends(get_current_user_id),
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """Mark the drafted roadmap accepted, completing the plan-review step. Safe
    to call even if the draft failed (the "continue anyway" path) — it just
    advances the flow to `done`."""
    org = await _get_org(clerk_org_id, db)
    session = await _get_or_create_session(org, user_id, db)
    if session.plan_confirmed_at is None:
        session.plan_confirmed_at = datetime.utcnow()
    await db.commit()
    return await _build_state(org, user_id, db)
