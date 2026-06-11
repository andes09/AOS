"""
Onboarding and Invitations API router.

Endpoints
---------
GET  /api/onboarding/status
POST /api/onboarding/complete
POST /api/onboarding/confirm-team
POST /api/onboarding/import-history
GET  /api/onboarding/import-status

POST   /api/invitations
GET    /api/invitations
DELETE /api/invitations/{invitation_id}
POST   /api/invitations/accept
"""
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_user_id, get_current_org_id
from src.auth_roles import require_role
from src.config import settings
from src.database import AsyncSessionLocal, get_db
from src.integrations.jira.client import JiraClient
from src.integrations.jira.oauth import refresh_access_token
from src.models.invitation import Invitation
from src.models.jira_connection import JiraConnection
from src.models.organization import Organization
from src.models.team import Team
from src.services.encryption import decrypt
from src.services.identifier_scan_service import run_team_scan
from src.services.invitation import (
    accept_invitation,
    build_invite_link,
    create_invitation,
)
from src.services.onboarding import get_onboarding_status, import_jira_sprint_history
from src.services.scope_cop import _get_anthropic_key

logger = logging.getLogger(__name__)

onboarding_router = APIRouter(tags=["onboarding"])
invitations_router = APIRouter(tags=["invitations"])


# ---------------------------------------------------------------------------
# Response / Request models
# ---------------------------------------------------------------------------

class OnboardingStatusResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    jira_connected: bool
    board_selected: bool
    import_status: str
    imported_sprints: int | None
    onboarding_completed: bool


class CompleteOnboardingResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    completed_at: str


class ImportHistoryRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    sprint_count: int = 3


class ImportHistoryResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    status: str
    sprint_count: int


class ImportStatusResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    status: str
    imported_sprints: int | None


class ConfirmTeamMember(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    name: str
    jira_account_id: str | None = None
    capacity: int | None = None
    role: str | None = None
    seniority: str | None = None
    strengths: list[str] | None = None
    meetings: str | None = None
    email: str | None = None


class ConfirmTeamRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    members: list[ConfirmTeamMember]


class ConfirmTeamResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    upserted: int
    completed_at: str


class InviteRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    email: str
    role: str = "developer"


class InvitationItem(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    id: str
    email: str
    role: str
    status: str
    invite_link: str
    expires_at: str
    created_at: str


class CreateInvitationResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    id: str
    email: str
    role: str
    invite_link: str
    expires_at: str
    status: str


class InvitationsListResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    invitations: list[InvitationItem]


class AcceptInviteRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    token: str


class AcceptInviteResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    team_id: str
    role: str
    accepted_at: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _resolve_org_and_team(clerk_org_id: str, db: AsyncSession):
    org_result = await db.execute(
        select(Organization).where(Organization.clerk_org_id == clerk_org_id)
    )
    org = org_result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    team_result = await db.execute(
        select(Team).where(Team.organization_id == org.id).limit(1)
    )
    team = team_result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    return org, team


async def _get_jira_client(org: Organization, db: AsyncSession) -> JiraClient:
    conn_result = await db.execute(
        select(JiraConnection).where(
            JiraConnection.organization_id == org.id,
            JiraConnection.is_active == True,
        )
    )
    conn = conn_result.scalar_one_or_none()
    if not conn:
        raise HTTPException(status_code=402, detail="No active Jira connection")

    access_token = decrypt(conn.encrypted_access_token)
    if conn.expires_at and conn.expires_at < datetime.now(timezone.utc).replace(tzinfo=None):
        refresh_token = decrypt(conn.encrypted_refresh_token)
        new_tokens = await refresh_access_token(refresh_token)
        access_token = new_tokens["access_token"]

    return JiraClient(cloud_id=conn.jira_cloud_id, access_token=access_token)


# ---------------------------------------------------------------------------
# Onboarding endpoints
# ---------------------------------------------------------------------------

@onboarding_router.get("/status", response_model=OnboardingStatusResponse)
async def get_status(
    _user_id: str = Depends(get_current_user_id),
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    org, team = await _resolve_org_and_team(clerk_org_id, db)
    status_dict = await get_onboarding_status(org.id, team.id, db)
    return OnboardingStatusResponse(
        jira_connected=status_dict["jiraConnected"],
        board_selected=status_dict["boardSelected"],
        import_status=status_dict["importStatus"],
        imported_sprints=status_dict["importedSprints"],
        onboarding_completed=status_dict["onboardingCompleted"],
    )


@onboarding_router.post("/complete", response_model=CompleteOnboardingResponse)
async def complete_onboarding(
    _user_id: str = Depends(get_current_user_id),
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    org, _ = await _resolve_org_and_team(clerk_org_id, db)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    org.onboarding_completed_at = now
    await db.commit()
    return CompleteOnboardingResponse(completed_at=now.isoformat())


async def _run_identifier_scan_bg(team_id: uuid.UUID, org_id: uuid.UUID) -> None:
    """Background worker: run the bootstrap identifier scan after Jira import.

    Owns its own DB session (BackgroundTasks fire after the request scope is
    torn down). Failures are logged but never re-raised — a glossary build
    failure must not affect the user's onboarding flow.
    """
    try:
        async with AsyncSessionLocal() as bg_db:
            team = await bg_db.scalar(select(Team).where(Team.id == team_id))
            org = await bg_db.scalar(select(Organization).where(Organization.id == org_id))
            if not team or not org:
                logger.warning(
                    "identifier_scan_bg: team/org missing (team_id=%s, org_id=%s)",
                    team_id, org_id,
                )
                return

            jira_client = await _get_jira_client(org, bg_db)
            anthropic_key = await _get_anthropic_key(str(team.id), bg_db)

            logger.info("identifier_scan_bg: starting (team_id=%s)", team_id)
            summary = await run_team_scan(
                team=team, jira_client=jira_client,
                anthropic_key=anthropic_key, db=bg_db,
            )
            logger.info(
                "identifier_scan_bg: completed (team_id=%s, persisted=%d, low_conf=%d)",
                team_id,
                summary.get("identifiers_persisted", 0),
                summary.get("low_confidence_count", 0),
            )
    except Exception as exc:  # noqa: BLE001 — must not propagate
        logger.exception(
            "identifier_scan_bg: failed (team_id=%s): %s", team_id, exc
        )


@onboarding_router.post("/import-history", response_model=ImportHistoryResponse, status_code=202)
async def import_history(
    body: ImportHistoryRequest,
    background_tasks: BackgroundTasks,
    _user_id: str = Depends(get_current_user_id),
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    org, team = await _resolve_org_and_team(clerk_org_id, db)

    if not team.jira_board_id:
        raise HTTPException(status_code=422, detail="Board not selected yet")

    sprint_count = max(1, min(6, body.sprint_count or 3))

    jira_client = await _get_jira_client(org, db)

    # Set status to in_progress immediately
    team.jira_import_status = "in_progress"
    await db.flush()

    # Run import inline (no Celery)
    await import_jira_sprint_history(team, jira_client, sprint_count, db)
    await db.commit()

    # Auto-trigger the identifier bootstrap scan in the background so the
    # Team Glossary is ready when the lead lands on Settings → Glossary.
    # Runs after the request returns; failures are logged but never block UX.
    background_tasks.add_task(_run_identifier_scan_bg, team.id, org.id)

    return ImportHistoryResponse(status=team.jira_import_status, sprint_count=sprint_count)


@onboarding_router.get("/import-status", response_model=ImportStatusResponse)
async def import_status_endpoint(
    _user_id: str = Depends(get_current_user_id),
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    _, team = await _resolve_org_and_team(clerk_org_id, db)
    return ImportStatusResponse(
        status=team.jira_import_status,
        imported_sprints=team.jira_import_sprints_imported,
    )


@onboarding_router.post("/confirm-team", response_model=ConfirmTeamResponse)
async def confirm_team(
    body: ConfirmTeamRequest,
    background_tasks: BackgroundTasks,
    _user_id: str = Depends(get_current_user_id),
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """Upsert Developer records from the confirmed team member list.

    Called from the ReviewStep when the user clicks "Sync sprint history →".
    Creates or updates one Developer row per included member, then marks
    onboarding complete. The sprint-history import runs as a background task
    so the navigation to /app/sprint-planner is instant.
    """
    from src.models.developer import Developer

    org, team = await _resolve_org_and_team(clerk_org_id, db)

    existing_devs = (await db.scalars(
        select(Developer).where(Developer.team_id == team.id)
    )).all()
    by_name = {d.name: d for d in existing_devs}

    # Mark onboarding complete first — this is the critical operation.
    # Developer profile upserts are best-effort; a DB schema gap must never
    # prevent the user from accessing the app.
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    org.onboarding_completed_at = now
    await db.commit()

    upserted = 0
    try:
        for m in body.members:
            dev = by_name.get(m.name)
            if dev is None:
                dev = Developer(
                    id=uuid.uuid4(),
                    team_id=team.id,
                    name=m.name,
                )
                db.add(dev)
            if m.email is not None:
                dev.email = m.email
            if m.role is not None:
                dev.role = m.role
            if m.seniority is not None:
                dev.seniority = m.seniority
            if m.capacity is not None:
                dev.capacity_hours_per_week = m.capacity
            if m.strengths is not None:
                dev.domain_strengths = ",".join(m.strengths)
            if m.meetings is not None:
                dev.meeting_hours_bucket = m.meetings
            upserted += 1
        await db.commit()
    except Exception as exc:
        logger.warning("confirm_team: developer upsert failed (non-critical): %s", exc)
        await db.rollback()

    if team.jira_board_id:
        background_tasks.add_task(_run_identifier_scan_bg, team.id, org.id)

    return ConfirmTeamResponse(upserted=upserted, completed_at=now.isoformat())


# ---------------------------------------------------------------------------
# Invitations endpoints
# ---------------------------------------------------------------------------

@invitations_router.post("", response_model=CreateInvitationResponse, status_code=201)
async def create_invite(
    body: InviteRequest,
    user_id: str = Depends(get_current_user_id),
    clerk_org_id: str = Depends(get_current_org_id),
    _role: str = Depends(require_role("lead")),
    db: AsyncSession = Depends(get_db),
):
    allowed_roles = {"developer", "lead"}
    if body.role not in allowed_roles:
        raise HTTPException(status_code=422, detail="role must be 'developer' or 'lead'")

    org, team = await _resolve_org_and_team(clerk_org_id, db)

    # Check for existing pending invitation before creating (to detect 409 case)
    existing_result = await db.execute(
        select(Invitation).where(
            Invitation.organization_id == org.id,
            Invitation.email == body.email,
            Invitation.status == "pending",
        )
    )
    existing_inv = existing_result.scalar_one_or_none()

    invitation = await create_invitation(
        organization_id=org.id,
        team_id=team.id,
        inviter_id=user_id,
        email=body.email,
        role=body.role,
        db=db,
    )
    await db.commit()
    invite_link = build_invite_link(invitation.token, settings.frontend_url)

    if existing_inv and existing_inv.id == invitation.id:
        raise HTTPException(
            status_code=409,
            detail={
                "id": str(invitation.id),
                "email": invitation.email,
                "role": invitation.role,
                "inviteLink": invite_link,
                "expiresAt": invitation.expires_at.isoformat(),
                "status": invitation.status,
            },
        )

    return CreateInvitationResponse(
        id=str(invitation.id),
        email=invitation.email,
        role=invitation.role,
        invite_link=invite_link,
        expires_at=invitation.expires_at.isoformat(),
        status=invitation.status,
    )


@invitations_router.get("", response_model=InvitationsListResponse)
async def list_invitations(
    _user_id: str = Depends(get_current_user_id),
    clerk_org_id: str = Depends(get_current_org_id),
    _role: str = Depends(require_role("lead")),
    db: AsyncSession = Depends(get_db),
):
    try:
        org, _ = await _resolve_org_and_team(clerk_org_id, db)
    except HTTPException:
        return InvitationsListResponse(invitations=[])
    result = await db.execute(
        select(Invitation).where(Invitation.organization_id == org.id)
        .order_by(Invitation.created_at.desc())
    )
    invitations = result.scalars().all()
    items = [
        InvitationItem(
            id=str(inv.id),
            email=inv.email,
            role=inv.role,
            status=inv.status,
            invite_link=build_invite_link(inv.token, settings.frontend_url),
            expires_at=inv.expires_at.isoformat(),
            created_at=inv.created_at.isoformat(),
        )
        for inv in invitations
    ]
    return InvitationsListResponse(invitations=items)


@invitations_router.delete("/{invitation_id}")
async def revoke_invitation(
    invitation_id: uuid.UUID,
    _user_id: str = Depends(get_current_user_id),
    clerk_org_id: str = Depends(get_current_org_id),
    _role: str = Depends(require_role("lead")),
    db: AsyncSession = Depends(get_db),
):
    org, _ = await _resolve_org_and_team(clerk_org_id, db)
    result = await db.execute(
        select(Invitation).where(
            Invitation.id == invitation_id,
            Invitation.organization_id == org.id,
        )
    )
    invitation = result.scalar_one_or_none()
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")
    invitation.status = "revoked"
    await db.commit()
    return {"revoked": True}


@invitations_router.post("/accept", response_model=AcceptInviteResponse)
async def accept_invite(
    body: AcceptInviteRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    invitation = await accept_invitation(body.token, user_id, db)
    await db.commit()
    return AcceptInviteResponse(
        team_id=str(invitation.team_id),
        role=invitation.role,
        accepted_at=invitation.accepted_at.isoformat(),
    )
