"""
Unit tests for services/roadmap_service — direct DB tests (sqlite in-memory,
same fixture shape as test_roadmap_generator.py) for `claim_next_task`'s
dependency-graph awareness. Its own docstring used to admit "'Next' has no
dependency-graph meaning yet" — this covers the gap now that it does.

PATCH .../tasks/{id} blocking (`task_is_blocked`) is covered end-to-end in
test_roadmap.py; this file is just the one piece with no REST surface.
"""

import uuid

import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.database import Base
import src.models  # noqa: F401 — registers all models so relationship() string refs resolve
from src.models.developer import Developer
from src.models.milestone import Milestone
from src.models.onboarding_session import OnboardingSession
from src.models.organization import Organization
from src.models.project import Project
from src.models.task import Task, TaskStatus, task_dependencies
from src.models.team import Team
from src.services import roadmap_service

_REQUIRED_TABLES = [
    Organization.__table__,
    Team.__table__,
    OnboardingSession.__table__,
    Project.__table__,
    Milestone.__table__,
    Task.__table__,
    task_dependencies,
    Developer.__table__,
]


@pytest_asyncio.fixture
async def roadmap_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: Base.metadata.create_all(
            sync_conn, tables=_REQUIRED_TABLES
        ))

    Session = async_sessionmaker(engine, expire_on_commit=False)
    yield Session

    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: Base.metadata.drop_all(
            sync_conn, tables=_REQUIRED_TABLES
        ))
    await engine.dispose()


async def _seed(Session):
    org_id, team_id, session_id, dev_id, project_id, milestone_id = (uuid.uuid4() for _ in range(6))
    async with Session() as db:
        db.add_all([
            Organization(id=org_id, clerk_org_id="org_x", name="Org X", slug="org-x"),
            Team(id=team_id, organization_id=org_id, name="Team X"),
            Developer(id=dev_id, team_id=team_id, name="Dev"),
            OnboardingSession(
                id=session_id, organization_id=org_id, status="completed",
                project_brief={"projectName": "X"},
            ),
        ])
        await db.flush()
        db.add(Project(id=project_id, team_id=team_id, onboarding_session_id=session_id, name="X"))
        await db.flush()
        db.add(Milestone(id=milestone_id, project_id=project_id, title="M0", sort_order=0))
        await db.commit()
    return {
        "team_id": team_id, "dev_id": dev_id, "project_id": project_id, "milestone_id": milestone_id,
    }


async def test_claim_next_task_skips_blocked_task_for_next_unblocked_one(roadmap_db):
    """X (sort_order 0) depends on Y (not done, sort_order 2) and is blocked;
    Z (sort_order 1) has no dependencies. Without dependency-awareness,
    claim_next_task would return X purely by sort order — it must skip past
    it to Z instead."""
    seeded = await _seed(roadmap_db)
    async with roadmap_db() as db:
        x = Task(milestone_id=seeded["milestone_id"], title="X", sort_order=0, status=TaskStatus.TODO.value)
        z = Task(milestone_id=seeded["milestone_id"], title="Z", sort_order=1, status=TaskStatus.TODO.value)
        y = Task(milestone_id=seeded["milestone_id"], title="Y", sort_order=2, status=TaskStatus.TODO.value)
        db.add_all([x, z, y])
        await db.flush()
        # Insert the edge directly rather than `x.depends_on.append(y)`:
        # x/y are already flushed (persistent), so appending would need to
        # lazy-load x's existing depends_on first — synchronously
        # unsupported under asyncio (see roadmap_shapes._add_tasks's comment
        # on the same pitfall during real persistence).
        await db.execute(task_dependencies.insert().values(task_id=x.id, depends_on_task_id=y.id))
        await db.commit()

    async with roadmap_db() as db:
        project = await db.get(Project, seeded["project_id"])
        developer = await db.get(Developer, seeded["dev_id"])
        claimed = await roadmap_service.claim_next_task(project, developer, db)

    assert claimed is not None
    assert claimed.title == "Z"
    assert claimed.assignee_id == developer.id
