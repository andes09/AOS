from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from clerk_backend_api import Clerk
from clerk_backend_api.security.types import AuthenticateRequestOptions
from src.config import settings

security = HTTPBearer()

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


async def get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> str:
    """Verify Clerk JWT and return the user ID (sub claim)."""
    payload = await _verify_token(credentials)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
        )
    return user_id


async def get_current_org_id(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> str:
    """Verify Clerk JWT and return the Clerk organisation ID (org_id claim)."""
    payload = await _verify_token(credentials)
    org_id = payload.get("org_id")
    if not org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No organisation context — sign in with an organisation account.",
        )
    return org_id
