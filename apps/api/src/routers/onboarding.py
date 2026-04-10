"""
Onboarding and Invitations API router.

Endpoints
---------
GET  /api/onboarding/status
POST /api/onboarding/complete
POST /api/onboarding/import-history
GET  /api/onboarding/import-status

POST   /api/invitations
GET    /api/invitations
DELETE /api/invitations/{invitation_id}
POST   /api/invitations/accept
"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_user_id, get_current_org_id
from src.auth_roles import require_role
from src.config import settings
from src.database import get_db
from src.integrations.jira.client import JiraClient
from src.integrations.jira.oauth import refresh_access_token
from src.models.invitation import Invitation
from src.models.jira_connection import JiraConnection
from src.models.organization import Organization
from src.models.team import Team
from src.services.encryption import decrypt
from src.services.invitation import (
    accept_invitation,
    build_invite_link,
    create_invitation,
)
from src.services.onboarding import get_onboarding_status, import_jira_sprint_history

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

    return JiraClient(cloud_id=conn.cloud_id, access_token=access_token)


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


@onboarding_router.post("/import-history", response_model=ImportHistoryResponse, status_code=202)
async def import_history(
    body: ImportHistoryRequest,
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
    allowed_roles = {"lead", "exec", "admin"}
    if body.role not in allowed_roles:
        raise HTTPException(status_code=422, detail="Invitations can only be sent for lead, exec, or admin roles")

    org, team = await _resolve_org_and_team(clerk_org_id, db)
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
