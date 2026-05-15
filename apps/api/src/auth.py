from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from clerk_backend_api import Clerk
from clerk_backend_api.security.types import AuthenticateRequestOptions
from src.config import settings
from src.database import get_db
from src.models.developer import AppRole, Developer
from src.models.organization import Organization
from src.models.team import Team

security = HTTPBearer(auto_error=False)

_clerk = Clerk(bearer_auth=settings.clerk_secret_key)


class _BearerRequest:
    """Minimal request shim that satisfies the Requestish protocol."""
    def __init__(self, token: str):
        self.headers = {"Authorization": f"Bearer {token}"}


async def _verify_token(credentials: HTTPAuthorizationCredentials) -> dict:
    """Verify Clerk JWT via JWKS and return the claims payload."""
    state = await _clerk.authenticate_request_async(
        _BearerRequest(credentials.credentials),
        AuthenticateRequestOptions(secret_key=settings.clerk_secret_key),
    )
    if not state.is_signed_in or state.payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    return state.payload


def _simulator_bypass_active(request: Request) -> bool:
    """True when env=local, a simulator key is configured, and the caller presented the matching header."""
    if settings.environment != "local" or not settings.simulator_api_key:
        return False
    return request.headers.get("X-Simulator-Key", "") == settings.simulator_api_key


async def _get_first_admin_user(db: AsyncSession) -> tuple[str, str]:
    """Return (clerk_user_id, clerk_org_id) for the first admin Developer. Raises 401 if none exists."""
    result = await db.execute(
        select(Developer.clerk_user_id, Organization.clerk_org_id)
        .join(Team, Developer.team_id == Team.id)
        .join(Organization, Team.organization_id == Organization.id)
        .where(
            Developer.app_role == AppRole.ADMIN.value,
            Developer.clerk_user_id.is_not(None),
        )
        .limit(1)
    )
    row = result.first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Simulator bypass: no admin user found in database",
        )
    return row[0], row[1]


async def get_current_user_id(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> str:
    """Verify Clerk JWT and return the user ID (sub claim). Honours the simulator bypass in local env."""
    if _simulator_bypass_active(request):
        user_id, _ = await _get_first_admin_user(db)
        return user_id
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    payload = await _verify_token(credentials)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
        )
    return user_id


async def get_current_org_id(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> str:
    """Verify Clerk JWT and return the Clerk organisation ID (org_id claim). Honours the simulator bypass in local env."""
    if _simulator_bypass_active(request):
        _, org_id = await _get_first_admin_user(db)
        return org_id
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    payload = await _verify_token(credentials)
    org_id = payload.get("org_id")
    if not org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No organisation context — sign in with an organisation account.",
        )
    return org_id
