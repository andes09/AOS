"""
Unit tests for services/roadmap_generator — Groq (OpenAI-compatible) calls are
mocked, the DB is an in-memory sqlite scoped to just the tables this feature
touches (the shared tmp_db fixture pulls in models whose bare-JSONB columns
break on sqlite).
"""

import json
import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest_asyncio
from openai import BadRequestError
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
from src.models.task import Task, task_dependencies
from src.services import roadmap_generator
from src.services.idea_interview import _PURPOSE_GUIDANCE

_REQUIRED_TABLES = [
    Organization.__table__,
    Team.__table__,
    OnboardingSession.__table__,
    Project.__table__,
    Milestone.__table__,
    Task.__table__,
    task_dependencies,
]

_BRIEF = {"projectName": "Brief Name", "problemStatement": "Founders lack plans"}


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


async def _seed(Session, purpose="hobby"):
    """Org + team + completed onboarding session with a brief. Returns ids."""
    org_id, team_id, session_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with Session() as db:
        db.add_all([
            Organization(id=org_id, clerk_org_id="org_x", name="Org X", slug="org-x"),
            Team(id=team_id, organization_id=org_id, name="Team X"),
            OnboardingSession(
                id=session_id,
                organization_id=org_id,
                status="completed",
                project_brief=_BRIEF,
                project_purpose=purpose,
            ),
        ])
        await db.commit()
    return team_id, session_id


# ─── Groq (OpenAI-compatible) fakes ─────────────────────────────────────────────

class _FakeToolCall:
    def __init__(self, name, payload):
        self.function = SimpleNamespace(name=name, arguments=json.dumps(payload))


def _fake_groq(payload=None, tool_name="build_roadmap", tool_calls=None):
    """Fake AsyncOpenAI whose chat.completions.create returns the given tool call."""
    if tool_calls is None:
        tool_calls = [_FakeToolCall(tool_name, payload)] if payload is not None else []
    message = SimpleNamespace(tool_calls=tool_calls or None)
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=message)],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=200),
    )
    fake_completions = SimpleNamespace(create=AsyncMock(return_value=response))
    return SimpleNamespace(chat=SimpleNamespace(completions=fake_completions))


def _patch_groq(fake):
    return patch(
        "src.services.roadmap_generator.AsyncOpenAI", return_value=fake
    )


def _tool_use_failed_error():
    """A Groq 400 with code=tool_use_failed — observed live when the model's raw
    output doesn't parse as a clean tool call. Groq's own guidance is to retry."""
    resp = httpx.Response(
        400, request=httpx.Request("POST", "http://groq.test"),
        json={"error": {"code": "tool_use_failed"}},
    )
    return BadRequestError("Failed to call a function.", response=resp, body={"code": "tool_use_failed"})


_ROADMAP_PAYLOAD = {
    "projectName": "Trail Buddy",
    "summary": "Two weeks to a hikeable MVP.",
    "milestones": [
        {
            "title": "Foundations",
            "description": "Set up the skeleton",
            "tasks": [
                {"title": "Init repo", "dayOffset": 0, "key": "init-repo"},
                {
                    "title": "Pick stack",
                    "description": "Keep it boring",
                    "dayOffset": 1,
                    "dependsOn": ["init-repo"],
                },
            ],
        },
        {
            "title": "Core loop",
            "tasks": [{"title": "Build map view", "dayOffset": 3}],
        },
    ],
}


# ─── _call_planner retry on tool_use_failed ────────────────────────────────────

async def test_call_planner_retries_tool_use_failed_then_succeeds():
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(
            tool_calls=[_FakeToolCall("build_roadmap", _ROADMAP_PAYLOAD)]
        ))],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=200),
    )
    create_mock = AsyncMock(side_effect=[_tool_use_failed_error(), response])
    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create_mock)))

    with _patch_groq(fake):
        data, usage = await roadmap_generator._call_planner(
            "sk-key", "sys", "user", roadmap_generator._ROADMAP_TOOL
        )

    assert data["projectName"] == "Trail Buddy"
    assert create_mock.await_count == 2


async def test_call_planner_gives_up_after_max_tool_use_failures():
    create_mock = AsyncMock(side_effect=[_tool_use_failed_error() for _ in range(10)])
    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create_mock)))

    with _patch_groq(fake):
        try:
            await roadmap_generator._call_planner(
                "sk-key", "sys", "user", roadmap_generator._ROADMAP_TOOL
            )
            raise AssertionError("expected RuntimeError")
        except RuntimeError as exc:
            assert "Groq API error" in str(exc)

    assert create_mock.await_count == roadmap_generator._MAX_TOOL_RETRIES + 1


# ─── _tech_stack_prompt / _brief_prompt ────────────────────────────────────────

def test_tech_stack_prompt_none_when_unset():
    session = OnboardingSession(project_brief={"projectName": "Trail Buddy"})
    assert roadmap_generator._tech_stack_prompt(session) is None
    assert "Project brief" in roadmap_generator._brief_prompt(session)


def test_tech_stack_prompt_experienced_names_the_stack():
    session = OnboardingSession(
        tech_experience="experienced", known_tech_stack=["React", "Postgres"],
    )
    prompt = roadmap_generator._tech_stack_prompt(session)
    assert "React, Postgres" in prompt
    assert "already knows" in prompt
    assert prompt in roadmap_generator._brief_prompt(session)


def test_tech_stack_prompt_new_asks_for_beginner_setup():
    session = OnboardingSession(tech_experience="new", known_tech_stack=[])
    prompt = roadmap_generator._tech_stack_prompt(session)
    assert "new to building software" in prompt
    assert "setup" in prompt
    assert prompt in roadmap_generator._brief_prompt(session)


# ─── generate_roadmap ──────────────────────────────────────────────────────────

async def test_generate_roadmap_happy_path(roadmap_db):
    team_id, session_id = await _seed(roadmap_db, purpose="hobby")
    fake = _fake_groq(_ROADMAP_PAYLOAD)

    async with roadmap_db() as db:
        session = await db.get(OnboardingSession, session_id)
        team = await db.get(Team, team_id)
        with _patch_groq(fake):
            project = await roadmap_generator.generate_roadmap(session, team, "sk-key", db)

    # Forced-tool call with purpose steering in the system prompt.
    call = fake.chat.completions.create.await_args.kwargs
    assert call["tool_choice"] == {"type": "function", "function": {"name": "build_roadmap"}}
    assert _PURPOSE_GUIDANCE["hobby"] in call["messages"][0]["content"]
    assert "Brief Name" in call["messages"][1]["content"]

    async with roadmap_db() as db:
        saved = await db.get(Project, project.id)
        assert saved.name == "Trail Buddy"
        assert saved.summary == "Two weeks to a hikeable MVP."
        assert saved.purpose == "hobby"
        assert saved.onboarding_session_id == session_id

        milestones = (await db.execute(
            select(Milestone).where(Milestone.project_id == saved.id).order_by(Milestone.sort_order)
        )).scalars().all()
        assert [m.title for m in milestones] == ["Foundations", "Core loop"]
        assert [m.sort_order for m in milestones] == [0, 1]

        tasks = (await db.execute(
            select(Task)
            .where(Task.milestone_id == milestones[0].id)
            .order_by(Task.sort_order)
            .options(selectinload(Task.depends_on))
        )).scalars().all()
        assert [t.title for t in tasks] == ["Init repo", "Pick stack"]
        assert [t.sort_order for t in tasks] == [0, 1]
        # "Pick stack" declared dependsOn: ["init-repo"] — resolved to a real edge.
        assert tasks[0].depends_on == []
        assert tasks[1].depends_on == [tasks[0]]
        for t in tasks:
            assert t.scheduled_date is not None
            assert t.scheduled_date.weekday() < 5  # only weekdays
            assert t.scheduled_date >= date.today()


async def test_generate_roadmap_no_tool_block_persists_nothing(roadmap_db):
    team_id, session_id = await _seed(roadmap_db)
    fake = _fake_groq(tool_calls=[])

    async with roadmap_db() as db:
        session = await db.get(OnboardingSession, session_id)
        team = await db.get(Team, team_id)
        with _patch_groq(fake):
            try:
                await roadmap_generator.generate_roadmap(session, team, "sk-key", db)
                raise AssertionError("expected RuntimeError")
            except RuntimeError as exc:
                assert "did not return a roadmap" in str(exc)

    async with roadmap_db() as db:
        assert (await db.execute(select(Project))).scalars().all() == []


async def test_generate_roadmap_empty_milestones_persists_nothing(roadmap_db):
    team_id, session_id = await _seed(roadmap_db)
    fake = _fake_groq({"projectName": "X", "milestones": []})

    async with roadmap_db() as db:
        session = await db.get(OnboardingSession, session_id)
        team = await db.get(Team, team_id)
        with _patch_groq(fake):
            try:
                await roadmap_generator.generate_roadmap(session, team, "sk-key", db)
                raise AssertionError("expected RuntimeError")
            except RuntimeError as exc:
                assert "empty roadmap" in str(exc)

    async with roadmap_db() as db:
        assert (await db.execute(select(Project))).scalars().all() == []
        assert (await db.execute(select(Milestone))).scalars().all() == []


async def test_generate_roadmap_cyclic_dependency_persists_nothing(roadmap_db):
    """A cyclic dependsOn graph in the model output is rejected outright —
    the same failure class as other malformed-output cases (surfaced by the
    router as a 502), and nothing partial is left behind."""
    team_id, session_id = await _seed(roadmap_db)
    payload = {
        "projectName": "Cyclic",
        "milestones": [
            {
                "title": "M0",
                "tasks": [
                    {"title": "A", "dayOffset": 0, "key": "a", "dependsOn": ["b"]},
                    {"title": "B", "dayOffset": 0, "key": "b", "dependsOn": ["a"]},
                ],
            },
        ],
    }
    fake = _fake_groq(payload)

    async with roadmap_db() as db:
        session = await db.get(OnboardingSession, session_id)
        team = await db.get(Team, team_id)
        with _patch_groq(fake):
            try:
                await roadmap_generator.generate_roadmap(session, team, "sk-key", db)
                raise AssertionError("expected RuntimeError")
            except RuntimeError as exc:
                assert "invalid task dependency graph" in str(exc)

    async with roadmap_db() as db:
        assert (await db.execute(select(Project))).scalars().all() == []


async def test_generate_roadmap_dangling_dependency_persists_nothing(roadmap_db):
    """A dependsOn reference to a key that doesn't exist in the response is
    rejected the same way — never silently dropped on the strict (fresh
    generation) path."""
    team_id, session_id = await _seed(roadmap_db)
    payload = {
        "projectName": "Dangling",
        "milestones": [
            {
                "title": "M0",
                "tasks": [{"title": "A", "dayOffset": 0, "key": "a", "dependsOn": ["ghost"]}],
            },
        ],
    }
    fake = _fake_groq(payload)

    async with roadmap_db() as db:
        session = await db.get(OnboardingSession, session_id)
        team = await db.get(Team, team_id)
        with _patch_groq(fake):
            try:
                await roadmap_generator.generate_roadmap(session, team, "sk-key", db)
                raise AssertionError("expected RuntimeError")
            except RuntimeError as exc:
                assert "doesn't exist in this batch" in str(exc)

    async with roadmap_db() as db:
        assert (await db.execute(select(Project))).scalars().all() == []


async def test_generate_roadmap_cross_milestone_dependency_persists(roadmap_db):
    """dependsOn can reference a task in an earlier milestone, not just a
    same-milestone sibling."""
    team_id, session_id = await _seed(roadmap_db)
    payload = {
        "projectName": "Cross-milestone",
        "milestones": [
            {"title": "M0", "tasks": [{"title": "Setup", "dayOffset": 0, "key": "setup"}]},
            {
                "title": "M1",
                "tasks": [{"title": "Deploy", "dayOffset": 1, "dependsOn": ["setup"]}],
            },
        ],
    }
    fake = _fake_groq(payload)

    async with roadmap_db() as db:
        session = await db.get(OnboardingSession, session_id)
        team = await db.get(Team, team_id)
        with _patch_groq(fake):
            await roadmap_generator.generate_roadmap(session, team, "sk-key", db)

    async with roadmap_db() as db:
        tasks = (
            await db.execute(select(Task).options(selectinload(Task.depends_on)))
        ).scalars().all()
        setup = next(t for t in tasks if t.title == "Setup")
        deploy = next(t for t in tasks if t.title == "Deploy")
        assert deploy.depends_on == [setup]


async def test_generate_roadmap_convergent_dependency_persists_both_edges(roadmap_db):
    """A task with two independent prerequisites persists both edges."""
    team_id, session_id = await _seed(roadmap_db)
    payload = {
        "projectName": "Convergent",
        "milestones": [
            {
                "title": "M0",
                "tasks": [
                    {"title": "Backend", "dayOffset": 0, "key": "backend"},
                    {"title": "Frontend", "dayOffset": 0, "key": "frontend"},
                    {"title": "Integrate", "dayOffset": 1, "dependsOn": ["backend", "frontend"]},
                ],
            },
        ],
    }
    fake = _fake_groq(payload)

    async with roadmap_db() as db:
        session = await db.get(OnboardingSession, session_id)
        team = await db.get(Team, team_id)
        with _patch_groq(fake):
            await roadmap_generator.generate_roadmap(session, team, "sk-key", db)

    async with roadmap_db() as db:
        tasks = (
            await db.execute(select(Task).options(selectinload(Task.depends_on)))
        ).scalars().all()
        integrate = next(t for t in tasks if t.title == "Integrate")
        assert {t.title for t in integrate.depends_on} == {"Backend", "Frontend"}


async def test_generate_roadmap_clamps_and_defaults(roadmap_db):
    team_id, session_id = await _seed(roadmap_db)
    payload = {
        "milestones": [{
            "title": "",  # falls back to Phase 1
            "tasks": [
                {"title": "Way out", "dayOffset": 999},   # clamped to _MAX_DAY_OFFSET
                {"title": "Bad offset", "dayOffset": "nope"},  # coerced to 0
            ],
        }],
    }
    fake = _fake_groq(payload)

    async with roadmap_db() as db:
        session = await db.get(OnboardingSession, session_id)
        team = await db.get(Team, team_id)
        with _patch_groq(fake):
            project = await roadmap_generator.generate_roadmap(session, team, "sk-key", db)

    async with roadmap_db() as db:
        saved = await db.get(Project, project.id)
        assert saved.name == "Brief Name"  # projectName fallback from the brief
        milestone = (await db.execute(
            select(Milestone).where(Milestone.project_id == saved.id)
        )).scalar_one()
        assert milestone.title == "Phase 1"
        tasks = (await db.execute(
            select(Task).where(Task.milestone_id == milestone.id).order_by(Task.sort_order)
        )).scalars().all()
        far, near = tasks[0].scheduled_date, tasks[1].scheduled_date
        assert far == roadmap_generator._weekday_after(
            date.today(), roadmap_generator._MAX_DAY_OFFSET
        )
        assert near == roadmap_generator._weekday_after(date.today(), 0)


# ─── regenerate_roadmap ────────────────────────────────────────────────────────

async def test_regenerate_roadmap_keeps_project_id_and_replaces_content(roadmap_db):
    team_id, session_id = await _seed(roadmap_db)
    fake = _fake_groq(_ROADMAP_PAYLOAD)

    async with roadmap_db() as db:
        session = await db.get(OnboardingSession, session_id)
        team = await db.get(Team, team_id)
        with _patch_groq(fake):
            first = await roadmap_generator.generate_roadmap(session, team, "sk-key", db)

    regen_payload = {
        "projectName": "Trail Buddy 2",
        "milestones": [{"title": "Restart", "tasks": [{"title": "Redo it", "dayOffset": 0}]}],
    }
    fake2 = _fake_groq(regen_payload)
    async with roadmap_db() as db:
        session = await db.get(OnboardingSession, session_id)
        team = await db.get(Team, team_id)
        with _patch_groq(fake2):
            second = await roadmap_generator.regenerate_roadmap(session, team, "sk-key", db)

    assert second.id == first.id  # Project row preserved

    async with roadmap_db() as db:
        saved = await db.get(Project, first.id)
        assert saved.name == "Trail Buddy 2"
        milestones = (await db.execute(
            select(Milestone).where(Milestone.project_id == saved.id)
        )).scalars().all()
        assert [m.title for m in milestones] == ["Restart"]
        # No orphaned tasks from the first generation.
        all_tasks = (await db.execute(select(Task))).scalars().all()
        assert [t.title for t in all_tasks] == ["Redo it"]


# ─── regenerate_milestone ──────────────────────────────────────────────────────

async def _seed_roadmap(Session, session_id, team_id):
    """Persist a 3-milestone roadmap directly. Returns (project_id, milestone_ids)."""
    project_id = uuid.uuid4()
    milestone_ids = [uuid.uuid4() for _ in range(3)]
    async with Session() as db:
        db.add(Project(
            id=project_id, team_id=team_id, onboarding_session_id=session_id,
            name="Seeded", purpose="hobby",
        ))
        await db.flush()
        for i, mid in enumerate(milestone_ids):
            db.add(Milestone(id=mid, project_id=project_id, title=f"M{i}", sort_order=i))
            await db.flush()
            db.add(Task(milestone_id=mid, title=f"M{i} task", sort_order=0))
        await db.commit()
    return project_id, milestone_ids


async def test_regenerate_milestone_touches_only_the_target(roadmap_db):
    team_id, session_id = await _seed(roadmap_db)
    project_id, milestone_ids = await _seed_roadmap(roadmap_db, session_id, team_id)

    payload = {
        "title": "M1 rebuilt",
        "description": "Sharper phase",
        "tasks": [
            {"title": "New task A", "dayOffset": 0},
            {"title": "New task B", "dayOffset": 1},
        ],
    }
    fake = _fake_groq(payload, tool_name="rebuild_milestone")

    async with roadmap_db() as db:
        session = await db.get(OnboardingSession, session_id)
        target = await db.get(Milestone, milestone_ids[1])
        with _patch_groq(fake):
            result = await roadmap_generator.regenerate_milestone(target, session, "sk-key", db)

    # The prompt carried the full outline with the target marked.
    call = fake.chat.completions.create.await_args.kwargs
    assert call["tool_choice"] == {"type": "function", "function": {"name": "rebuild_milestone"}}
    assert '"isTarget": true' in call["messages"][1]["content"]

    assert result.id == milestone_ids[1]
    async with roadmap_db() as db:
        target = await db.get(Milestone, milestone_ids[1])
        assert target.title == "M1 rebuilt"
        assert target.description == "Sharper phase"
        assert target.sort_order == 1  # position kept
        new_tasks = (await db.execute(
            select(Task).where(Task.milestone_id == target.id).order_by(Task.sort_order)
        )).scalars().all()
        assert [t.title for t in new_tasks] == ["New task A", "New task B"]

        # Siblings byte-identical.
        for i in (0, 2):
            sibling = await db.get(Milestone, milestone_ids[i])
            assert sibling.title == f"M{i}"
            tasks = (await db.execute(
                select(Task).where(Task.milestone_id == sibling.id)
            )).scalars().all()
            assert [t.title for t in tasks] == [f"M{i} task"]


async def test_regenerate_milestone_failure_leaves_everything_untouched(roadmap_db):
    team_id, session_id = await _seed(roadmap_db)
    project_id, milestone_ids = await _seed_roadmap(roadmap_db, session_id, team_id)

    fake = _fake_groq(tool_calls=[])  # no tool block → RuntimeError
    async with roadmap_db() as db:
        session = await db.get(OnboardingSession, session_id)
        target = await db.get(Milestone, milestone_ids[1])
        with _patch_groq(fake):
            try:
                await roadmap_generator.regenerate_milestone(target, session, "sk-key", db)
                raise AssertionError("expected RuntimeError")
            except RuntimeError:
                pass

    async with roadmap_db() as db:
        for i in range(3):
            milestone = await db.get(Milestone, milestone_ids[i])
            assert milestone.title == f"M{i}"
            tasks = (await db.execute(
                select(Task).where(Task.milestone_id == milestone.id)
            )).scalars().all()
            assert [t.title for t in tasks] == [f"M{i} task"]
