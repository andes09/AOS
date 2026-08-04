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
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import pytest_asyncio
from openai import APIError, BadRequestError, RateLimitError
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
from src.services.llm_errors import LLMRateLimitError

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


class _FakeStream:
    """Async-iterable standing in for the OpenAI SDK's streaming response —
    yields pre-built chunks, one delta.tool_calls[].function.arguments
    fragment (or a trailing usage-only chunk) each."""

    def __init__(self, chunks):
        self._chunks = chunks

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for chunk in self._chunks:
            yield chunk


def _stream_chunks_for(arguments, usage):
    """Splits `arguments` into a couple of delta fragments (so accumulation
    logic is actually exercised) plus a trailing usage-only chunk, matching
    the shape confirmed against the real Groq endpoint."""
    if not arguments:
        return [SimpleNamespace(choices=[], usage=usage)]
    mid = len(arguments) // 2
    fragments = [arguments[:mid], arguments[mid:]] if mid else [arguments]
    chunks = [
        SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(
                tool_calls=[SimpleNamespace(function=SimpleNamespace(arguments=frag))]
            ))],
            usage=None,
        )
        for frag in fragments
        if frag
    ]
    chunks.append(SimpleNamespace(choices=[], usage=usage))
    return chunks


def _fake_groq(payload=None, tool_name="build_roadmap", tool_calls=None):
    """Fake AsyncOpenAI whose chat.completions.create serves both the
    non-streamed (_call_planner) and streamed (_call_planner_stream) shapes —
    picks based on the `stream` kwarg, same as the real client does."""
    if tool_calls is None:
        tool_calls = [_FakeToolCall(tool_name, payload)] if payload is not None else []
    message = SimpleNamespace(tool_calls=tool_calls or None)
    usage = SimpleNamespace(prompt_tokens=100, completion_tokens=200)
    response = SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)
    arguments = tool_calls[0].function.arguments if tool_calls else None
    stream_chunks = _stream_chunks_for(arguments, usage)

    async def create(**kwargs):
        return _FakeStream(stream_chunks) if kwargs.get("stream") else response

    fake_completions = SimpleNamespace(create=AsyncMock(side_effect=create))
    return SimpleNamespace(chat=SimpleNamespace(completions=fake_completions))


def _patch_groq(fake):
    return patch(
        "src.services.roadmap_generator.AsyncOpenAI", return_value=fake
    )


def _tool_use_failed_error():
    """A Groq 400 with code=tool_use_failed — observed live when the model's raw
    output doesn't parse as a clean tool call. Groq's own guidance is to retry.
    This is what the non-streamed path (_call_planner) raises, from a normal
    HTTP error response."""
    resp = httpx.Response(
        400, request=httpx.Request("POST", "http://groq.test"),
        json={"error": {"code": "tool_use_failed"}},
    )
    return BadRequestError("Failed to call a function.", response=resp, body={"code": "tool_use_failed"})


def _tool_use_failed_stream_error():
    """The streamed path's equivalent of _tool_use_failed_error — confirmed
    live against Groq that a mid-stream tool_use_failed surfaces as a bare
    APIError (not BadRequestError), since the SDK doesn't map SSE-delivered
    error events to status-code subclasses the way it does HTTP responses."""
    return APIError(
        "Failed to call a function. Please adjust your prompt.",
        httpx.Request("POST", "http://groq.test"),
        body={"code": "tool_use_failed"},
    )


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


# ─── _call_planner_stream (streamed, used by generate_roadmap) ─────────────────

class _RaisingStream:
    """A stream that yields a couple of chunks then raises — the shape
    confirmed live against Groq: tool_use_failed surfaces mid-iteration, not
    from the initial create() call like the non-streamed path."""

    def __init__(self, error, chunks=()):
        self._error = error
        self._chunks = chunks

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for chunk in self._chunks:
            yield chunk
        raise self._error


async def test_call_planner_stream_reports_progress_and_returns_data():
    usage = SimpleNamespace(prompt_tokens=100, completion_tokens=200)
    arguments = json.dumps(_ROADMAP_PAYLOAD)
    create_mock = AsyncMock(return_value=_FakeStream(_stream_chunks_for(arguments, usage)))
    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create_mock)))

    progress_calls = []

    async def on_progress(pct):
        progress_calls.append(pct)

    with _patch_groq(fake):
        data, returned_usage = await roadmap_generator._call_planner_stream(
            "sk-key", "sys", "user", roadmap_generator._ROADMAP_TOOL, on_progress
        )

    assert data["projectName"] == "Trail Buddy"
    assert returned_usage is usage
    assert progress_calls  # at least one update fired
    assert progress_calls == sorted(progress_calls)  # monotonic as more args arrive
    assert all(0 <= p <= 95 for p in progress_calls)
    create_mock.assert_awaited_once()
    _, kwargs = create_mock.await_args
    assert kwargs["stream"] is True
    assert kwargs["tool_choice"] == {"type": "function", "function": {"name": "build_roadmap"}}


async def test_call_planner_stream_retries_tool_use_failed_then_succeeds():
    usage = SimpleNamespace(prompt_tokens=100, completion_tokens=200)
    arguments = json.dumps(_ROADMAP_PAYLOAD)
    create_mock = AsyncMock(side_effect=[
        _RaisingStream(_tool_use_failed_stream_error()),
        _FakeStream(_stream_chunks_for(arguments, usage)),
    ])
    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create_mock)))

    with _patch_groq(fake):
        data, _ = await roadmap_generator._call_planner_stream(
            "sk-key", "sys", "user", roadmap_generator._ROADMAP_TOOL, None
        )

    assert data["projectName"] == "Trail Buddy"
    assert create_mock.await_count == 2


async def test_call_planner_stream_gives_up_after_max_tool_use_failures():
    create_mock = AsyncMock(side_effect=[
        _RaisingStream(_tool_use_failed_stream_error()) for _ in range(10)
    ])
    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create_mock)))

    with _patch_groq(fake):
        try:
            await roadmap_generator._call_planner_stream(
                "sk-key", "sys", "user", roadmap_generator._ROADMAP_TOOL, None
            )
            raise AssertionError("expected RuntimeError")
        except RuntimeError as exc:
            assert "Groq API error" in str(exc)

    assert create_mock.await_count == roadmap_generator._MAX_TOOL_RETRIES + 1


async def test_call_planner_stream_malformed_json_retries_then_succeeds():
    usage = SimpleNamespace(prompt_tokens=100, completion_tokens=200)
    good_arguments = json.dumps(_ROADMAP_PAYLOAD)
    create_mock = AsyncMock(side_effect=[
        _FakeStream(_stream_chunks_for("{not valid json", usage)),
        _FakeStream(_stream_chunks_for(good_arguments, usage)),
    ])
    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create_mock)))

    with _patch_groq(fake):
        data, _ = await roadmap_generator._call_planner_stream(
            "sk-key", "sys", "user", roadmap_generator._ROADMAP_TOOL, None
        )

    assert data["projectName"] == "Trail Buddy"
    assert create_mock.await_count == 2


async def test_call_planner_stream_empty_arguments_raises():
    empty_usage = SimpleNamespace(prompt_tokens=10, completion_tokens=0)
    create_mock = AsyncMock(side_effect=[
        _FakeStream(_stream_chunks_for(None, empty_usage)) for _ in range(10)
    ])
    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create_mock)))

    with _patch_groq(fake):
        try:
            await roadmap_generator._call_planner_stream(
                "sk-key", "sys", "user", roadmap_generator._ROADMAP_TOOL, None
            )
            raise AssertionError("expected RuntimeError")
        except RuntimeError as exc:
            assert "did not return a roadmap" in str(exc)


# ─── rate limits are terminal, never retried ───────────────────────────────────

def _rate_limit_error():
    """A Groq 429 as an HTTP response — what both call paths normally see."""
    resp = httpx.Response(
        429, request=httpx.Request("POST", "http://groq.test"),
        json={"error": {"code": "rate_limit_exceeded"}},
    )
    return RateLimitError(
        "Rate limit reached", response=resp, body={"code": "rate_limit_exceeded"}
    )


def _rate_limit_stream_error():
    """A rate limit delivered mid-stream, which reaches us as a bare APIError
    for the same reason _tool_use_failed_stream_error does."""
    return APIError(
        "Rate limit reached for model",
        httpx.Request("POST", "http://groq.test"),
        body={"code": "rate_limit_exceeded"},
    )


async def test_call_planner_rate_limit_stops_without_retrying():
    create_mock = AsyncMock(side_effect=[_rate_limit_error() for _ in range(10)])
    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create_mock)))

    with _patch_groq(fake), pytest.raises(LLMRateLimitError):
        await roadmap_generator._call_planner(
            "sk-key", "sys", "user", roadmap_generator._ROADMAP_TOOL
        )

    assert create_mock.await_count == 1


async def test_call_planner_stream_rate_limit_stops_without_retrying():
    create_mock = AsyncMock(side_effect=[_rate_limit_error() for _ in range(10)])
    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create_mock)))

    with _patch_groq(fake), pytest.raises(LLMRateLimitError):
        await roadmap_generator._call_planner_stream(
            "sk-key", "sys", "user", roadmap_generator._ROADMAP_TOOL, None
        )

    assert create_mock.await_count == 1


async def test_call_planner_stream_mid_stream_rate_limit_stops_without_retrying():
    """The streamed path has to sniff the error code (see llm_errors.
    is_rate_limit) — otherwise this would fall through to the generic
    'Groq API error' arm and lose the reason."""
    create_mock = AsyncMock(side_effect=[
        _RaisingStream(_rate_limit_stream_error()) for _ in range(10)
    ])
    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create_mock)))

    with _patch_groq(fake), pytest.raises(LLMRateLimitError):
        await roadmap_generator._call_planner_stream(
            "sk-key", "sys", "user", roadmap_generator._ROADMAP_TOOL, None
        )

    assert create_mock.await_count == 1


async def test_generate_roadmap_rate_limit_persists_nothing(roadmap_db):
    team_id, session_id = await _seed(roadmap_db)
    create_mock = AsyncMock(side_effect=[_rate_limit_error() for _ in range(10)])
    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create_mock)))

    async with roadmap_db() as db:
        session = await db.get(OnboardingSession, session_id)
        team = await db.get(Team, team_id)
        with _patch_groq(fake), pytest.raises(LLMRateLimitError):
            await roadmap_generator.generate_roadmap(session, team, "sk-key", db)

    async with roadmap_db() as db:
        assert (await db.execute(select(Project))).scalars().all() == []


# ─── _tech_stack_prompt / _brief_prompt ────────────────────────────────────────

def test_tech_stack_prompt_none_when_unset():
    session = OnboardingSession(project_brief={"projectName": "Trail Buddy"})
    assert roadmap_generator._tech_stack_prompt(session) is None
    brief_prompt = roadmap_generator._brief_prompt(session)
    assert "Project brief" in brief_prompt
    assert roadmap_generator._ENV_SETUP_GUIDANCE in brief_prompt


def test_tech_stack_prompt_experienced_names_the_stack():
    session = OnboardingSession(
        tech_experience="experienced", known_tech_stack=["React", "Postgres"],
    )
    prompt = roadmap_generator._tech_stack_prompt(session)
    assert "React, Postgres" in prompt
    assert "already knows" in prompt
    assert "installed for this project" in prompt
    assert prompt in roadmap_generator._brief_prompt(session)


def test_tech_stack_prompt_new_asks_for_beginner_setup():
    session = OnboardingSession(tech_experience="new", known_tech_stack=[])
    prompt = roadmap_generator._tech_stack_prompt(session)
    assert "new to building software" in prompt
    assert "setup" in prompt
    assert prompt in roadmap_generator._brief_prompt(session)


def test_brief_prompt_always_includes_environment_setup_guidance():
    session = OnboardingSession(project_brief={"projectName": "Trail Buddy"})
    assert roadmap_generator._ENV_SETUP_GUIDANCE in roadmap_generator._brief_prompt(session)


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


async def test_generate_roadmap_once_returns_winner_project_on_conflict(roadmap_db):
    """Simulates the prewarm-task-vs-/plan/draft race: a Project already
    exists for the session (the "winner") by the time generate_roadmap_once
    tries to create one — its commit hits Project.onboarding_session_id's
    unique constraint, and generate_roadmap_once should roll back and hand
    back the winner's project instead of raising."""
    team_id, session_id = await _seed(roadmap_db)
    fake = _fake_groq(_ROADMAP_PAYLOAD)

    async with roadmap_db() as db:
        winner = Project(id=uuid.uuid4(), team_id=team_id, onboarding_session_id=session_id, name="Winner")
        db.add(winner)
        await db.commit()
        winner_id = winner.id

    async with roadmap_db() as db:
        session = await db.get(OnboardingSession, session_id)
        team = await db.get(Team, team_id)
        with _patch_groq(fake):
            project = await roadmap_generator.generate_roadmap_once(session, team, "sk-key", db)

    assert project.id == winner_id
    async with roadmap_db() as db:
        projects = (await db.execute(select(Project))).scalars().all()
        assert [p.id for p in projects] == [winner_id]
        assert (await db.execute(select(Milestone))).scalars().all() == []


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


# ─── _prewarm_roadmap_async ────────────────────────────────────────────────────

async def test_prewarm_roadmap_async_generates_when_eligible(roadmap_db):
    _, session_id = await _seed(roadmap_db)
    fake = _fake_groq(_ROADMAP_PAYLOAD)

    async with roadmap_db() as db:
        with _patch_groq(fake), patch("src.config.settings.groq_api_key", "sk-platform"):
            await roadmap_generator._prewarm_roadmap_async(str(session_id), db)

    async with roadmap_db() as db:
        projects = (await db.execute(select(Project))).scalars().all()
        assert [p.name for p in projects] == ["Trail Buddy"]


async def test_prewarm_roadmap_async_noop_when_session_not_completed(roadmap_db):
    _, session_id = await _seed(roadmap_db)
    async with roadmap_db() as db:
        session = await db.get(OnboardingSession, session_id)
        session.status = "in_progress"
        await db.commit()

    fake = _fake_groq(_ROADMAP_PAYLOAD)
    async with roadmap_db() as db:
        with _patch_groq(fake), patch("src.config.settings.groq_api_key", "sk-platform"):
            await roadmap_generator._prewarm_roadmap_async(str(session_id), db)

    assert fake.chat.completions.create.await_count == 0
    async with roadmap_db() as db:
        assert (await db.execute(select(Project))).scalars().all() == []


async def test_prewarm_roadmap_async_noop_when_project_already_exists(roadmap_db):
    team_id, session_id = await _seed(roadmap_db)
    async with roadmap_db() as db:
        db.add(Project(id=uuid.uuid4(), team_id=team_id, onboarding_session_id=session_id, name="Existing"))
        await db.commit()

    fake = _fake_groq(_ROADMAP_PAYLOAD)
    async with roadmap_db() as db:
        with _patch_groq(fake), patch("src.config.settings.groq_api_key", "sk-platform"):
            await roadmap_generator._prewarm_roadmap_async(str(session_id), db)

    assert fake.chat.completions.create.await_count == 0
    async with roadmap_db() as db:
        projects = (await db.execute(select(Project))).scalars().all()
        assert [p.name for p in projects] == ["Existing"]


async def test_prewarm_roadmap_async_noop_when_no_groq_key(roadmap_db):
    _, session_id = await _seed(roadmap_db)
    fake = _fake_groq(_ROADMAP_PAYLOAD)

    async with roadmap_db() as db:
        with _patch_groq(fake), patch("src.config.settings.groq_api_key", ""):
            await roadmap_generator._prewarm_roadmap_async(str(session_id), db)

    assert fake.chat.completions.create.await_count == 0
    async with roadmap_db() as db:
        assert (await db.execute(select(Project))).scalars().all() == []


# ─── prewarm_roadmap (the Celery task's retry policy) ──────────────────────────

class _FakeSessionCtx:
    """Stands in for AsyncSessionLocal() — the prewarm task only needs the
    context manager and a rollback on the error path."""

    async def __aenter__(self):
        return SimpleNamespace(rollback=AsyncMock())

    async def __aexit__(self, *exc):
        return False


def _patch_prewarm(error):
    return (
        patch("src.services.roadmap_generator.AsyncSessionLocal", _FakeSessionCtx),
        patch(
            "src.services.roadmap_generator._prewarm_roadmap_async",
            AsyncMock(side_effect=error),
        ),
        patch.object(
            roadmap_generator.prewarm_roadmap, "retry",
            MagicMock(return_value=RuntimeError("retried")),
        ),
    )


def test_prewarm_roadmap_task_does_not_retry_on_rate_limit():
    """Retrying 15s into the same quota window just burns it again — and the
    prefetch is optional, since /plan/draft generates on demand."""
    sessions, prewarm, retry = _patch_prewarm(LLMRateLimitError("rate limited"))
    with sessions, prewarm, retry as retry_mock:
        roadmap_generator.prewarm_roadmap.run(str(uuid.uuid4()))
    retry_mock.assert_not_called()


def test_prewarm_roadmap_task_still_retries_other_failures():
    sessions, prewarm, retry = _patch_prewarm(RuntimeError("Groq API error: boom"))
    with sessions, prewarm, retry as retry_mock:
        with pytest.raises(RuntimeError):
            roadmap_generator.prewarm_roadmap.run(str(uuid.uuid4()))
    retry_mock.assert_called_once()
