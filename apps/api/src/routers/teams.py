"""
Multi-team management API router.

Endpoints
---------
GET    /api/teams
GET    /api/teams/multi-dashboard
POST   /api/teams/{team_id}/access
DELETE /api/teams/{team_id}/access/{developer_id}
"""
import json
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, field_validator
from pydantic.alias_generators import to_camel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_org_id, get_current_user_id
from src.auth_roles import require_role
from src.config import settings
from src.database import get_db
from src.models.developer import Developer
from src.models.organization import Organization
from src.models.team import Team
from src.models.team_access import TeamAccessGrant
from src.services.multi_team import get_accessible_teams, get_multi_team_summary

teams_router = APIRouter(tags=["teams"])


# ---------------------------------------------------------------------------
# Response / Request models
# ---------------------------------------------------------------------------

class TeamListItem(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    team_id: str
    team_name: str
    is_primary: bool


class TeamsListResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    teams: list[TeamListItem]


class TeamDashboardItem(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    team_id: str
    team_name: str
    health_score: int
    active_sprint_name: str | None
    completion_rate: float
    active_deps_count: int
    last_retro_date: str | None
    rag_status: str


class MultiDashboardResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    teams: list[TeamDashboardItem]


class GrantAccessRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    developer_clerk_user_id: str


class CreateTeamDeveloper(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    name: str
    role: str | None = None


class CreateTeamRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    name: str
    developers: list[CreateTeamDeveloper] = []


class CreatedDeveloper(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    developer_id: str
    name: str


class CreateTeamResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    team_id: str
    name: str
    is_new: bool
    developers: list[CreatedDeveloper]


class SetupStatusResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    setup_complete: bool
    team_id: str | None


class SeedTicketIn(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    jira_issue_key: str
    title: str
    story_points: float | None = None
    ticket_type: str | None = None
    labels: list[str] | None = None


class SeedTicketsRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    tickets: list[SeedTicketIn]


class SeedTicketsResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    created: int
    updated: int


class MemberSetupIn(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    name: str
    email: str | None = None
    role: str
    custom_role: str | None = None
    seniority: str
    capacity_hours_per_week: int
    domain_strengths: list[str]
    meeting_hours_bucket: str
    skill_ratings: dict[str, float] | None = None

    @field_validator("skill_ratings")
    @classmethod
    def _validate_skill_ratings(cls, v: dict[str, float] | None) -> dict[str, float] | None:
        if v is None:
            return v
        for _key, val in v.items():
            if val < 0.0 or val > 1.0:
                raise ValueError("skill_ratings values must be between 0.0 and 1.0")
        return v


class TeamSetupRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    name: str
    size_tier: str
    cadence: str
    methodology: str
    tech_stack: list[str]
    members: list[MemberSetupIn]


class TeamSetupResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    team_id: str
    member_count: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_primary_team_id(clerk_user_id: str, db: AsyncSession) -> uuid.UUID | None:
    result = await db.execute(
        select(Developer.team_id).where(Developer.clerk_user_id == clerk_user_id).limit(1)
    )
    row = result.scalar_one_or_none()
    return row


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@teams_router.get("", response_model=TeamsListResponse)
async def list_teams(
    user_id: str = Depends(get_current_user_id),
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    teams = await get_accessible_teams(user_id, clerk_org_id, db)
    primary_id = await _get_primary_team_id(user_id, db)

    items = [
        TeamListItem(
            team_id=str(t.id),
            team_name=t.name,
            is_primary=(t.id == primary_id),
        )
        for t in teams
    ]
    return TeamsListResponse(teams=items)


@teams_router.get("/multi-dashboard", response_model=MultiDashboardResponse)
async def multi_dashboard(
    user_id: str = Depends(get_current_user_id),
    clerk_org_id: str = Depends(get_current_org_id),
    _role: str = Depends(require_role("lead")),
    db: AsyncSession = Depends(get_db),
):
    if not settings.is_feature_enabled("multi_team_dashboard"):
        raise HTTPException(status_code=404, detail="Feature not available")
    teams = await get_accessible_teams(user_id, clerk_org_id, db)
    if not teams:
        return MultiDashboardResponse(teams=[])

    summaries = await get_multi_team_summary([t.id for t in teams], db)
    items = [
        TeamDashboardItem(
            team_id=s["teamId"],
            team_name=s["teamName"],
            health_score=s["healthScore"],
            active_sprint_name=s["activeSprintName"],
            completion_rate=s["completionRate"],
            active_deps_count=s["activeDepsCount"],
            last_retro_date=s["lastRetroDate"],
            rag_status=s["ragStatus"],
        )
        for s in summaries
    ]
    return MultiDashboardResponse(teams=items)


@teams_router.post("", response_model=CreateTeamResponse)
async def create_team(
    body: CreateTeamRequest,
    response: Response,
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """Create a Team (and its Developers) under the caller's current org.

    Idempotent on (organization_id, name): if a team with this name already
    exists in the org, return it with isNew=False. Developers are idempotent
    on (team_id, name): re-POSTing the same body returns existing devs and
    does not duplicate rows.

    Gated by the `allow_team_creation_via_api` feature flag.
    """
    if not settings.is_feature_enabled("allow_team_creation_via_api"):
        raise HTTPException(
            status_code=403,
            detail="Team creation via API is disabled in this environment.",
        )

    org = await db.scalar(
        select(Organization).where(Organization.clerk_org_id == clerk_org_id)
    )
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")

    # Idempotency: look up an existing team with this name in the org.
    team = await db.scalar(
        select(Team).where(
            Team.organization_id == org.id,
            Team.name == body.name,
        )
    )
    is_new = False
    if team is None:
        team = Team(
            id=uuid.uuid4(),
            organization_id=org.id,
            name=body.name,
            sprint_length_days=14,
        )
        db.add(team)
        await db.flush()  # get team.id before creating developers
        is_new = True
        response.status_code = 201
    else:
        response.status_code = 200

    # Idempotent developer creation: skip names already present on the team.
    existing_devs = (
        await db.scalars(
            select(Developer).where(Developer.team_id == team.id)
        )
    ).all()
    existing_by_name = {d.name: d for d in existing_devs}

    created_or_existing: list[Developer] = []
    for dev_in in body.developers:
        existing = existing_by_name.get(dev_in.name)
        if existing is not None:
            created_or_existing.append(existing)
            continue
        dev = Developer(
            id=uuid.uuid4(),
            team_id=team.id,
            name=dev_in.name,
            role=dev_in.role,
        )
        db.add(dev)
        created_or_existing.append(dev)

    await db.commit()

    return CreateTeamResponse(
        team_id=str(team.id),
        name=team.name,
        is_new=is_new,
        developers=[
            CreatedDeveloper(developer_id=str(d.id), name=d.name)
            for d in created_or_existing
        ],
    )


@teams_router.post(
    "/{team_id}/seed-tickets", response_model=SeedTicketsResponse
)
async def seed_tickets(
    team_id: uuid.UUID,
    body: SeedTicketsRequest,
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """Bulk-insert backlog Ticket rows for a team without going through
    Jira sync.

    The simulator uses this to populate the candidate pool when
    `sync_jira_team` can't run (stale OAuth scopes, no Celery worker, etc).
    Tickets are inserted with sprint_id=None so SprintBrain's
    `_get_candidate_tickets` query picks them up.

    Idempotent on jira_issue_id: existing rows have sprint_id reset to NULL
    and core fields refreshed (so spillover semantics from a prior run don't
    pollute the new pool). Gated by `allow_team_creation_via_api`.
    """
    from src.models.ticket import Ticket, TicketStatus

    if not settings.is_feature_enabled("allow_team_creation_via_api"):
        raise HTTPException(
            status_code=403,
            detail="Team API disabled in this environment.",
        )

    org = await db.scalar(
        select(Organization).where(Organization.clerk_org_id == clerk_org_id)
    )
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")

    team = await db.scalar(
        select(Team).where(
            Team.id == team_id,
            Team.organization_id == org.id,
        )
    )
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    from src.models.ticket import Ticket  # local import — avoid app cold-start cost
    from src.models.sprint import Sprint, SprintStatus

    # Mark any stale ACTIVE/PLANNING sprints from prior sim runs as
    # COMPLETED. Otherwise push_to_jira's "active sprint in progress" guard
    # 409s the very first push of a new run. Safe because seed_tickets is
    # dev-only — we're claiming the team for a fresh sim.
    stale_sprints = (await db.scalars(
        select(Sprint).where(
            Sprint.team_id == team.id,
            Sprint.status.in_([SprintStatus.ACTIVE, SprintStatus.PLANNING]),
        )
    )).all()
    for s in stale_sprints:
        s.status = SprintStatus.COMPLETED
    if stale_sprints:
        await db.flush()

    created = 0
    updated = 0
    for t in body.tickets:
        # jira_issue_key is unique within a project, so use it as the
        # synthetic jira_issue_id when the simulator hasn't captured the
        # real Jira numeric id. Production sync will reconcile if a real
        # id ever shows up.
        synthetic_id = t.jira_issue_key
        existing = await db.scalar(
            select(Ticket).where(Ticket.jira_issue_id == synthetic_id)
        )
        if existing is not None:
            existing.team_id = team.id
            existing.sprint_id = None
            existing.title = t.title
            existing.story_points_estimated = t.story_points
            existing.ticket_type = t.ticket_type
            existing.status = TicketStatus.TODO
            existing.labels = t.labels
            updated += 1
        else:
            db.add(
                Ticket(
                    team_id=team.id,
                    sprint_id=None,
                    jira_issue_id=synthetic_id,
                    jira_issue_key=t.jira_issue_key,
                    title=t.title,
                    status=TicketStatus.TODO,
                    ticket_type=t.ticket_type,
                    story_points_estimated=t.story_points,
                    labels=t.labels,
                )
            )
            created += 1

    await db.commit()
    return SeedTicketsResponse(created=created, updated=updated)


@teams_router.get("/setup-status", response_model=SetupStatusResponse)
async def get_setup_status(
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """Return whether the onboarding wizard has been completed for this org."""
    org = await db.scalar(
        select(Organization).where(Organization.clerk_org_id == clerk_org_id)
    )
    if not org:
        return SetupStatusResponse(setup_complete=False, team_id=None)

    team = await db.scalar(
        select(Team).where(
            Team.organization_id == org.id,
            Team.profile_setup_at.is_not(None),
        )
    )
    if team:
        return SetupStatusResponse(setup_complete=True, team_id=str(team.id))
    return SetupStatusResponse(setup_complete=False, team_id=None)


_CADENCE_MAP = {
    "1-week": 7,
    "2-week": 14,
    "3-week": 21,
    "4-week": 28,
}


@teams_router.post("/setup", response_model=TeamSetupResponse)
async def team_setup(
    body: TeamSetupRequest,
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """Save the team profile and members collected during the onboarding wizard.

    Finds or creates the primary team for the org, updates its profile fields,
    and creates a Developer row for each member supplied.
    """
    org = await db.scalar(
        select(Organization).where(Organization.clerk_org_id == clerk_org_id)
    )
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")

    # Find the existing team for this org (created by provision_organization),
    # or create one if it does not exist yet.
    team = await db.scalar(
        select(Team).where(Team.organization_id == org.id)
    )
    if team is None:
        team = Team(
            id=uuid.uuid4(),
            organization_id=org.id,
            name=body.name,
            sprint_length_days=_CADENCE_MAP.get(body.cadence, 14),
        )
        db.add(team)
        await db.flush()

    # Update profile fields.
    team.name = body.name
    team.size_tier = body.size_tier
    team.methodology = body.methodology
    team.tech_stack = json.dumps(body.tech_stack)
    team.sprint_length_days = _CADENCE_MAP.get(body.cadence, 14)
    team.profile_setup_at = datetime.utcnow()

    # Create developer rows for each member.
    for member in body.members:
        effective_role = member.custom_role if member.role == "custom" else member.role
        dev = Developer(
            id=uuid.uuid4(),
            team_id=team.id,
            name=member.name,
            email=member.email,
            role=effective_role,
            seniority=member.seniority,
            capacity_hours_per_week=member.capacity_hours_per_week,
            domain_strengths=json.dumps(member.domain_strengths),
            meeting_hours_bucket=member.meeting_hours_bucket,
            skill_ratings=member.skill_ratings,
        )
        db.add(dev)

    await db.commit()

    return TeamSetupResponse(team_id=str(team.id), member_count=len(body.members))


@teams_router.post("/{team_id}/access", status_code=201)
async def grant_access(
    team_id: uuid.UUID,
    body: GrantAccessRequest,
    _user_id: str = Depends(get_current_user_id),
    _role: str = Depends(require_role("lead")),
    db: AsyncSession = Depends(get_db),
):
    # Find developer by clerk user id
    dev_result = await db.execute(
        select(Developer).where(Developer.clerk_user_id == body.developer_clerk_user_id)
    )
    developer = dev_result.scalar_one_or_none()
    if not developer:
        raise HTTPException(status_code=404, detail="Developer not found")

    # Check if already granted
    existing = await db.execute(
        select(TeamAccessGrant).where(
            TeamAccessGrant.developer_id == developer.id,
            TeamAccessGrant.team_id == team_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Access already granted")

    grant = TeamAccessGrant(
        id=uuid.uuid4(),
        developer_id=developer.id,
        team_id=team_id,
        granted_by=_user_id,
    )
    db.add(grant)
    await db.commit()
    return {"granted": True, "teamId": str(team_id), "developerId": str(developer.id)}


@teams_router.delete("/{team_id}/access/{developer_id}")
async def revoke_access(
    team_id: uuid.UUID,
    developer_id: uuid.UUID,
    _user_id: str = Depends(get_current_user_id),
    _role: str = Depends(require_role("lead")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(TeamAccessGrant).where(
            TeamAccessGrant.developer_id == developer_id,
            TeamAccessGrant.team_id == team_id,
        )
    )
    grant = result.scalar_one_or_none()
    if not grant:
        raise HTTPException(status_code=404, detail="Access grant not found")

    await db.delete(grant)
    await db.commit()
    return {"revoked": True}
