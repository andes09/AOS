"""
Projects — the Project Hub. Lists an org's projects (Active/Finished/Archived),
enforces the org's project cap, and drives creation of a *new* project through
the same chat -> brief -> generate machinery onboarding v2 uses, but decoupled
from org onboarding (no GitHub/profile steps — those are already satisfied at
the org level by the time a second project gets created).

GET    /api/projects                          -> the org's projects (optional ?status=)
GET    /api/projects/{project_id}              -> single project's metadata
POST   /api/projects                           -> starts creation; 422 if over the cap
PATCH  /api/projects/{project_id}               -> rename / status transition

Creation sub-resource (no Project row exists yet -- keyed by session, not project):
PUT    /api/projects/sessions/{session_id}/purpose
GET    /api/projects/sessions/{session_id}/chat
POST   /api/projects/sessions/{session_id}/chat/message
POST   /api/projects/sessions/{session_id}/generate

Import-based creation (docs/plans/2026-07-20-import-artifacts.md) is a
fast-follow that will add a parallel /sessions/{id}/import/analyze + /apply
pair under this same prefix -- deliberately not built here.
"""

import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.auth import get_current_org_id, get_current_user_id
from src.database import get_db
from src.models.milestone import Milestone
from src.models.onboarding_session import OnboardingMessage, OnboardingSession
from src.models.organization import Organization
from src.models.project import Project, ProjectStatus
from src.models.team import Team
from src.routers.project_common import _get_org, _owned_project
from src.services import idea_interview, roadmap_generator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects", tags=["projects"])

_VALID_STATUSES = {s.value for s in ProjectStatus}

# active <-> finished, active <-> archived, finished -> archived. Deliberately
# NOT archived -> finished: restoring to active first keeps every transition a
# single explicit user intent (see docs/plans/2026-07-20-project-hub.md).
_ALLOWED_TRANSITIONS = {
    ("active", "finished"),
    ("finished", "active"),
    ("active", "archived"),
    ("archived", "active"),
    ("finished", "archived"),
}

_PROJECT_PURPOSES = ("hobby", "startup", "learning")


# ─── serialization ──────────────────────────────────────────────────────────────
def _project_summary_json(project: Project) -> dict:
    return {
        "id": str(project.id),
        "name": project.name,
        "summary": project.summary,
        "purpose": project.purpose,
        "status": project.status,
        "createdAt": project.created_at.isoformat() if project.created_at else None,
        "updatedAt": project.updated_at.isoformat() if project.updated_at else None,
        "hasRoadmap": bool(project.milestones),
    }


# ─── shared lookups ─────────────────────────────────────────────────────────────
async def _owned_session(session_id: uuid.UUID, org: Organization, db: AsyncSession) -> OnboardingSession:
    """Load a creation session, ensuring it belongs to the caller's org. 404 otherwise.

    Ownership check is against the session directly (not via a Project — no
    Project exists yet at this point in the flow).
    """
    session = await db.scalar(
        select(OnboardingSession).where(
            OnboardingSession.id == session_id, OnboardingSession.organization_id == org.id
        )
    )
    if session is None:
        raise HTTPException(status_code=404, detail="session_not_found")
    return session


async def _project_count(org: Organization, db: AsyncSession) -> int:
    """All of the org's projects, regardless of status -- archiving is a
    visibility flag, not a resource-freeing operation, so it must not be a
    loophole around the cap."""
    return (
        await db.scalar(
            select(func.count(Project.id))
            .join(Team, Project.team_id == Team.id)
            .where(Team.organization_id == org.id)
        )
    ) or 0


async def _resolve_team(org: Organization, db: AsyncSession) -> Team:
    team = await db.scalar(
        select(Team).where(Team.organization_id == org.id).order_by(Team.created_at)
    )
    if team is None:
        raise HTTPException(status_code=409, detail="no_team_for_org")
    return team


# ─── list / detail / rename / status ─────────────────────────────────────────────
@router.get("")
async def list_projects(
    status: str | None = None,
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    if status is not None and status not in _VALID_STATUSES:
        raise HTTPException(status_code=422, detail=f"status must be one of {sorted(_VALID_STATUSES)}")

    org = await _get_org(clerk_org_id, db)
    query = (
        select(Project)
        .join(Team, Project.team_id == Team.id)
        .where(Team.organization_id == org.id)
        .options(selectinload(Project.milestones))
        .order_by(Project.created_at)
    )
    if status is not None:
        query = query.where(Project.status == status)

    projects = (await db.execute(query)).scalars().all()
    return {"projects": [_project_summary_json(p) for p in projects]}


@router.get("/{project_id}")
async def get_project(
    project_id: uuid.UUID,
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    org = await _get_org(clerk_org_id, db)
    project = await _owned_project(project_id, org, db)
    return _project_summary_json(project)


class ProjectUpdateRequest(BaseModel):
    name: str | None = None
    status: str | None = None

    @field_validator("name")
    @classmethod
    def _valid_name(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if not (1 <= len(v) <= 255):
                raise ValueError("name must be 1-255 characters")
        return v

    @field_validator("status")
    @classmethod
    def _valid_status(cls, v: str | None) -> str | None:
        if v is not None and v not in _VALID_STATUSES:
            raise ValueError(f"status must be one of {sorted(_VALID_STATUSES)}")
        return v


@router.patch("/{project_id}")
async def update_project(
    project_id: uuid.UUID,
    body: ProjectUpdateRequest,
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    org = await _get_org(clerk_org_id, db)
    project = await _owned_project(project_id, org, db)

    if body.status is not None and body.status != project.status:
        if (project.status, body.status) not in _ALLOWED_TRANSITIONS:
            raise HTTPException(status_code=409, detail="invalid_status_transition")
        project.status = body.status

    if body.name is not None:
        project.name = body.name

    await db.commit()
    await db.refresh(project)
    project = await _owned_project(project_id, org, db)  # re-eager-load milestones for hasRoadmap
    return _project_summary_json(project)


# ─── creation: POST /api/projects starts it, /sessions/{id}/... drives it ───────
@router.post("", status_code=201)
async def start_project_creation(
    user_id: str = Depends(get_current_user_id),
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    org = await _get_org(clerk_org_id, db)

    if org.max_projects is not None and await _project_count(org, db) >= org.max_projects:
        raise HTTPException(status_code=422, detail="project_limit_reached")

    session = OnboardingSession(
        organization_id=org.id, created_by_user_id=user_id, status="in_progress"
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return {"sessionId": str(session.id)}


class PurposeRequest(BaseModel):
    purpose: str

    @field_validator("purpose")
    @classmethod
    def _purpose_valid(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in _PROJECT_PURPOSES:
            raise ValueError(f"purpose must be one of {_PROJECT_PURPOSES}")
        return v


@router.put("/sessions/{session_id}/purpose")
async def put_session_purpose(
    session_id: uuid.UUID,
    body: PurposeRequest,
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    org = await _get_org(clerk_org_id, db)
    session = await _owned_session(session_id, org, db)
    session.project_purpose = body.purpose
    await db.commit()
    return {"sessionId": str(session.id), "purpose": session.project_purpose}


async def _session_chat_payload(session: OnboardingSession, db: AsyncSession) -> dict:
    rows = (
        await db.execute(
            select(OnboardingMessage)
            .where(OnboardingMessage.session_id == session.id)
            .order_by(OnboardingMessage.seq)
        )
    ).scalars().all()
    return {
        "sessionId": str(session.id),
        "status": session.status,
        "messages": [
            {
                "id": str(m.id),
                "role": m.role,
                "content": m.content,
                "createdAt": m.created_at.isoformat() if m.created_at else None,
            }
            for m in rows
        ],
        "brief": session.project_brief,
        "briefComplete": session.brief_complete,
    }


@router.get("/sessions/{session_id}/chat")
async def get_session_chat(
    session_id: uuid.UUID,
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """Idempotently seeds the opening assistant message on first read, then
    returns the transcript so far -- mirrors roadmap.py's refine-chat GET."""
    org = await _get_org(clerk_org_id, db)
    session = await _owned_session(session_id, org, db)

    count = await db.scalar(
        select(func.count(OnboardingMessage.id)).where(OnboardingMessage.session_id == session.id)
    )
    if not count:
        db.add(OnboardingMessage(
            session_id=session.id,
            role="assistant",
            content=idea_interview.opening_message(session.project_purpose),
            seq=0,
        ))
        await db.commit()

    return await _session_chat_payload(session, db)


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


async def _chat_event_stream(session: OnboardingSession, content: str, api_key: str, db: AsyncSession):
    """SSE generator: `token` events while the model replies, then `brief`,
    then `done` -- or a terminal `error`. Same protocol as onboarding_v2.py
    and roadmap.py's chat endpoints."""
    queue: asyncio.Queue = asyncio.Queue()

    async def on_token(text: str) -> None:
        await queue.put(("token", {"text": text}))

    async def runner() -> None:
        try:
            result = await idea_interview.run_interview_turn(session, content, api_key, db, on_token)
            await queue.put(("brief", {
                "brief": result["brief"],
                "missingFields": result["missing_fields"],
                "briefComplete": result["brief_complete"],
            }))
            await queue.put(("done", {"messageId": result["message_id"], "status": result["status"]}))
        except Exception as e:  # noqa: BLE001 — surface any failure to the client
            logger.exception("[project-chat] turn failed for session %s", session.id)
            await queue.put(("error", {"message": str(e) or "Interview turn failed"}))
        finally:
            await queue.put(None)

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


@router.post("/sessions/{session_id}/chat/message")
async def send_session_chat_message(
    session_id: uuid.UUID,
    body: ChatMessageRequest,
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    org = await _get_org(clerk_org_id, db)
    session = await _owned_session(session_id, org, db)
    if not session.project_purpose:
        raise HTTPException(status_code=409, detail="purpose_not_set")
    if session.status == "completed":
        raise HTTPException(status_code=409, detail="chat_completed")

    user_count = await db.scalar(
        select(func.count(OnboardingMessage.id)).where(
            OnboardingMessage.session_id == session.id, OnboardingMessage.role == "user"
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


@router.post("/sessions/{session_id}/generate")
async def generate_project(
    session_id: uuid.UUID,
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    org = await _get_org(clerk_org_id, db)
    session = await _owned_session(session_id, org, db)

    # Idempotent: a retried call (e.g. a flaky network on the client) returns
    # the already-generated project instead of erroring on the 1:1 FK.
    existing = await db.scalar(select(Project).where(Project.onboarding_session_id == session.id))
    if existing is not None:
        existing = await _owned_project(existing.id, org, db)
        return _project_summary_json(existing)

    if not session.project_brief:
        raise HTTPException(
            status_code=409,
            detail="Add some project details first — there's no project brief to plan from yet.",
        )

    # Re-check the cap: time may have passed (and other projects may have been
    # created) between POST /api/projects and this call.
    if org.max_projects is not None and await _project_count(org, db) >= org.max_projects:
        raise HTTPException(status_code=422, detail="project_limit_reached")

    team = await _resolve_team(org, db)
    api_key = await idea_interview.resolve_api_key(clerk_org_id, db)

    try:
        project = await roadmap_generator.generate_roadmap(session, team, api_key, db)
    except ValueError as exc:  # bad key
        raise HTTPException(status_code=402, detail=str(exc))
    except RuntimeError as exc:  # upstream / model failure
        raise HTTPException(status_code=502, detail=str(exc))

    project = await _owned_project(project.id, org, db)
    return _project_summary_json(project)
