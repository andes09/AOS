"""
Shared lookups between routers/projects.py and routers/roadmap.py.

Extracted once both routers needed the same org/project resolution — the
"used twice -> extract" rule this repo already applies elsewhere.
"""

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.milestone import Milestone
from src.models.organization import Organization
from src.models.project import Project
from src.models.task import Task
from src.models.team import Team


async def _get_org(clerk_org_id: str, db: AsyncSession) -> Organization:
    org = await db.scalar(select(Organization).where(Organization.clerk_org_id == clerk_org_id))
    if not org:
        raise HTTPException(status_code=409, detail="org_not_provisioned")
    return org


async def _owned_project(project_id: uuid.UUID, org: Organization, db: AsyncSession) -> Project:
    """Load a project, ensuring it belongs to the caller's org. 404 otherwise.

    Eager-loads milestones+tasks (ordered) and the onboarding_session, since
    every caller needs at least one of those.
    """
    project = await db.scalar(
        select(Project)
        .join(Team, Project.team_id == Team.id)
        .where(Project.id == project_id, Team.organization_id == org.id)
        .options(
            selectinload(Project.milestones).selectinload(Milestone.tasks).selectinload(Task.depends_on),
            selectinload(Project.onboarding_session),
        )
    )
    if project is None:
        raise HTTPException(status_code=404, detail="project_not_found")
    return project
