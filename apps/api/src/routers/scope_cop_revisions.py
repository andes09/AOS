"""Single-ticket Scope Cop revision router (Initiative B, Wave 2 / SB-7).

The "Refine one ticket" path — distinct from the batched commit (SB-8). Two
endpoints, both lead-gated:

GET  /api/scope-cop/tickets/{ticket_key}/revision-preview
    Returns ``{original, suggested_revision, fetched_updated_at}`` for the
    inline-refinement modal. ``original`` is the live Jira state; the suggestion
    comes from the cached ``ticket_analyses.suggested_revision`` row, or a fresh
    Scope Cop run when none is cached.

PATCH /api/scope-cop/tickets/{ticket_key}
    Applies a (possibly user-edited) revision to Jira after an optimistic
    stale-write check, writes a ``ticket_revisions`` audit row, and re-runs
    Scope Cop scoring so the readiness score reflects the edit.

Consumes — but does not modify — the Jira client, the Scope Cop service, and
the shared auth/db dependencies. Team resolution, Jira client construction, and
the response model are reused from ``src.routers.scope_cop``.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_org_id
from src.auth_roles import require_role
from src.database import get_db
from src.models.organization import Organization
from src.models.scope_cop import TicketAnalysis
from src.models.team import Team
from src.models.ticket_revision import TicketRevision
from src.routers.scope_cop import (
    TicketAnalysisResult,
    _get_jira_client,
    _resolve_team,
)
from src.services.scope_cop import analyze_tickets

scope_cop_revisions_router = APIRouter(tags=["scope-cop"])

# Story-points custom field. The Scope Cop service (`_fetch_ticket`) and the
# Jira sync both treat ``customfield_10016`` as the primary story-points field
# (``customfield_10028`` is a legacy fallback used only on read). We write to
# the primary field on push.
STORY_POINTS_FIELD = "customfield_10016"


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class RevisionInput(BaseModel):
    """The revision payload a user accepts/edits before push.

    All fields optional — only the keys present are mapped into the Jira
    ``fields`` update, so a caller can push e.g. only ``story_points``.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    title: str | None = None
    description: str | None = None
    acceptance_criteria: list[str] | None = None
    story_points: int | float | None = None


class RevisionPreviewResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    original: dict
    suggested_revision: dict | None = None
    fetched_updated_at: str | None = None


class PatchRevisionRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    revision: RevisionInput
    fetched_updated_at: str
    team_id: str


class PatchRevisionResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    committed: bool
    result: TicketAnalysisResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _resolve_team_or_default(
    team_id: str, clerk_org_id: str, db: AsyncSession
) -> Team:
    """Resolve a team id, accepting the ``"default"`` sentinel.

    Mirrors ``src.routers.scope_cop.analyze``: ``"default"`` maps to the first
    team of the caller's org; any other value is a team UUID.
    """
    if team_id == "default":
        org = await db.scalar(
            select(Organization).where(Organization.clerk_org_id == clerk_org_id)
        )
        if not org:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Organisation not found."
            )
        team = await db.scalar(select(Team).where(Team.organization_id == org.id))
        if not team:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Team not found."
            )
        return team
    return await _resolve_team(team_id, db)


def _shape_original(issue: dict) -> dict:
    """Project a raw Jira ``get_issue`` payload to ``{title, description, story_points}``.

    ``get_issue`` returns ADF for ``description``; the preview surfaces it as-is
    (the UI flattens). Story points are not in ``get_issue``'s field set, so this
    best-effort reads whichever custom field is present (None otherwise).
    """
    fields = issue.get("fields") or {}
    story_points = (
        fields.get("story_points")
        or fields.get(STORY_POINTS_FIELD)
        or fields.get("customfield_10028")
    )
    return {
        "title": fields.get("summary"),
        "description": fields.get("description"),
        "story_points": story_points,
    }


def _build_jira_fields(revision: RevisionInput) -> dict:
    """Map a ``RevisionInput`` to a Jira ``fields`` update dict.

    Only keys explicitly provided by the caller are emitted (``exclude_unset``)
    so a partial revision never blanks untouched fields.

    - ``title`` → ``summary``
    - ``description`` → ``description`` (plain text; the client wraps ADF)
    - ``story_points`` → ``customfield_10016``
    - ``acceptance_criteria`` → appended to the description text. There is no
      standard Jira AC field in this Jira instance, so AC is folded into the
      description as an "Acceptance Criteria" bullet list rather than dropped.
    """
    provided = revision.model_dump(exclude_unset=True)
    fields: dict = {}

    if "title" in provided:
        fields["summary"] = revision.title

    description = revision.description if "description" in provided else None
    ac = revision.acceptance_criteria if "acceptance_criteria" in provided else None
    if ac:
        ac_block = "Acceptance Criteria:\n" + "\n".join(f"- {item}" for item in ac)
        description = f"{description}\n\n{ac_block}" if description else ac_block
    if description is not None:
        fields["description"] = description

    if "story_points" in provided and revision.story_points is not None:
        fields[STORY_POINTS_FIELD] = revision.story_points

    return fields


async def _load_cached_suggestion(
    team_id: str, ticket_key: str, db: AsyncSession
) -> dict | None:
    """Read the cached ``ticket_analyses.suggested_revision`` for this ticket."""
    row = await db.scalar(
        select(TicketAnalysis).where(
            TicketAnalysis.team_id == uuid.UUID(team_id),
            TicketAnalysis.ticket_key == ticket_key,
        )
    )
    return row.suggested_revision if row else None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@scope_cop_revisions_router.get(
    "/tickets/{ticket_key}/revision-preview",
    response_model=RevisionPreviewResponse,
)
async def revision_preview(
    ticket_key: str,
    team_id: str,
    _: str = Depends(require_role("lead")),
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """Return the live Jira state + Scope Cop's suggested fix for one ticket.

    Reads the cached suggestion when present; otherwise runs a fresh Scope Cop
    analysis. ``fetched_updated_at`` is Jira's last-modified stamp, echoed back
    by the client on PATCH for stale-write detection.
    """
    team = await _resolve_team_or_default(team_id, clerk_org_id, db)
    resolved_team_id = str(team.id)
    jira_client = await _get_jira_client(team, db)

    issue = await jira_client.get_issue(ticket_key)
    original = _shape_original(issue)
    fetched_updated_at = (issue.get("fields") or {}).get("updated")

    suggested_revision = await _load_cached_suggestion(resolved_team_id, ticket_key, db)
    if suggested_revision is None:
        try:
            results = await analyze_tickets(
                team_id=resolved_team_id,
                ticket_keys=[ticket_key],
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
        if results:
            suggested_revision = results[0].suggested_revision
            if fetched_updated_at is None:
                fetched_updated_at = results[0].fetched_updated_at

    return RevisionPreviewResponse(
        original=original,
        suggested_revision=suggested_revision,
        fetched_updated_at=fetched_updated_at,
    )


@scope_cop_revisions_router.patch(
    "/tickets/{ticket_key}",
    response_model=PatchRevisionResponse,
)
async def apply_revision(
    ticket_key: str,
    request: PatchRevisionRequest,
    _: str = Depends(require_role("lead")),
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """Apply a single-ticket revision to Jira and re-score it.

    Flow: stale check (409 on conflict) → snapshot pre-edit state → push to
    Jira → write a ``ticket_revisions`` audit row → re-run Scope Cop scoring.
    """
    team = await _resolve_team_or_default(request.team_id, clerk_org_id, db)
    resolved_team_id = str(team.id)
    jira_client = await _get_jira_client(team, db)

    # 1. Optimistic concurrency: reject if Jira moved under us.
    if await jira_client.check_stale(ticket_key, request.fetched_updated_at):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="ticket modified in Jira since fetch",
        )

    # 2. Snapshot pre-edit Jira state for future rollback (best effort).
    pre_issue = await jira_client.get_issue(ticket_key)

    # 3. Map the (possibly user-edited) revision to Jira fields and push.
    fields = _build_jira_fields(request.revision)
    if fields:
        await jira_client.update_issue(ticket_key, fields)

    # 4. Audit row — cached suggestion vs. what was actually applied.
    cached_suggestion = await _load_cached_suggestion(
        resolved_team_id, ticket_key, db
    )
    db.add(
        TicketRevision(
            team_id=team.id,
            ticket_key=ticket_key,
            suggested_revision=cached_suggestion or {},
            applied_revision=request.revision.model_dump(
                exclude_unset=True, by_alias=False
            ),
            original_jira_state=pre_issue,
            applied_at=datetime.now(timezone.utc),
            applied_by=None,
        )
    )
    await db.commit()

    # 5. Re-score so the readiness reflects the edit.
    results = await analyze_tickets(
        team_id=resolved_team_id,
        ticket_keys=[ticket_key],
        jira_client=jira_client,
        db=db,
    )
    if not results:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Re-scoring returned no result for the updated ticket.",
        )
    r = results[0]
    result = TicketAnalysisResult(
        ticket_key=r.ticket_key,
        ticket_title=r.ticket_title,
        readiness_score=r.readiness_score,
        status=r.status,
        issues=r.issues,
        suggestions=r.suggestions,
        stack_alignment=r.stack_alignment,
        matched_identifier_count=r.matched_identifier_count,
        suggested_revision=r.suggested_revision,
        fetched_updated_at=r.fetched_updated_at,
    )

    return PatchRevisionResponse(committed=True, result=result)
