"""
Sprint Brain API router.

Endpoints
---------
POST /api/sprint-brain/plan
    Generate an AI-powered sprint plan for a team.

POST /api/sprint-brain/what-if
    Re-plan with specified tickets dropped; returns revised confidence/assignments.

Coordinator stubs
-----------------
Three internal helpers are currently stubbed and must be completed once the
following upstream tracks land:

  get_anthropic_key()      → needs Organisation model (Track C) + encryption service
  _get_developer_profiles() → needs TeamMember + VelocityRecord models (Track C)
                              and velocity service (Track E velocity engine)
  _get_candidate_tickets()  → needs Ticket model (Track C) + Jira sync (Track D)
"""

import logging
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select, func, or_

from src.auth import get_current_user_id, get_current_org_id
from src.auth_roles import require_role
from src.config import settings
from src.database import get_db
from src.integrations.jira.push import resolve_jira_account_id
from src.integrations.jira.sync import _get_fresh_client_async, JiraReauthRequired
from src.models.developer import Developer
from src.models.jira_connection import JiraConnection
from src.models.organization import Organization
from src.models.scope_cop import TicketAnalysis
from src.models.dependency_radar import Dependency, RiskLevel
from src.models.retro import RetroPattern
from src.models.sprint import Sprint, SprintStatus
from src.models.team import Team
from src.models.ticket import Ticket, TicketStatus
from src.services.ai_client import get_anthropic_key
from src.services.sprint_brain import (
    SprintBrainInput,
    SprintBrainOutput,
    generate_sprint_plan,
    simulate_what_if,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sprint-brain", tags=["sprint-brain"])


# ---------------------------------------------------------------------------
# Pydantic request/response models
# ---------------------------------------------------------------------------


class PlanRequest(BaseModel):
    team_id: str
    sprint_length_days: int = 14
    sprint_start_date: str = ""        # ISO-8601; defaults to today if omitted
    pto_overrides: dict[str, float] = {}


class WhatIfRequest(BaseModel):
    team_id: str
    sprint_length_days: int = 14
    sprint_start_date: str = ""
    pto_overrides: dict[str, float] = {}
    dropped_ticket_ids: list[str]      # tickets to remove from the candidate pool


class PushAssignment(BaseModel):
    ticketId: str       # Jira issue key
    developerId: str    # Developer UUID


class PushToJiraRequest(BaseModel):
    teamId: str
    sprintName: str
    sprintStartDate: str    # YYYY-MM-DD
    sprintEndDate: str      # YYYY-MM-DD
    assignments: list[PushAssignment]


class PushToJiraResponse(BaseModel):
    jiraSprintId: int
    sprintUrl: str
    pushedTickets: int
    unassignedWarnings: list[str]


class ScopeWarning(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    ticket_id: str
    status: str
    issues: list[str]


class DependencyWarning(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    ticket_id: str
    risk_level: str
    description: str | None


class EnrichmentStatus(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    scope_cop: Literal["not_analyzed", "all_ready", "has_issues"]
    dependency_radar: Literal["not_scanned", "no_risks", "has_risks"]
    retro_patterns: Literal["no_data", "no_active_patterns", "has_patterns"]


# ---------------------------------------------------------------------------
# Coordinator stubs — replace once upstream tracks are merged
# ---------------------------------------------------------------------------


async def _get_developer_profiles(team_id: str, db: AsyncSession) -> list[dict]:
    """
    Build developer profiles for sprint planning.

    Uses per-developer velocity records when available; falls back to
    team average velocity divided equally across active developers (cold start).
    """
    developers = (await db.scalars(
        select(Developer).where(Developer.team_id == team_id, Developer.is_active.is_(True))
    )).all()

    if not developers:
        return []

    # Compute team avg velocity from completed sprints as cold-start baseline
    completed_sprints = (await db.scalars(
        select(Sprint).where(
            Sprint.team_id == team_id,
            Sprint.status == SprintStatus.COMPLETED,
            Sprint.delivered_points.isnot(None),
        ).order_by(Sprint.end_date.desc()).limit(6)
    )).all()

    if completed_sprints:
        team_avg = sum(s.delivered_points for s in completed_sprints) / len(completed_sprints)
        per_dev_velocity = round(team_avg / len(developers), 1)
        sprint_count = len(completed_sprints)
    else:
        per_dev_velocity = 8.0  # sensible default: ~1 ticket/sprint
        sprint_count = 0

    return [
        {
            "developer_id": str(d.id),
            "display_name": d.name,
            "role": d.role or "Engineer",
            "email": d.email or "",
            "velocity": per_dev_velocity,
            "sprint_count": sprint_count,
            "avg_points_per_sprint": per_dev_velocity,
            "safe_capacity_pts": round(per_dev_velocity * 0.8, 1),
            "velocity_breakdown": [
                {
                    "ticket_type": "general",
                    "domain": d.role or "Engineering",
                    "avg_pts": per_dev_velocity,
                    "sample_count": sprint_count,
                }
            ] if sprint_count > 0 else [],
        }
        for d in developers
    ]


async def _get_candidate_tickets(team_id: str, db: AsyncSession) -> list[dict]:
    """Fetch unassigned/backlog tickets for sprint planning.

    Includes both tickets with no sprint (true backlog) and tickets that
    remained in a completed sprint (carryover) — the latter must flow back
    into the candidate pool for the next sprint.
    """
    import uuid as _uuid
    try:
        team_uuid = _uuid.UUID(team_id)
    except ValueError:
        team_uuid = team_id

    tickets = (await db.scalars(
        select(Ticket)
        .where(
            Ticket.team_id == team_id,
            or_(
                Ticket.sprint_id.is_(None),
                Ticket.sprint_id.in_(
                    select(Sprint.id).where(
                        Sprint.team_id == team_uuid,
                        Sprint.status == SprintStatus.COMPLETED,
                    )
                ),
            ),
            Ticket.status.notin_([TicketStatus.DONE, TicketStatus.CANCELLED]),
        )
        .order_by(Ticket.story_points_estimated.desc().nulls_last())
        .limit(50)
    )).all()

    # Attach per-ticket skill_vector + matched_identifiers from TicketSkillAnalysis
    # (additive enrichment).
    skill_vectors: dict = {}
    matched_identifiers_map: dict = {}
    try:
        from src.models.identifier import TicketSkillAnalysis
        ticket_ids = [t.id for t in tickets]
        if ticket_ids:
            analyses = (await db.scalars(
                select(TicketSkillAnalysis).where(
                    TicketSkillAnalysis.ticket_id.in_(ticket_ids)
                )
            )).all()
            skill_vectors = {a.ticket_id: (a.skill_vector or {}) for a in analyses}
            matched_identifiers_map = {
                a.ticket_id: (a.matched_identifiers or []) for a in analyses
            }
    except Exception:
        # Defensive: never block plan generation on enrichment failure.
        skill_vectors = {}
        matched_identifiers_map = {}

    return [
        {
            "id": t.jira_issue_key or str(t.id),
            "summary": t.title,
            "story_points": t.story_points_estimated or 0,
            "priority": "medium",
            "labels": t.labels or [],
            "skill_vector": skill_vectors.get(t.id, {}),
            "matched_identifiers": matched_identifiers_map.get(t.id, []),
        }
        for t in tickets
    ]


# ---------------------------------------------------------------------------
# Enrichment
# ---------------------------------------------------------------------------


async def _build_enrichment(
    team_id: str,
    assigned_keys: list[str],
    db: AsyncSession,
) -> tuple[list[ScopeWarning], list[DependencyWarning], EnrichmentStatus, list[str], list[str]]:
    """
    Query ticket_analyses, dependencies, and retro_patterns to build enrichment data.
    Returns (scope_warnings, dep_warnings, enrichment_status, historical_warnings, pattern_descriptions).
    """
    import uuid as _uuid
    try:
        team_uuid = _uuid.UUID(team_id)
    except ValueError:
        # Can't enrich without a valid team UUID
        return (
            [],
            [],
            EnrichmentStatus(
                scope_cop="not_analyzed",
                dependency_radar="not_scanned",
                retro_patterns="no_data",
            ),
            [],
            [],
        )

    # --- Scope Cop enrichment ---
    scope_warnings: list[ScopeWarning] = []
    scope_cop_status: Literal["not_analyzed", "all_ready", "has_issues"] = "not_analyzed"
    try:
        scope_rows = (await db.scalars(
            select(TicketAnalysis).where(
                TicketAnalysis.team_id == team_uuid,
                TicketAnalysis.ticket_key.in_(assigned_keys),
            )
        )).all()

        if not scope_rows:
            scope_cop_status = "not_analyzed"
        else:
            # r.status may be a ScopeCopStatus enum member or a plain string depending on
            # SQLAlchemy version / dialect — normalize to string value before comparing.
            def _status_str(s) -> str:
                return s.value if hasattr(s, "value") else str(s)

            flagged = [r for r in scope_rows if _status_str(r.status) != "ready"]
            if flagged:
                scope_cop_status = "has_issues"
                scope_warnings = [
                    ScopeWarning(
                        ticket_id=r.ticket_key,
                        status=_status_str(r.status),
                        issues=r.issues or [],
                    )
                    for r in flagged
                ]
            else:
                scope_cop_status = "all_ready"

        logger.debug(
            "[enrichment] scope_cop: %d checked, %d flagged",
            len(scope_rows),
            len(scope_warnings),
        )
    except Exception:
        logger.exception("[enrichment] scope_cop query failed — defaulting to not_analyzed")
        scope_cop_status = "not_analyzed"
        scope_warnings = []

    # --- Dependency Radar enrichment ---
    dep_warnings: list[DependencyWarning] = []
    dep_radar_status: Literal["not_scanned", "no_risks", "has_risks"] = "not_scanned"
    try:
        # Check if ANY dep data exists for this team (determines not_scanned vs no_risks)
        any_deps = await db.scalar(
            select(func.count()).select_from(Dependency).where(
                Dependency.team_id == team_uuid,
                Dependency.resolved_at.is_(None),
            )
        )
        high_risk_deps = (await db.scalars(
            select(Dependency).where(
                Dependency.team_id == team_uuid,
                Dependency.ticket_key.in_(assigned_keys),
                Dependency.resolved_at.is_(None),
                Dependency.risk_level == RiskLevel.HIGH.value,
            )
        )).all()

        if not any_deps:
            dep_radar_status = "not_scanned"
        elif not high_risk_deps:
            dep_radar_status = "no_risks"
        else:
            dep_radar_status = "has_risks"
            dep_warnings = [
                DependencyWarning(
                    ticket_id=r.ticket_key,
                    risk_level=r.risk_level,
                    description=r.description,
                )
                for r in high_risk_deps
            ]

        logger.debug(
            "[enrichment] dep_radar: %d high-risk on assigned tickets",
            len(dep_warnings),
        )
    except Exception:
        logger.exception("[enrichment] dep_radar query failed — defaulting to not_scanned")
        dep_radar_status = "not_scanned"
        dep_warnings = []

    # --- Retro Pattern enrichment ---
    historical_warnings: list[str] = []
    pattern_descriptions: list[str] = []
    retro_status: Literal["no_data", "no_active_patterns", "has_patterns"] = "no_data"
    try:
        all_pattern_rows = (await db.scalars(
            select(RetroPattern).where(RetroPattern.team_id == team_uuid)
        )).all()

        active_patterns = [
            r for r in all_pattern_rows
            if r.status == "active" and r.occurrence_count >= 2
        ]

        if not all_pattern_rows:
            retro_status = "no_data"
        elif not active_patterns:
            retro_status = "no_active_patterns"
        else:
            retro_status = "has_patterns"
            historical_warnings = [p.description for p in active_patterns if p.description]
            pattern_descriptions = historical_warnings

        logger.debug("[enrichment] patterns: %d active for team", len(active_patterns))
    except Exception:
        logger.exception("[enrichment] retro_patterns query failed — defaulting to no_data")
        retro_status = "no_data"
        historical_warnings = []
        pattern_descriptions = []

    return (
        scope_warnings,
        dep_warnings,
        EnrichmentStatus(
            scope_cop=scope_cop_status,
            dependency_radar=dep_radar_status,
            retro_patterns=retro_status,
        ),
        historical_warnings,
        pattern_descriptions,
    )


# ---------------------------------------------------------------------------
# Route helpers
# ---------------------------------------------------------------------------


def _sprint_plan_response(
    team_id: str,
    sprint_start: str,
    plan: SprintBrainOutput,
    developer_profiles: list[dict],
    candidate_tickets: list[dict],
    scope_warnings: list[ScopeWarning] | None = None,
    dep_warnings: list[DependencyWarning] | None = None,
    enrichment_status: EnrichmentStatus | None = None,
    historical_warnings: list[str] | None = None,
) -> dict:
    dev_name_map = {p["developer_id"].lower(): p["display_name"] for p in developer_profiles}
    ticket_title_map = {t["id"]: t["summary"] for t in candidate_tickets}
    ticket_skill_map = {t["id"]: t.get("skill_vector", {}) for t in candidate_tickets}
    ticket_identifiers_map = {
        t["id"]: t.get("matched_identifiers", []) for t in candidate_tickets
    }
    enriched_assignments = [
        {
            **a,
            "developer_id": a.get("developer_id", "").lower(),
            "developer_name": dev_name_map.get(a.get("developer_id", "").lower(), a.get("developer_id", "")),
            "title": ticket_title_map.get(a.get("ticket_id", ""), a.get("ticket_id", "")),
            "skill_vector": ticket_skill_map.get(a.get("ticket_id", ""), {}),
            "matched_identifiers": ticket_identifiers_map.get(a.get("ticket_id", ""), []),
        }
        for a in plan.assignments
    ]
    default_status = EnrichmentStatus(
        scope_cop="not_analyzed",
        dependency_radar="not_scanned",
        retro_patterns="no_data",
    )
    return {
        "team_id": team_id,
        "sprint_start": sprint_start,
        "assignments": enriched_assignments,
        "confidence_score": plan.confidence_score,
        "summary": plan.summary,
        "warnings": plan.warnings,
        "what_if_dropped": plan.what_if_dropped,
        "insufficient_data_devs": plan.insufficient_data_devs,
        "developers": {p["developer_id"].lower(): p["display_name"] for p in developer_profiles},
        "scopeWarnings": [w.model_dump(by_alias=True) for w in (scope_warnings or [])],
        "dependencyWarnings": [w.model_dump(by_alias=True) for w in (dep_warnings or [])],
        "historicalWarnings": historical_warnings or [],
        "enrichmentStatus": (enrichment_status or default_status).model_dump(by_alias=True),
    }


async def _resolve_team_id(team_id: str, clerk_org_id: str, db: AsyncSession) -> str:
    """Resolve 'default' (or any non-UUID) to the org's first team id."""
    try:
        import uuid as _uuid
        _uuid.UUID(team_id)
        return team_id
    except ValueError:
        pass
    org = await db.scalar(select(Organization).where(Organization.clerk_org_id == clerk_org_id))
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organisation not found")
    team = await db.scalar(select(Team).where(Team.organization_id == org.id))
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    return str(team.id)


async def _build_brain_input(
    team_id: str,
    sprint_length_days: int,
    sprint_start_date: str,
    pto_overrides: dict[str, float],
    db: AsyncSession,
) -> tuple[SprintBrainInput, str, list[dict], list[dict]]:
    """Return (SprintBrainInput, sprint_start, developer_profiles, candidate_tickets)."""
    candidate_tickets = await _get_candidate_tickets(team_id, db)
    if not candidate_tickets:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "No candidate tickets found for this team. "
                "Sync your Jira backlog first."
            ),
        )

    developer_profiles = await _get_developer_profiles(team_id, db)
    sprint_start = sprint_start_date or date.today().isoformat()

    return (
        SprintBrainInput(
            team_id=team_id,
            candidate_tickets=candidate_tickets,
            developer_profiles=developer_profiles,
            sprint_length_days=sprint_length_days,
            sprint_start_date=sprint_start,
            pto_overrides=pto_overrides,
        ),
        sprint_start,
        developer_profiles,
        candidate_tickets,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/plan")
async def create_sprint_plan(
    request: PlanRequest,
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Generate an AI-powered sprint plan.

    Fetches the team's velocity profiles and unstarted Jira tickets, then
    asks Claude to assign tickets to developers and return a confidence score,
    plain-English summary, risk warnings, and what-if analysis for each ticket.
    """
    api_key = await get_anthropic_key(clerk_org_id, db)
    team_id = await _resolve_team_id(request.team_id, clerk_org_id, db)

    brain_input, sprint_start, dev_profiles, tickets = await _build_brain_input(
        team_id=team_id,
        sprint_length_days=request.sprint_length_days,
        sprint_start_date=request.sprint_start_date,
        pto_overrides=request.pto_overrides,
        db=db,
    )

    # Pre-fetch active retro patterns to inject into Claude prompt (Track 23)
    import uuid as _uuid
    try:
        _team_uuid = _uuid.UUID(team_id)
        _pattern_rows = (await db.scalars(
            select(RetroPattern).where(
                RetroPattern.team_id == _team_uuid,
                RetroPattern.status == "active",
                RetroPattern.occurrence_count >= 2,
            )
        )).all()
        brain_input.historical_patterns = [p.description for p in _pattern_rows if p.description]
    except (ValueError, Exception):
        pass  # non-UUID team_id or DB error — proceed without patterns

    try:
        plan = await generate_sprint_plan(brain_input, api_key, db=db)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        )

    # Post-plan enrichment queries (Tracks 22 + 23)
    assigned_keys = [a.get("ticket_id", "") for a in plan.assignments]
    scope_warnings, dep_warnings, enrichment_status, historical_warnings, _ = (
        await _build_enrichment(team_id, assigned_keys, db)
    )

    return _sprint_plan_response(
        team_id, sprint_start, plan, dev_profiles, tickets,
        scope_warnings=scope_warnings,
        dep_warnings=dep_warnings,
        enrichment_status=enrichment_status,
        historical_warnings=historical_warnings,
    )


@router.post("/what-if")
async def what_if_scenario(
    request: WhatIfRequest,
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Model the impact of dropping specific tickets from the sprint.

    Re-runs sprint planning with the given tickets removed from the candidate
    pool and returns the revised plan. Compare `confidence_score` before and
    after to quantify the benefit of descoping.
    """
    api_key = await get_anthropic_key(clerk_org_id, db)
    team_id = await _resolve_team_id(request.team_id, clerk_org_id, db)

    brain_input, sprint_start, dev_profiles, tickets = await _build_brain_input(
        team_id=team_id,
        sprint_length_days=request.sprint_length_days,
        sprint_start_date=request.sprint_start_date,
        pto_overrides=request.pto_overrides,
        db=db,
    )

    try:
        plan = await simulate_what_if(brain_input, request.dropped_ticket_ids, api_key)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        )

    return {
        "team_id": request.team_id,
        "sprint_start": sprint_start,
        "dropped_tickets": request.dropped_ticket_ids,
        "revised_plan": {
            "assignments": plan.assignments,
            "confidence_score": plan.confidence_score,
            "summary": plan.summary,
            "warnings": plan.warnings,
            "insufficient_data_devs": plan.insufficient_data_devs,
        },
    }


@router.post("/push-to-jira", dependencies=[Depends(require_role("lead"))])
async def push_to_jira(
    request: PushToJiraRequest,
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
) -> PushToJiraResponse:
    """
    Create a Jira sprint, move issues into it, and assign developers.

    Requires 'lead' role or higher.
    """
    if not settings.is_feature_enabled("push_to_jira"):
        raise HTTPException(status_code=404, detail="Feature not available")
    # 1. Resolve team by teamId — 404 if not found
    resolved_team_id = await _resolve_team_id(request.teamId, clerk_org_id, db)
    import uuid as _uuid
    team = await db.scalar(select(Team).where(Team.id == _uuid.UUID(resolved_team_id)))
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found.")

    # 2. Check for active sprint — 409 if found
    active_sprint = await db.scalar(
        select(Sprint).where(
            Sprint.team_id == team.id,
            Sprint.status == SprintStatus.ACTIVE,
        )
    )
    if active_sprint:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "detail": "An active sprint is in progress. Complete it before pushing a new plan.",
                "currentSprintName": active_sprint.name or "",
            },
        )

    # 3. Get JiraConnection for org — 402 if not found
    connection = await db.scalar(
        select(JiraConnection).where(
            JiraConnection.organization_id == team.organization_id,
            JiraConnection.is_active.is_(True),
        )
    )
    if not connection:
        raise HTTPException(
            status_code=402,
            detail="No active Jira connection. Connect Jira in Settings.",
        )

    # 4. Get board_id; 5. Build client
    try:
        client = await _get_fresh_client_async(connection, db)
    except JiraReauthRequired as exc:
        raise HTTPException(status_code=402, detail=str(exc))

    # 6. Create sprint in Jira
    sprint_data = await client.create_sprint(
        team.jira_board_id,
        request.sprintName,
        request.sprintStartDate,
        request.sprintEndDate,
    )

    # 7. Extract sprint id and URL
    jira_sprint_id: int = sprint_data["id"]
    sprint_url: str = sprint_data["self"]

    # 7b. Persist Omada Sprint so GET /api/sprints/completed can resolve it
    # immediately (e.g. for retro lookup) without waiting for the Celery sync.
    from src.models.sprint import Sprint as _Sprint, SprintStatus as _SprintStatus
    from datetime import date as _date
    _existing = await db.scalar(
        select(_Sprint).where(
            _Sprint.team_id == team.id,
            _Sprint.jira_sprint_id == str(jira_sprint_id),
        )
    )
    if _existing is None:
        _new_sprint = _Sprint(
            team_id=team.id,
            jira_sprint_id=str(jira_sprint_id),
            name=request.sprintName,
            status=_SprintStatus.ACTIVE,
            start_date=_date.fromisoformat(request.sprintStartDate) if request.sprintStartDate else None,
            end_date=_date.fromisoformat(request.sprintEndDate) if request.sprintEndDate else None,
        )
        db.add(_new_sprint)
        await db.flush()

    # 8. Move issues into the new sprint — only pass valid Jira issue keys (e.g. PROJ-123)
    import re as _re
    issue_keys = [
        a.ticketId for a in request.assignments
        if _re.match(r"^[A-Z][A-Z0-9_]+-\d+$", a.ticketId or "")
    ]
    move_warnings: list[str] = []
    if issue_keys:
        try:
            await client.move_issues_to_sprint(jira_sprint_id, issue_keys)
        except Exception as exc:
            # Non-fatal: sprint was created; tickets may not exist in this Jira instance
            move_warnings = issue_keys
            import logging as _log
            _log.getLogger(__name__).warning("move_issues_to_sprint skipped: %s", exc)

    # 9. Assign each ticket; collect warnings for unresolved developers
    unassigned_warnings: list[str] = move_warnings
    for assignment in request.assignments:
        account_id = await resolve_jira_account_id(assignment.developerId, str(team.id), db)
        if account_id:
            try:
                await client.assign_issue(assignment.ticketId, account_id)
            except Exception:
                unassigned_warnings.append(assignment.ticketId)
        else:
            unassigned_warnings.append(assignment.ticketId)

    # 10. Return response
    return PushToJiraResponse(
        jiraSprintId=jira_sprint_id,
        sprintUrl=sprint_url,
        pushedTickets=len(issue_keys),
        unassignedWarnings=unassigned_warnings,
    )
