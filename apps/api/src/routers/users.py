"""
Users API router.

Endpoints
---------
GET /api/users/me/role
    Returns the current authenticated user's app role.

POST /api/users/role
    Admin-only: update another developer's app role by clerkUserId.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_user_id
from src.auth_roles import get_current_app_role, require_role
from src.database import get_db
from src.models.developer import Developer

users_router = APIRouter(tags=["users"])


class RoleResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    user_id: str
    app_role: str


class SetRoleRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    clerk_user_id: str
    app_role: str


@users_router.get("/me/role", response_model=RoleResponse)
async def get_my_role(
    user_id: str = Depends(get_current_user_id),
    app_role: str = Depends(get_current_app_role),
):
    """Return the current user's app role. Returns 'developer' if no record found."""
    return RoleResponse(user_id=user_id, app_role=app_role)


@users_router.post("/role", response_model=RoleResponse)
async def set_user_role(
    body: SetRoleRequest,
    _: str = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Admin-only: set a developer's app role by clerkUserId."""
    developer = await db.scalar(
        select(Developer).where(Developer.clerk_user_id == body.clerk_user_id)
    )
    if developer is None:
        raise HTTPException(status_code=404, detail="Developer not found.")

    developer.app_role = body.app_role
    await db.commit()
    await db.refresh(developer)

    return RoleResponse(user_id=body.clerk_user_id, app_role=developer.app_role)
