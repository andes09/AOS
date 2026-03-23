"""
Organizations API router.

Endpoints
---------
POST /api/organizations
    Idempotent org + default team provisioning.
    Called by the frontend once after first sign-in.
    Returns 201 on creation, 200 if org already existed.
"""
import uuid
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_org_id
from src.database import get_db
from src.models.organization import Organization
from src.models.team import Team
from src.services.encryption import encrypt

router = APIRouter(prefix="/api/organizations", tags=["organizations"])
settings_router = APIRouter(prefix="/api/settings", tags=["settings"])


class AnthropicKeyRequest(BaseModel):
    key: str


@settings_router.post("/anthropic-key")
async def save_anthropic_key(
    body: AnthropicKeyRequest,
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    org = await db.scalar(select(Organization).where(Organization.clerk_org_id == clerk_org_id))
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")
    org.encrypted_anthropic_key = encrypt(body.key.strip())
    await db.commit()
    return {"saved": True}


class ProvisionRequest(BaseModel):
    name: str


@router.post("")
async def provision_organization(
    body: ProvisionRequest,
    response: Response,
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """Upsert org + default team. Idempotent."""
    org = await db.scalar(
        select(Organization).where(Organization.clerk_org_id == clerk_org_id)
    )

    if org:
        team = await db.scalar(select(Team).where(Team.organization_id == org.id))
        if team is None:
            raise HTTPException(status_code=500, detail="Organisation exists but has no default team.")
        response.status_code = 200
        return {"orgId": str(org.id), "teamId": str(team.id), "isNew": False}

    try:
        org = Organization(
            id=uuid.uuid4(),
            clerk_org_id=clerk_org_id,
            name=body.name,
            slug=clerk_org_id,  # use clerk_org_id as slug — guaranteed unique
            use_managed_key=False,
        )
        db.add(org)
        await db.flush()  # get org.id before creating team

        team = Team(
            id=uuid.uuid4(),
            organization_id=org.id,
            name=f"{body.name} Team",
            sprint_length_days=14,
        )
        db.add(team)
        await db.commit()

        response.status_code = 201
        return {"orgId": str(org.id), "teamId": str(team.id), "isNew": True}

    except IntegrityError:
        # Concurrent request already created the org (e.g. React Strict Mode double-fire).
        # Roll back and return the existing record as if it were a normal idempotent hit.
        await db.rollback()
        org = await db.scalar(select(Organization).where(Organization.clerk_org_id == clerk_org_id))
        if org is None:
            raise HTTPException(status_code=500, detail="Organisation creation failed.")
        team = await db.scalar(select(Team).where(Team.organization_id == org.id))
        if team is None:
            raise HTTPException(status_code=500, detail="Organisation exists but has no default team.")
        response.status_code = 200
        return {"orgId": str(org.id), "teamId": str(team.id), "isNew": False}
