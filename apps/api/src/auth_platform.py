"""
Platform-admin auth — a cross-org check, kept separate from auth_roles.py
(that module is intrinsically org-scoped; this is a different kind of check).

`require_platform_admin` verifies the caller's Clerk user ID (via
`get_current_user_id`, which doesn't require an org claim, unlike
`get_current_org_id`) against a Clerk-user-ID env allowlist
(`settings.platform_admin_ids` — comma-separated `PLATFORM_ADMIN_USER_IDS`).
Empty by default, so this denies everyone until explicitly configured.
"""

from fastapi import Depends, HTTPException, status

from src.auth import get_current_user_id
from src.config import settings


async def require_platform_admin(user_id: str = Depends(get_current_user_id)) -> str:
    """Dependency: 403s unless `user_id` is in the platform-admin allowlist."""
    if user_id not in settings.platform_admin_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")
    return user_id
