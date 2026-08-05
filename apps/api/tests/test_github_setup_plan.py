"""
Unit tests for services/github_setup_plan — the fixed "Get set up with GitHub"
milestone injected for founders who told onboarding they've never used GitHub.

Same in-memory sqlite scoping as test_roadmap_generator.py (the shared tmp_db
fixture pulls in models whose bare-JSONB columns break on sqlite).
"""

import uuid
from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from src.database import Base
import src.models  # noqa: F401 — registers all models so relationship() string refs resolve
from src.models.milestone import Milestone
from src.models.onboarding_session import OnboardingSession
from src.models.organization import Organization
from src.models.project import Project
from src.models.task import Task, task_dependencies
from src.models.team import Team
from src.services.github_setup_plan import (
    MILESTONE_TITLE,
    SETUP_TASKS,
    ensure_github_setup_milestone,
)

_REQUIRED_TABLES = [
    Organization.__table__,
    Team.__table__,
    OnboardingSession.__table__,
    Project.__table__,
    Milestone.__table__,
    Task.__table__,
    task_dependencies,
]


@pytest_asyncio.fixture
async def setup_db():
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


async def _seed(Session, *, needs_setup: bool, milestone_titles=("Build it", "Ship it")):
    """Org + team + session + a project with an existing roadmap. Returns ids."""
    org_id, team_id, session_id, project_id = (uuid.uuid4() for _ in range(4))
    async with Session() as db:
        db.add_all([
            Organization(id=org_id, clerk_org_id="org_x", name="Org X", slug="org-x"),
            Team(id=team_id, organization_id=org_id, name="Team X"),
            OnboardingSession(
                id=session_id,
                organization_id=org_id,
                status="completed",
                github_setup_needed_at=datetime.utcnow() if needs_setup else None,
            ),
            Project(id=project_id, team_id=team_id, onboarding_session_id=session_id, name="P"),
        ])
        await db.flush()
        for idx, title in enumerate(milestone_titles):
            db.add(Milestone(project_id=project_id, title=title, description="d", sort_order=idx))
        await db.commit()
    return session_id, project_id


async def _load(Session, project_id):
    async with Session() as db:
        milestones = (await db.scalars(
            select(Milestone)
            .where(Milestone.project_id == project_id)
            .order_by(Milestone.sort_order)
            .options(selectinload(Milestone.tasks))
        )).all()
        return milestones


async def _run(Session, session_id, project_id):
    async with Session() as db:
        session = await db.get(OnboardingSession, session_id)
        project = await db.get(Project, project_id)
        added = await ensure_github_setup_milestone(session, project, db)
        await db.commit()
        return added


@pytest.mark.asyncio
async def test_prepends_the_setup_milestone_and_shifts_the_rest(setup_db):
    session_id, project_id = await _seed(setup_db, needs_setup=True)

    assert await _run(setup_db, session_id, project_id) is True

    milestones = await _load(setup_db, project_id)
    assert [m.title for m in milestones] == [MILESTONE_TITLE, "Build it", "Ship it"]
    assert [m.sort_order for m in milestones] == [0, 1, 2]

    tasks = sorted(milestones[0].tasks, key=lambda t: t.sort_order)
    assert [t.title for t in tasks] == [t["title"] for t in SETUP_TASKS]
    # Every task needs a short_id (that's what makes PR auto-complete work) and
    # a scheduled_date (or it never surfaces in the planner's day view).
    assert all(t.short_id and t.scheduled_date for t in tasks)
    assert all(t.duration_minutes for t in tasks)
    # The last task is the one that closes the loop back into Omada.
    assert "Omada" in tasks[-1].title


@pytest.mark.asyncio
async def test_no_op_when_the_founder_never_asked(setup_db):
    session_id, project_id = await _seed(setup_db, needs_setup=False)

    assert await _run(setup_db, session_id, project_id) is False

    milestones = await _load(setup_db, project_id)
    assert [m.title for m in milestones] == ["Build it", "Ship it"]
    assert [m.sort_order for m in milestones] == [0, 1]


@pytest.mark.asyncio
async def test_is_idempotent_across_repeated_calls(setup_db):
    """Every path that shows a roadmap calls this, so it runs more than once
    for the same project — a second milestone (or a second sort_order shift)
    would corrupt the plan."""
    session_id, project_id = await _seed(setup_db, needs_setup=True)

    assert await _run(setup_db, session_id, project_id) is True
    assert await _run(setup_db, session_id, project_id) is False

    milestones = await _load(setup_db, project_id)
    assert [m.title for m in milestones] == [MILESTONE_TITLE, "Build it", "Ship it"]
    assert [m.sort_order for m in milestones] == [0, 1, 2]
    assert len(milestones[0].tasks) == len(SETUP_TASKS)


@pytest.mark.asyncio
async def test_short_ids_continue_the_org_sequence(setup_db):
    """The injected tasks must draw from the same org counter as generated
    ones — a collision would make two tasks answer to the same PR reference."""
    session_id, project_id = await _seed(setup_db, needs_setup=True)
    await _run(setup_db, session_id, project_id)

    async with setup_db() as db:
        org = (await db.scalars(select(Organization))).one()
        assert org.next_task_seq == len(SETUP_TASKS)
        short_ids = [t.short_id for t in (await db.scalars(select(Task))).all()]
    assert len(set(short_ids)) == len(SETUP_TASKS)
    assert all(sid.startswith("ORGX-") for sid in short_ids)


@pytest.mark.asyncio
async def test_works_on_a_project_with_no_milestones_yet(setup_db):
    session_id, project_id = await _seed(setup_db, needs_setup=True, milestone_titles=())

    assert await _run(setup_db, session_id, project_id) is True

    milestones = await _load(setup_db, project_id)
    assert [m.title for m in milestones] == [MILESTONE_TITLE]
