"""
The 9 v1 MCP tools. Each resolves `(org, developer)` from the verified
token's `clerk_org_id`/`developer_id` claims (see oauth_provider.py's
`load_access_token`) — never from a model-supplied parameter — so the
multi-tenant boundary holds regardless of what the calling LLM is prompted
to pass. `developer_id`/role are re-resolved fresh from the DB on every call,
never trusted stale off the token, so a role change or removal takes effect
immediately.

`project_id` resolution (added on top of the original plan doc, which
predates Project Hub's multi-project model): if omitted and the org has
exactly one active project, default to it; otherwise the tool errors with
the available project list (same shape `list_projects` returns) so the
calling agent can retry with an explicit id.
"""

import uuid
from datetime import date

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.fastmcp import FastMCP
from sqlalchemy import select

from src.auth_roles import role_at_least
from src.database import db_session
from src.models.developer import Developer
from src.models.organization import Organization
from src.models.project import Project
from src.models.team import Team
from src.routers import project_common
from src.services import idea_interview, roadmap_generator, roadmap_service as svc


class ToolError(Exception):
    """Raised for tool-facing errors — FastMCP surfaces the message to the
    calling agent as a tool error result rather than a transport failure."""


async def _identity() -> tuple[str, str, str]:
    token = get_access_token()
    if token is None or not token.claims:
        raise ToolError("Not authenticated.")
    claims = token.claims
    return claims["clerk_org_id"], claims["clerk_user_id"], claims["developer_id"]


async def _current_org_and_developer(db) -> tuple[Organization, Developer]:
    clerk_org_id, _clerk_user_id, developer_id = await _identity()
    org = await db.scalar(select(Organization).where(Organization.clerk_org_id == clerk_org_id))
    if org is None:
        raise ToolError("org_not_provisioned")
    # developer_id arrives as a plain string (AccessToken.claims is a dict —
    # see oauth_provider.py's load_access_token); Developer.id is a real
    # uuid.UUID column, so parse before binding.
    developer = await db.scalar(select(Developer).where(Developer.id == uuid.UUID(developer_id)))
    if developer is None:
        raise ToolError("developer_not_found")
    return org, developer


async def _active_projects(org: Organization, db) -> list[Project]:
    rows = (
        await db.execute(
            select(Project)
            .join(Team, Project.team_id == Team.id)
            .where(Team.organization_id == org.id, Project.status == "active")
            .order_by(Project.created_at)
        )
    ).scalars().all()
    return list(rows)


def _project_summary(p: Project) -> dict:
    return {"id": str(p.id), "name": p.name, "status": p.status}


async def _resolve_project(org: Organization, project_id: str | None, db) -> Project:
    """The project_id-resolution rule described in the module docstring.

    `_owned_project` expects a real `uuid.UUID` — REST call sites get one
    pre-parsed by FastAPI's path-param binding, but MCP tool args arrive as
    plain strings, so parse explicitly here rather than relying on implicit
    dialect coercion (works on Postgres, not guaranteed on SQLite/tests).
    """
    if project_id is not None:
        try:
            pid = uuid.UUID(project_id)
        except ValueError:
            raise ToolError("project_not_found")
        return await project_common._owned_project(pid, org, db)  # noqa: SLF001 — shared ownership check
    active = await _active_projects(org, db)
    if len(active) == 1:
        return await project_common._owned_project(active[0].id, org, db)  # noqa: SLF001
    raise ToolError(
        "project_id is required (the org has "
        f"{'no' if not active else 'more than one'} active project) — "
        f"call list_projects first. Available: {[_project_summary(p) for p in active]}"
    )


def register_tools(mcp: FastMCP) -> None:
    """Registers all 9 tools on `mcp`. Called once from main.py at mount time."""

    @mcp.tool()
    async def list_projects() -> dict:
        """List the caller's organization's projects, so an agent can pick which
        project_id to use before calling any other project-scoped tool."""
        async with db_session() as db:
            org, _dev = await _current_org_and_developer(db)
            rows = (
                await db.execute(
                    select(Project)
                    .join(Team, Project.team_id == Team.id)
                    .where(Team.organization_id == org.id)
                    .order_by(Project.created_at)
                )
            ).scalars().all()
            return {"projects": [_project_summary(p) for p in rows]}

    @mcp.tool()
    async def get_roadmap(project_id: str | None = None) -> dict:
        """Full project + milestones + tasks for the caller's org. Omit
        project_id if the org has exactly one active project."""
        async with db_session() as db:
            org, _dev = await _current_org_and_developer(db)
            project = await _resolve_project(org, project_id, db)
            return svc.project_json(project)

    @mcp.tool()
    async def get_task(task_id: str, project_id: str | None = None) -> dict:
        """Single task by id, scoped to the caller's org."""
        async with db_session() as db:
            org, _dev = await _current_org_and_developer(db)
            project = await _resolve_project(org, project_id, db)
            task = await svc.owned_task(task_id, project, db)
            return svc.task_json(task)

    @mcp.tool()
    async def list_tasks(
        project_id: str | None = None,
        status: str | None = None,
        assignee_id: str | None = None,
        milestone_id: str | None = None,
        scheduled_after: str | None = None,
        scheduled_before: str | None = None,
    ) -> dict:
        """Filter tasks by status / assignee / milestone / scheduled date range
        (dates as YYYY-MM-DD)."""
        async with db_session() as db:
            org, _dev = await _current_org_and_developer(db)
            project = await _resolve_project(org, project_id, db)
            tasks = await svc.list_tasks(
                project,
                db,
                status=status,
                assignee_id=uuid.UUID(assignee_id) if assignee_id else None,
                milestone_id=uuid.UUID(milestone_id) if milestone_id else None,
                scheduled_after=date.fromisoformat(scheduled_after) if scheduled_after else None,
                scheduled_before=date.fromisoformat(scheduled_before) if scheduled_before else None,
            )
            return {"tasks": [svc.task_json(t) for t in tasks]}

    @mcp.tool()
    async def list_team_members(project_id: str | None = None) -> dict:
        """Roster + workload (open scheduled tasks) for the resolved project."""
        async with db_session() as db:
            org, _dev = await _current_org_and_developer(db)
            project = await _resolve_project(org, project_id, db)
            return await svc.get_members(org, project, db)

    @mcp.tool()
    async def get_roadmap_status(project_id: str | None = None) -> dict:
        """Onboarding/planning readiness check for the resolved project."""
        async with db_session() as db:
            org, _dev = await _current_org_and_developer(db)
            project = await _resolve_project(org, project_id, db)
            return svc.get_roadmap_status(project)

    @mcp.tool()
    async def get_next_task(project_id: str | None = None) -> dict:
        """Claims the next todo task by schedule order and self-assigns it to
        the caller's own Developer record. Returns a clean "nothing to do"
        result when the project has no unassigned todo tasks left."""
        async with db_session() as db:
            org, developer = await _current_org_and_developer(db)
            project = await _resolve_project(org, project_id, db)
            task = await svc.claim_next_task(project, developer, db)
            if task is None:
                return {"task": None, "message": "Nothing to do — no unassigned todo tasks."}
            return {"task": svc.task_json(task)}

    @mcp.tool()
    async def complete_task(
        task_id: str, completion_note: str | None = None, project_id: str | None = None
    ) -> dict:
        """Marks a task done, sets completed_at, and optionally records a
        free-text completion_note. Idempotent: calling again without a note
        does not clobber a previously-recorded one."""
        async with db_session() as db:
            org, _dev = await _current_org_and_developer(db)
            project = await _resolve_project(org, project_id, db)
            task = await svc.owned_task(task_id, project, db)
            task = await svc.complete_task(task, completion_note, db)
            return {"task": svc.task_json(task)}

    @mcp.tool()
    async def regenerate_milestone(
        milestone_id: str, confirmed: bool = False, project_id: str | None = None
    ) -> dict:
        """Triggers AI replanning of a milestone. Requires the caller to hold
        at least the 'lead' role, AND an explicit confirmed=true — this costs
        LLM spend and destructively replans existing tasks, and MCP has no
        universal human-confirmation primitive to rely on instead. Returns a
        "confirmation required" result (no data touched) if confirmed is
        false or the role gate fails."""
        async with db_session() as db:
            org, developer = await _current_org_and_developer(db)
            if not role_at_least(developer.app_role, "lead"):
                return {"error": "requires_lead_role", "yourRole": developer.app_role}
            if not confirmed:
                return {"error": "confirmation_required", "message": "Pass confirmed=true to proceed — this replaces the milestone's existing tasks."}

            project = await _resolve_project(org, project_id, db)
            milestone = await svc.owned_milestone(milestone_id, project, db)
            session = project.onboarding_session
            api_key = await idea_interview.resolve_api_key(org.clerk_org_id, db)
            try:
                await roadmap_generator.regenerate_milestone(milestone, session, api_key, db)
            except ValueError as exc:
                raise ToolError(f"bad_key: {exc}")
            except RuntimeError as exc:
                raise ToolError(f"upstream_error: {exc}")
            # Re-fetch rather than trust the returned object — see the REST
            # route's identical comment (routers/roadmap.py).
            milestone = await svc.owned_milestone(milestone_id, project, db)
            return {"milestone": svc.milestone_json(milestone)}
