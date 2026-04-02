from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException, status
from src.models.organization import Organization
from src.services.encryption import decrypt


async def get_anthropic_key(clerk_org_id: str, db: AsyncSession) -> str:
    """Fetch and decrypt the org's Anthropic API key. Raises HTTP 402 if not configured."""
    org = await db.scalar(select(Organization).where(Organization.clerk_org_id == clerk_org_id))
    if not org or not org.encrypted_anthropic_key:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="No Anthropic API key configured. Please add your key in Settings.",
        )
    return decrypt(org.encrypted_anthropic_key)
