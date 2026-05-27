"""
Scope Cop API router.

Endpoints
---------
POST /api/scope-cop/analyze
    Analyze ticket readiness via Claude. Requires lead role.
    Fetches tickets from Jira, scores each on four readiness criteria,
    upserts results to ticket_analyses, returns AnalyzeResponse.

GET /api/scope-cop/analyses/{team_id}
    Return cached analyses for a team. No Claude call. Requires lead role.
    Returns 404 if no analyses exist for the team.
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
from src.database import get_db
from src.integrations.jira.client import JiraClient
from src.integrations.jira.oauth import refresh_access_token
from src.models.jira_connection import JiraConnection
from src.models.organization import Organization
from src.models.scope_cop import TicketAnalysis
from src.models.team import Team
from src.services.encryption import decrypt, encrypt
from src.services.scope_cop import (
    _split_meta_from_suggestions,
    analyze_tickets,
)

scope_cop_router = APIRouter(tags=["scope-cop"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    team_id: str
    ticket_keys: list[str]


class TicketAnalysisResult(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    ticket_key: str
    ticket_title: str
    readiness_score: int
    status: str
    issues: list[str]
    suggestions: list[str]
    # Wave 2 (Initiative A) — optional for backward compat with old cached rows.
    stack_alignment: int | None = None
    matched_identifier_count: int | None = None


class ScopeCopSummary(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    total_tickets: int
    ready_count: int
    needs_work_count: int
    blocked_count: int


class AnalyzeResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    analyzed_at: str
    results: list[TicketAnalysisResult]
    summary: ScopeCopSummary


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
    """Resolve team → org Jira connection → JiraClient (with token refresh if needed).

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


def _build_summary(results: list[TicketAnalysisResult]) -> ScopeCopSummary:
    return ScopeCopSummary(
        total_tickets=len(results),
        ready_count=sum(1 for r in results if r.status == "ready"),
        needs_work_count=sum(1 for r in results if r.status == "needs_work"),
        blocked_count=sum(1 for r in results if r.status == "blocked"),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@scope_cop_router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(
    request: AnalyzeRequest,
    _: str = Depends(require_role("lead")),
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Analyze ticket readiness via Claude.

    Fetches each ticket from Jira, scores readiness on four criteria
    (acceptance criteria, estimate, bounded scope, unambiguous ownership),
    upserts results to ticket_analyses, and returns a per-ticket assessment.
    """
    if request.team_id == "default":
        org = await db.scalar(select(Organization).where(Organization.clerk_org_id == clerk_org_id))
        if not org:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organisation not found.")
        team = await db.scalar(select(Team).where(Team.organization_id == org.id))
        if not team:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found.")
    else:
        team = await _resolve_team(request.team_id, db)
    resolved_team_id = str(team.id)
    jira_client = await _get_jira_client(team, db)

    try:
        raw_results = await analyze_tickets(
            team_id=resolved_team_id,
            ticket_keys=request.ticket_keys,
            jira_client=jira_client,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=str(exc)
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        )

    results = [
        TicketAnalysisResult(
            ticket_key=r.ticket_key,
            ticket_title=r.ticket_title,
            readiness_score=r.readiness_score,
            status=r.status,
            issues=r.issues,
            suggestions=r.suggestions,
            stack_alignment=r.stack_alignment,
            matched_identifier_count=r.matched_identifier_count,
        )
        for r in raw_results
    ]

    return AnalyzeResponse(
        analyzed_at=datetime.now(timezone.utc).isoformat(),
        results=results,
        summary=_build_summary(results),
    )


@scope_cop_router.get("/analyses/{team_id}", response_model=AnalyzeResponse)
async def get_analyses(
    team_id: uuid.UUID,
    _: str = Depends(require_role("lead")),
    db: AsyncSession = Depends(get_db),
):
    """
    Return cached analyses for a team without re-calling Claude.

    Since ticket_analyses has UNIQUE (team_id, ticket_key), each row is
    already the most recent analysis for that ticket.
    """
    rows = (
        await db.scalars(
            select(TicketAnalysis)
            .where(TicketAnalysis.team_id == team_id)
            .order_by(TicketAnalysis.analyzed_at.desc())
        )
    ).all()

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No analyses found for this team.",
        )

    results = []
    for row in rows:
        # Peel the Wave-2 meta sentinel off the persisted suggestions array.
        clean_suggestions, stack_alignment, matched_count = (
            _split_meta_from_suggestions(row.suggestions or [])
        )
        results.append(
            TicketAnalysisResult(
                ticket_key=row.ticket_key,
                ticket_title=row.ticket_title or row.ticket_key,
                readiness_score=row.readiness_score or 0,
                status=row.status if isinstance(row.status, str) else row.status.value,
                issues=row.issues or [],
                suggestions=clean_suggestions,
                stack_alignment=stack_alignment,
                matched_identifier_count=matched_count,
            )
        )

    analyzed_at = max(row.analyzed_at for row in rows)

    return AnalyzeResponse(
        analyzed_at=analyzed_at.isoformat(),
        results=results,
        summary=_build_summary(results),
    )
