import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.invitation import Invitation
from src.models.developer import Developer


async def create_invitation(
    organization_id: uuid.UUID,
    team_id: uuid.UUID,
    inviter_id: str,
    email: str,
    role: str,
    db: AsyncSession,
) -> Invitation:
    """
    Creates an Invitation with a secure token valid for 7 days.
    Idempotent on (organization_id, email): returns the existing pending invitation
    if one already exists for this email in this org.
    """
    # Check for existing pending invitation
    existing = await db.execute(
        select(Invitation).where(
            Invitation.organization_id == organization_id,
            Invitation.email == email,
            Invitation.status == "pending",
        )
    )
    existing_inv = existing.scalar_one_or_none()
    if existing_inv:
        return existing_inv

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    invitation = Invitation(
        id=uuid.uuid4(),
        organization_id=organization_id,
        team_id=team_id,
        inviter_id=inviter_id,
        email=email,
        role=role,
        token=secrets.token_urlsafe(32),
        status="pending",
        expires_at=now + timedelta(days=7),
        created_at=now,
    )
    db.add(invitation)
    await db.flush()
    return invitation


async def accept_invitation(token: str, clerk_user_id: str, db: AsyncSession) -> Invitation:
    """
    Validates the token (exists, status=pending, not expired).
    Accepts the invitation and upserts a Developer row for the accepting user.
    Raises 404 if token not found.
    Raises 410 if expired or already accepted/revoked.
    """
    result = await db.execute(
        select(Invitation).where(Invitation.token == token)
    )
    invitation = result.scalar_one_or_none()
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if invitation.status != "pending":
        raise HTTPException(status_code=410, detail="Invitation already used or revoked")
    if invitation.expires_at < now:
        raise HTTPException(status_code=410, detail="Invitation has expired")

    invitation.status = "accepted"
    invitation.accepted_at = now

    # Upsert Developer row
    dev_result = await db.execute(
        select(Developer).where(Developer.clerk_user_id == clerk_user_id)
    )
    developer = dev_result.scalar_one_or_none()
    if not developer:
        developer = Developer(
            id=uuid.uuid4(),
            team_id=invitation.team_id,
            clerk_user_id=clerk_user_id,
            name=clerk_user_id,  # display name updated on next login
            app_role=invitation.role,
        )
        db.add(developer)
    else:
        developer.team_id = invitation.team_id
        developer.app_role = invitation.role

    await db.flush()
    return invitation


def build_invite_link(token: str, frontend_base_url: str) -> str:
    return f"{frontend_base_url}/invite?token={token}"
