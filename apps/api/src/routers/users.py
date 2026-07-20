"""
Users API router.

Endpoints
---------
GET /api/users/me/role
    Returns the current authenticated user's app role.
    Auto-provisions a Developer row on first access.

POST /api/users/role
    Admin-only: update another developer's app role by clerkUserId.

DELETE /api/users/me
    Delete the authenticated user's account and personal data.
"""
import logging
import uuid
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import _clerk, get_current_user_id, get_current_org_id
from src.auth_roles import require_role
from src.database import get_db
from src.models.developer import Developer
from src.models.organization import Organization
from src.models.sprint import Sprint, SprintTicket
from src.models.team import Team
from src.models.velocity import DeveloperVelocityProfile

logger = logging.getLogger(__name__)

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
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """Return the current user's app role. Auto-provisions a Developer row on first access."""
    developer = await db.scalar(
        select(Developer)
        .join(Team, Developer.team_id == Team.id)
        .join(Organization, Team.organization_id == Organization.id)
        .where(
            Organization.clerk_org_id == clerk_org_id,
            Developer.clerk_user_id == user_id,
        )
    )

    if developer is None:
        org = await db.scalar(select(Organization).where(Organization.clerk_org_id == clerk_org_id))
        if org:
            team = await db.scalar(select(Team).where(Team.organization_id == org.id))
            if team:
                developer = Developer(
                    id=uuid.uuid4(),
                    team_id=team.id,
                    clerk_user_id=user_id,
                    name=user_id,
                    app_role="developer",
                )
                db.add(developer)
                await db.commit()
                await db.refresh(developer)

    app_role = developer.app_role if developer else "developer"
    return RoleResponse(user_id=user_id, app_role=app_role)


class PatchMyRoleRequest(BaseModel):
    app_role: str


@users_router.patch("/me/role", response_model=RoleResponse)
async def patch_my_role(
    body: PatchMyRoleRequest,
    user_id: str = Depends(get_current_user_id),
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """Dev tool: set your own role without admin privileges."""
    developer = await db.scalar(
        select(Developer)
        .join(Team, Developer.team_id == Team.id)
        .join(Organization, Team.organization_id == Organization.id)
        .where(
            Organization.clerk_org_id == clerk_org_id,
            Developer.clerk_user_id == user_id,
        )
    )
    if developer is None:
        raise HTTPException(status_code=404, detail="Developer not found.")
    developer.app_role = body.app_role
    await db.commit()
    await db.refresh(developer)
    return RoleResponse(user_id=user_id, app_role=developer.app_role)


async def _wipe_team_data(db: AsyncSession, team_id: uuid.UUID) -> None:
    """Delete every row scoped to a team, in FK-dependency order.

    Many team-scoped tables don't have ondelete CASCADE on their FK to teams
    (sprints, tickets, retros, sprint_alerts, developer_velocity_profiles), so
    we have to walk them by hand. Tables that *do* CASCADE (team_access,
    ticket_revisions, recalibration_proposal, invitation, slack_config,
    team_identifiers) clean up automatically when the team row is dropped at
    the end.
    """
    # Children of sprints first.
    await db.execute(text(
        "DELETE FROM sprint_tickets WHERE sprint_id IN "
        "(SELECT id FROM sprints WHERE team_id = :tid)"
    ), {"tid": team_id})
    await db.execute(text("DELETE FROM sprint_alerts WHERE team_id = :tid"), {"tid": team_id})
    await db.execute(text("DELETE FROM retro_patterns WHERE team_id = :tid"), {"tid": team_id})
    await db.execute(text("DELETE FROM retrospectives WHERE team_id = :tid"), {"tid": team_id})
    # Tickets reference sprints (no cascade); drop tickets before sprints.
    await db.execute(text("DELETE FROM tickets WHERE team_id = :tid"), {"tid": team_id})
    await db.execute(text("DELETE FROM sprints WHERE team_id = :tid"), {"tid": team_id})
    await db.execute(text("DELETE FROM developer_velocity_profiles WHERE team_id = :tid"), {"tid": team_id})
    # developers.team_id has no CASCADE — delete all team members before the team row.
    await db.execute(text("DELETE FROM developers WHERE team_id = :tid"), {"tid": team_id})


@users_router.delete("/me")
async def delete_my_account(
    user_id: str = Depends(get_current_user_id),
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """Delete the authenticated user's account and any data they own.

    The product is used by scrum masters; the Developer table also holds rows
    for imported Jira team members (clerk_user_id IS NULL). "Solo on team" is
    judged by the count of other *signed-in* users only — those imported rows
    don't count, since they represent the team board the scrum master owns.

    If the user is the only signed-in user on the team, wipes all team-scoped
    data (sprints, tickets, retros, alerts, etc.) and deletes the team. If the
    team was the only one in the org, wipes Jira connections and deletes the org.
    Finally deletes the Clerk user so the account can't be re-used.
    """
    developer = await db.scalar(
        select(Developer)
        .join(Team, Developer.team_id == Team.id)
        .join(Organization, Team.organization_id == Organization.id)
        .where(
            Organization.clerk_org_id == clerk_org_id,
            Developer.clerk_user_id == user_id,
        )
    )

    if developer is not None:
        team_id = developer.team_id
        team = await db.get(Team, team_id)
        org_id = team.organization_id if team else None

        other_signed_in = await db.scalar(
            select(func.count(Developer.id))
            .where(
                Developer.team_id == team_id,
                Developer.id != developer.id,
                Developer.clerk_user_id.is_not(None),
            )
        )
        solo_on_team = (other_signed_in or 0) == 0

        # Personal data first — keeps the developer-delete path consistent
        # whether or not we end up wiping the rest of the team.
        await db.execute(
            update(SprintTicket)
            .where(SprintTicket.assignee_id == developer.id)
            .values(assignee_id=None)
        )
        await db.execute(
            delete(DeveloperVelocityProfile).where(DeveloperVelocityProfile.developer_id == developer.id)
        )

        if solo_on_team and team is not None:
            await _wipe_team_data(db, team_id)
            # _wipe_team_data deleted all developers including this one; expunge the
            # stale in-session instance so SQLAlchemy doesn't try to re-delete it.
            db.expunge(developer)
            await db.execute(text("DELETE FROM teams WHERE id = :tid"), {"tid": team_id})

            if org_id is not None:
                remaining_teams = await db.scalar(
                    select(func.count(Team.id)).where(Team.organization_id == org_id)
                )
                if (remaining_teams or 0) == 0:
                    # onboarding_sessions and github_connections FK to organizations.id
                    # with no ondelete cascade — must delete before the org row.
                    # (onboarding_messages cascades automatically via its own
                    # DB-level FK to onboarding_sessions.id.)
                    await db.execute(
                        text("DELETE FROM onboarding_sessions WHERE organization_id = :oid"),
                        {"oid": org_id},
                    )
                    await db.execute(
                        text("DELETE FROM github_connections WHERE organization_id = :oid"),
                        {"oid": org_id},
                    )
                    await db.execute(text("DELETE FROM organizations WHERE id = :oid"), {"oid": org_id})
        else:
            # Other devs share the team — only nuke this user.
            await db.delete(developer)

        await db.commit()

    try:
        await _clerk.users.delete_async(user_id=user_id)
    except Exception:
        logger.exception("Failed to delete Clerk user %s after local purge", user_id)

    return {"deleted": True}


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
