"""
Invitations API router.

Endpoints
---------
POST   /api/invitations
GET    /api/invitations
DELETE /api/invitations/{invitation_id}
POST   /api/invitations/accept
"""
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_user_id, get_current_org_id
from src.auth_roles import require_role
from src.config import settings
from src.database import get_db
from src.models.invitation import Invitation
from src.models.organization import Organization
from src.models.team import Team
from src.services.invitation import (
    accept_invitation,
    build_invite_link,
    create_invitation,
)

logger = logging.getLogger(__name__)

invitations_router = APIRouter(tags=["invitations"])


# ---------------------------------------------------------------------------
# Response / Request models
# ---------------------------------------------------------------------------

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
    except HTTPException as exc:
        # Deliberately degrades to an empty list rather than erroring, so the
        # settings page still renders. But the exception never propagates to
        # the central handler, so without this line an org that can't be
        # resolved looks identical to an org with no invitations.
        logger.warning(
            "list_invitations: could not resolve org, returning empty list",
            extra={"clerk_org_id": clerk_org_id, "status": exc.status_code, "detail": exc.detail},
        )
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
