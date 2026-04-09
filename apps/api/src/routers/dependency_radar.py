"""
Dependency Radar API router.

Endpoints (all gated with require_role("lead"))
------------------------------------------------
POST   /api/dependency-radar/scan
    Trigger Jira scan for a team. Returns scanned count + risk score.

GET    /api/dependency-radar/team/{team_id}
    Return all active (unresolved) dependencies + aggregate risk score.

POST   /api/dependency-radar/dependency
    Manually create a dependency (source='manual').

PATCH  /api/dependency-radar/dependency/{id}/resolve
    Mark a dependency as resolved (sets resolved_at = utcnow()).
"""
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_org_id
from src.auth_roles import require_role
from src.models.organization import Organization
from src.database import get_db
from src.integrations.jira.client import JiraClient
from src.integrations.jira.oauth import refresh_access_token
from src.models.dependency_radar import Dependency, DependencyType, RiskLevel
from src.models.jira_connection import JiraConnection
from src.models.team import Team
from src.services.dependency_radar import compute_team_risk_score, scan_jira_dependencies
from src.services.encryption import decrypt, encrypt

dependency_radar_router = APIRouter(tags=["dependency-radar"])


# ---------------------------------------------------------------------------
# Response / Request models
# ---------------------------------------------------------------------------


class DependencyItem(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: str
    ticket_key: str
    ticket_title: str
    blocked_by_key: str | None
    dependency_type: str
    risk_level: str
    description: str | None
    source: str
    resolved_at: str | None
    created_at: str


class ScanRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    team_id: str


class ScanResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    scanned_at: str
    dependencies_found: int
    risk_score: int


class RadarResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    team_id: str
    risk_score: int
    dependencies: list[DependencyItem]


class CreateDependencyRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    team_id: str
    ticket_key: str
    ticket_title: str
    blocked_by_key: str | None = None
    dependency_type: str
    risk_level: str
    description: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _resolve_team(team_id: str, db: AsyncSession) -> Team:
    """Resolve team by UUID string. Raises 404 if not found or invalid UUID."""
    try:
        team_uuid = uuid.UUID(team_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found.")
    team = await db.scalar(select(Team).where(Team.id == team_uuid))
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found.")
    return team


async def _get_jira_client(team: Team, db: AsyncSession) -> JiraClient:
    """Resolve org Jira connection → JiraClient (refreshing token if needed).

    Raises HTTP 402 if no active Jira connection exists for the org.
    """
    connection = await db.scalar(
        select(JiraConnection).where(
            JiraConnection.organization_id == team.organization_id,
            JiraConnection.is_active.is_(True),
        )
    )
    if not connection:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="No active Jira connection. Please connect Jira in Settings.",
        )

    access_token = decrypt(connection.encrypted_access_token)
    if connection.token_expires_at and connection.token_expires_at <= datetime.utcnow():
        refresh_tok = decrypt(connection.encrypted_refresh_token)
        tokens = await refresh_access_token(refresh_tok)
        access_token = tokens["access_token"]
        connection.encrypted_access_token = encrypt(access_token)
        if "refresh_token" in tokens:
            connection.encrypted_refresh_token = encrypt(tokens["refresh_token"])
        if "expires_in" in tokens:
            connection.token_expires_at = datetime.utcnow() + timedelta(seconds=tokens["expires_in"])
        await db.commit()

    return JiraClient(cloud_id=connection.jira_cloud_id, access_token=access_token)


def _dep_to_item(dep: Dependency) -> DependencyItem:
    return DependencyItem(
        id=str(dep.id),
        ticket_key=dep.ticket_key,
        ticket_title=dep.ticket_title or dep.ticket_key,
        blocked_by_key=dep.blocked_by_key,
        dependency_type=dep.dependency_type,
        risk_level=dep.risk_level,
        description=dep.description,
        source=dep.source,
        resolved_at=dep.resolved_at.isoformat() if dep.resolved_at else None,
        created_at=dep.created_at.isoformat(),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@dependency_radar_router.post("/scan", response_model=ScanResponse, status_code=status.HTTP_200_OK)
async def scan(
    request: ScanRequest,
    _: str = Depends(require_role("lead")),
    db: AsyncSession = Depends(get_db),
):
    """Trigger a Jira dependency scan for a team."""
    team = await _resolve_team(request.team_id, db)
    jira_client = await _get_jira_client(team, db)

    result = await scan_jira_dependencies(
        team_id=request.team_id,
        jira_client=jira_client,
        db=db,
    )
    await db.commit()

    return ScanResponse(
        scanned_at=result.scanned_at.isoformat(),
        dependencies_found=result.dependencies_found,
        risk_score=result.risk_score,
    )


@dependency_radar_router.get("/team/{team_id}", response_model=RadarResponse)
async def get_team_dependencies(
    team_id: str,
    _: str = Depends(require_role("lead")),
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """Return all active (unresolved) dependencies for a team plus aggregate risk score.
    Accepts a UUID string or 'default' (resolves to the first team in the org).
    """
    if team_id == "default":
        org = await db.scalar(select(Organization).where(Organization.clerk_org_id == clerk_org_id))
        if not org:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organisation not found.")
        team = await db.scalar(select(Team).where(Team.organization_id == org.id))
    else:
        team = await _resolve_team(team_id, db)

    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found.")

    rows = (
        await db.scalars(
            select(Dependency).where(
                Dependency.team_id == team.id,
                Dependency.resolved_at.is_(None),
            )
        )
    ).all()

    return RadarResponse(
        team_id=str(team.id),
        risk_score=compute_team_risk_score(list(rows)),
        dependencies=[_dep_to_item(d) for d in rows],
    )


@dependency_radar_router.post(
    "/dependency", response_model=DependencyItem, status_code=status.HTTP_201_CREATED
)
async def create_dependency(
    request: CreateDependencyRequest,
    _: str = Depends(require_role("lead")),
    db: AsyncSession = Depends(get_db),
):
    """Manually create a dependency with source='manual'."""
    team = await _resolve_team(request.team_id, db)

    dep = Dependency(
        team_id=team.id,
        ticket_key=request.ticket_key,
        ticket_title=request.ticket_title,
        blocked_by_key=request.blocked_by_key,
        dependency_type=request.dependency_type,
        risk_level=request.risk_level,
        description=request.description,
        source="manual",
    )
    db.add(dep)
    await db.flush()
    await db.refresh(dep)
    await db.commit()

    return _dep_to_item(dep)


@dependency_radar_router.patch(
    "/dependency/{dep_id}/resolve", response_model=DependencyItem
)
async def resolve_dependency(
    dep_id: uuid.UUID,
    _: str = Depends(require_role("lead")),
    db: AsyncSession = Depends(get_db),
):
    """Mark a dependency as resolved by setting resolved_at = utcnow()."""
    dep = await db.scalar(select(Dependency).where(Dependency.id == dep_id))
    if not dep:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dependency not found.")

    dep.resolved_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.commit()
    await db.refresh(dep)

    return _dep_to_item(dep)
