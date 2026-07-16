import uuid

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from src.database import Base
import src.models  # noqa: F401 — registers all models so relationship() string refs resolve
from src.models.organization import Organization
from src.models.team import Team
from src.models.onboarding_session import OnboardingSession
from src.models.project import Project
from src.models.milestone import Milestone
from src.models.task import Task, TaskStatus


_REQUIRED_TABLES = [
    Organization.__table__,
    Team.__table__,
    OnboardingSession.__table__,
    Project.__table__,
    Milestone.__table__,
    Task.__table__,
]


@pytest_asyncio.fixture
async def project_db():
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


async def _seed_project(Session) -> uuid.UUID:
    org_id = uuid.uuid4()
    team_id = uuid.uuid4()
    session_id = uuid.uuid4()
    project_id = uuid.uuid4()
    async with Session() as db:
        db.add_all([
            Organization(id=org_id, clerk_org_id="org_x", name="Org X", slug="org-x"),
            Team(id=team_id, organization_id=org_id, name="Team X"),
            OnboardingSession(id=session_id, organization_id=org_id, status="completed"),
        ])
        await db.flush()
        db.add(Project(
            id=project_id,
            team_id=team_id,
            onboarding_session_id=session_id,
            name="Omada Roadmap",
            summary="Ship the roadmap MVP",
            purpose="Replace ticket tracking with a milestone-based model",
        ))
        await db.commit()
    return project_id


# ---------------------------------------------------------------------------
# Relationship traversal
# ---------------------------------------------------------------------------

async def test_project_team_and_onboarding_session_traversal(project_db):
    project_id = await _seed_project(project_db)

    async with project_db() as db:
        project = (await db.execute(
            select(Project)
            .where(Project.id == project_id)
            .options(selectinload(Project.team), selectinload(Project.onboarding_session))
        )).scalar_one()
        team_id = project.team_id
        session_id = project.onboarding_session_id
        assert project.team.id == team_id
        assert project.onboarding_session.id == session_id

        team = (await db.execute(
            select(Team).where(Team.id == team_id).options(selectinload(Team.projects))
        )).scalar_one()
        assert [p.id for p in team.projects] == [project_id]

        session = (await db.execute(
            select(OnboardingSession)
            .where(OnboardingSession.id == session_id)
            .options(selectinload(OnboardingSession.project))
        )).scalar_one()
        assert session.project.id == project_id


async def test_milestone_and_task_traversal(project_db):
    project_id = await _seed_project(project_db)

    milestone_id = uuid.uuid4()
    task_id = uuid.uuid4()
    async with project_db() as db:
        db.add(Milestone(id=milestone_id, project_id=project_id, title="M1", sort_order=0))
        await db.flush()
        db.add(Task(id=task_id, milestone_id=milestone_id, title="T1", sort_order=0))
        await db.commit()

    async with project_db() as db:
        project = (await db.execute(
            select(Project).where(Project.id == project_id).options(selectinload(Project.milestones))
        )).scalar_one()
        assert [m.id for m in project.milestones] == [milestone_id]

        milestone = (await db.execute(
            select(Milestone).where(Milestone.id == milestone_id).options(selectinload(Milestone.tasks))
        )).scalar_one()
        assert milestone.project_id == project_id
        assert [t.id for t in milestone.tasks] == [task_id]

        task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one()
        assert task.milestone_id == milestone_id
        assert task.status == TaskStatus.TODO


# ---------------------------------------------------------------------------
# Ordering by sort_order
# ---------------------------------------------------------------------------

async def test_milestones_and_tasks_ordered_by_sort_order(project_db):
    project_id = await _seed_project(project_db)

    async with project_db() as db:
        db.add_all([
            Milestone(id=uuid.uuid4(), project_id=project_id, title="Third", sort_order=2),
            Milestone(id=uuid.uuid4(), project_id=project_id, title="First", sort_order=0),
            Milestone(id=uuid.uuid4(), project_id=project_id, title="Second", sort_order=1),
        ])
        await db.commit()

    async with project_db() as db:
        project = (await db.execute(
            select(Project).where(Project.id == project_id).options(selectinload(Project.milestones))
        )).scalar_one()
        assert [m.title for m in project.milestones] == ["First", "Second", "Third"]
        assert [m.sort_order for m in project.milestones] == [0, 1, 2]
        milestone_id = project.milestones[0].id  # "First"

    async with project_db() as db:
        db.add_all([
            Task(id=uuid.uuid4(), milestone_id=milestone_id, title="Third", sort_order=5),
            Task(id=uuid.uuid4(), milestone_id=milestone_id, title="First", sort_order=1),
            Task(id=uuid.uuid4(), milestone_id=milestone_id, title="Second", sort_order=3),
        ])
        await db.commit()

    async with project_db() as db:
        milestone = (await db.execute(
            select(Milestone).where(Milestone.id == milestone_id).options(selectinload(Milestone.tasks))
        )).scalar_one()
        assert [t.title for t in milestone.tasks] == ["First", "Second", "Third"]
        assert [t.sort_order for t in milestone.tasks] == [1, 3, 5]


# ---------------------------------------------------------------------------
# Cascade delete
# ---------------------------------------------------------------------------

async def test_deleting_project_cascades_to_milestones_and_tasks(project_db):
    project_id = await _seed_project(project_db)

    milestone_id = uuid.uuid4()
    task_id = uuid.uuid4()
    async with project_db() as db:
        db.add(Milestone(id=milestone_id, project_id=project_id, title="M1", sort_order=0))
        await db.flush()
        db.add(Task(id=task_id, milestone_id=milestone_id, title="T1", sort_order=0))
        await db.commit()

    async with project_db() as db:
        project = await db.get(Project, project_id)
        await db.delete(project)
        await db.commit()

    async with project_db() as db:
        assert await db.get(Project, project_id) is None
        remaining_milestones = (await db.execute(
            select(Milestone).where(Milestone.project_id == project_id)
        )).scalars().all()
        remaining_tasks = (await db.execute(
            select(Task).where(Task.milestone_id == milestone_id)
        )).scalars().all()
        assert remaining_milestones == []
        assert remaining_tasks == []
