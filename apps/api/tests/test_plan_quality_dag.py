"""Plan-quality telemetry for the task dependency graph.

Two independent things are under test, matching the two halves of what
`GET /roadmap/quality` returns:

* **Generation fidelity** — `resolve_task_dependencies` now reports what it
  dropped instead of only logging it. The drop *behaviour* is already covered
  by test_roadmap_planner.py (dangling/cyclic adjust cases) and
  test_artifact_import.py; what's new here is that the counts are correct and
  that `edges_proposed == edges_kept + edges_dropped` always holds.
* **DAG shape** — `compute_dag_shape` over a known graph, so the structural
  numbers are pinned to a hand-checkable answer rather than whatever the code
  happens to emit.

The pure functions are exercised on detached `Task` objects (no session): both
only need object identity and `depends_on`, so a DB round-trip would add
nothing. The endpoint test uses `tmp_db`, which is only safe because
`projects.plan_quality` is `JSON().with_variant(JSONB(), "postgresql")` — a
bare JSONB cannot be rendered on SQLite, which is why the legacy sprint-side
test_plan_quality.py had to avoid `tmp_db` entirely.
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient, ASGITransport

from src.main import app
from src.models.task import Task
from src.services.plan_quality import (
    compute_dag_shape,
    summarize_dependency_resolution,
)
from src.services.roadmap_shapes import resolve_task_dependencies, topological_levels

ORG = "org_plan_quality_dag"
USER = "user_plan_quality_dag"
AUTH = {"Authorization": "Bearer tok"}


def _task(key: str, status: str = "todo") -> Task:
    """A detached Task with `depends_on` pre-marked loaded (see roadmap_shapes._add_tasks)."""
    t = Task(id=uuid.uuid4(), milestone_id=uuid.uuid4(), title=key, status=status, sort_order=0)
    t.depends_on = []
    return t


def _patch_clerk(user_id=USER, org_id=ORG):
    payload = {"sub": user_id, "org_id": org_id}
    state = type("S", (), {"is_signed_in": True, "payload": payload})()
    return patch("src.auth._clerk.authenticate_request_async", new=AsyncMock(return_value=state))


def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ─── generation fidelity: resolve_task_dependencies stats ─────────────────────
def test_clean_graph_drops_nothing():
    tasks = {k: _task(k) for k in ("a", "b", "c")}
    stats = resolve_task_dependencies(
        tasks, {"a": [], "b": ["a"], "c": ["a", "b"]}, strict=True
    )

    assert stats == {
        "edges_proposed": 3,
        "edges_kept": 3,
        "edges_dropped": 0,
        "dropped_by_reason": {},
    }
    # Edges actually landed on the ORM objects, not just counted.
    assert [t.title for t in tasks["c"].depends_on] == ["a", "b"]


def test_dangling_reference_is_counted_as_dropped():
    tasks = {k: _task(k) for k in ("a", "b")}
    stats = resolve_task_dependencies(
        tasks, {"a": [], "b": ["a", "ghost"]}, strict=False
    )

    assert stats["dropped_by_reason"] == {"dangling": 1}
    assert (stats["edges_proposed"], stats["edges_kept"], stats["edges_dropped"]) == (2, 1, 1)
    assert [t.title for t in tasks["b"].depends_on] == ["a"]


def test_self_reference_counts_as_dangling():
    """A task depending on itself can't be a real prerequisite — same bucket."""
    tasks = {"a": _task("a")}
    stats = resolve_task_dependencies(tasks, {"a": ["a"]}, strict=False)

    assert stats["dropped_by_reason"] == {"dangling": 1}
    assert tasks["a"].depends_on == []


def test_cycle_drops_every_edge_out_of_the_cyclic_tasks():
    tasks = {k: _task(k) for k in ("a", "b")}
    stats = resolve_task_dependencies(tasks, {"a": ["b"], "b": ["a"]}, strict=False)

    # Both edges go, not just the one closing the loop.
    assert stats["dropped_by_reason"] == {"cyclic": 2}
    assert (stats["edges_kept"], stats["edges_dropped"]) == (0, 2)
    assert tasks["a"].depends_on == [] and tasks["b"].depends_on == []


def test_dangling_and_cyclic_are_bucketed_separately():
    tasks = {k: _task(k) for k in ("a", "b", "c")}
    stats = resolve_task_dependencies(
        tasks, {"a": ["b"], "b": ["a"], "c": ["ghost"]}, strict=False
    )

    assert stats["dropped_by_reason"] == {"dangling": 1, "cyclic": 2}
    assert stats["edges_proposed"] == stats["edges_kept"] + stats["edges_dropped"] == 3


def test_edges_into_existing_history_count_as_kept():
    """The adjuster lets a new task depend on an already-persisted one by UUID."""
    existing = _task("done-work", status="done")
    tasks = {"new": _task("new")}
    stats = resolve_task_dependencies(
        tasks,
        {"new": [str(existing.id)]},
        existing_tasks_by_id={str(existing.id): existing},
        strict=False,
    )

    assert (stats["edges_kept"], stats["edges_dropped"]) == (1, 0)
    assert tasks["new"].depends_on == [existing]


@pytest.mark.parametrize(
    "edges",
    [
        {"a": [], "b": ["a"]},
        {"a": ["b"], "b": ["a"]},
        {"a": ["ghost", "ghost2"], "b": ["a"]},
        {"a": ["b"], "b": ["c"], "c": ["a"]},
    ],
)
def test_proposed_always_equals_kept_plus_dropped(edges):
    """The invariant the telemetry's rate arithmetic depends on."""
    tasks = {k: _task(k) for k in edges}
    stats = resolve_task_dependencies(tasks, edges, strict=False)

    assert stats["edges_proposed"] == stats["edges_kept"] + stats["edges_dropped"]
    assert stats["edges_dropped"] == sum(stats["dropped_by_reason"].values())


# ─── topological_levels ───────────────────────────────────────────────────────
def test_levels_group_work_that_can_start_together():
    # a → {b, c} → d  (a diamond)
    levels, cyclic = topological_levels({"a": set(), "b": {"a"}, "c": {"a"}, "d": {"b", "c"}})

    assert levels == [["a"], ["b", "c"], ["d"]]
    assert cyclic == set()


def test_levels_ignore_dependencies_pointing_outside_the_graph():
    """Otherwise an absent key would falsely mark its whole chain cyclic."""
    levels, cyclic = topological_levels({"a": {"not-in-graph"}, "b": {"a"}})

    assert levels == [["a"], ["b"]]
    assert cyclic == set()


def test_levels_report_unpeelable_keys_as_cyclic():
    levels, cyclic = topological_levels({"a": {"b"}, "b": {"a"}, "c": set()})

    assert levels == [["c"]]
    assert cyclic == {"a", "b"}


# ─── DAG shape ────────────────────────────────────────────────────────────────
def test_shape_of_a_diamond():
    a, b, c, d = (_task(k) for k in ("a", "b", "c", "d"))
    b.depends_on = [a]
    c.depends_on = [a]
    d.depends_on = [b, c]

    shape = compute_dag_shape([a, b, c, d])

    assert shape["taskCount"] == 4
    assert shape["edgeCount"] == 4
    assert shape["rootCount"] == 1           # only `a` can start immediately
    assert shape["criticalPathLength"] == 3  # a → (b|c) → d
    assert shape["maxParallelWidth"] == 2    # b and c
    assert shape["isolatedCount"] == 0
    assert shape["blockedCount"] == 3        # everything downstream of a todo `a`
    assert shape["cyclicCount"] == 0


def test_shape_of_a_fully_parallel_plan():
    """No edges at all: everything starts now, nothing is blocked, path is 1."""
    tasks = [_task(k) for k in ("a", "b", "c")]

    shape = compute_dag_shape(tasks)

    assert shape["rootCount"] == shape["maxParallelWidth"] == shape["isolatedCount"] == 3
    assert shape["criticalPathLength"] == 1
    assert (shape["edgeCount"], shape["blockedCount"]) == (0, 0)


def test_shape_of_a_fully_sequential_plan():
    a, b, c = (_task(k) for k in ("a", "b", "c"))
    b.depends_on = [a]
    c.depends_on = [b]

    shape = compute_dag_shape([a, b, c])

    assert shape["criticalPathLength"] == 3
    assert shape["maxParallelWidth"] == 1
    assert shape["rootCount"] == 1


def test_done_prerequisites_do_not_count_as_blocking():
    a = _task("a", status="done")
    b = _task("b")
    b.depends_on = [a]

    assert compute_dag_shape([a, b])["blockedCount"] == 0


def test_shape_of_an_empty_project_is_all_zeroes():
    assert compute_dag_shape([]) == {
        "taskCount": 0,
        "edgeCount": 0,
        "rootCount": 0,
        "isolatedCount": 0,
        "criticalPathLength": 0,
        "maxParallelWidth": 0,
        "blockedCount": 0,
        "cyclicCount": 0,
    }


def test_shape_ignores_edges_pointing_outside_the_task_set():
    outsider = _task("outsider")
    a = _task("a")
    a.depends_on = [outsider]

    shape = compute_dag_shape([a])

    assert shape["edgeCount"] == 0
    assert shape["rootCount"] == 1


# ─── generation-fidelity summary ──────────────────────────────────────────────
def test_summary_is_none_when_nothing_was_recorded():
    """Absent telemetry must not render as a clean 0.0 build — it's unknown."""
    assert summarize_dependency_resolution(None) is None
    assert summarize_dependency_resolution({}) is None
    assert summarize_dependency_resolution({"resolution": "not-a-dict"}) is None


def test_summary_derives_the_dropped_edge_rate():
    summary = summarize_dependency_resolution(
        {
            "resolution": {
                "edges_proposed": 8,
                "edges_kept": 6,
                "edges_dropped": 2,
                "dropped_by_reason": {"dangling": 1, "cyclic": 1},
            },
            "source": "adjust",
            "recorded_at": "2026-08-04T12:00:00",
        }
    )

    assert summary["droppedEdgeRate"] == 0.25
    assert summary["droppedByReason"] == {"dangling": 1, "cyclic": 1}
    assert summary["source"] == "adjust"
    assert summary["recordedAt"] == "2026-08-04T12:00:00"


def test_summary_rate_is_zero_when_no_edges_were_proposed():
    """A plan with no dependencies proposed nothing, so it dropped nothing."""
    summary = summarize_dependency_resolution(
        {"resolution": {"edges_proposed": 0, "edges_kept": 0, "edges_dropped": 0}}
    )

    assert summary["droppedEdgeRate"] == 0.0
    assert summary["droppedByReason"] == {}


# ─── GET /roadmap/quality ─────────────────────────────────────────────────────
async def _seed(*, plan_quality=None, chain=0, clerk_org_id=ORG):
    """Seed org → team → session → project, plus a `chain`-long dependency chain."""
    from src.database import get_db
    from src.models.milestone import Milestone
    from src.models.onboarding_session import OnboardingSession
    from src.models.organization import Organization
    from src.models.project import Project
    from src.models.task import task_dependencies
    from src.models.team import Team

    async for db in app.dependency_overrides[get_db]():
        org = Organization(
            id=uuid.uuid4(),
            clerk_org_id=clerk_org_id,
            name="Org",
            slug=clerk_org_id,
            use_managed_key=False,
        )
        db.add(org)
        await db.flush()
        team = Team(id=uuid.uuid4(), organization_id=org.id, name="Default")
        db.add(team)
        await db.flush()
        session = OnboardingSession(
            id=uuid.uuid4(), organization_id=org.id, status="in_progress", project_brief={}
        )
        db.add(session)
        await db.flush()
        project = Project(
            id=uuid.uuid4(),
            team_id=team.id,
            onboarding_session_id=session.id,
            name="P",
            plan_quality=plan_quality,
        )
        db.add(project)
        await db.flush()
        milestone = Milestone(id=uuid.uuid4(), project_id=project.id, title="M1", sort_order=0)
        db.add(milestone)
        await db.flush()

        previous = None
        for i in range(chain):
            t = Task(
                id=uuid.uuid4(), milestone_id=milestone.id, title=f"T{i}", status="todo", sort_order=i
            )
            db.add(t)
            await db.flush()
            if previous is not None:
                # Insert the edge directly rather than `t.depends_on.append(...)`:
                # appending to a persistent object's collection lazy-loads it
                # first, synchronously, which raises under asyncio. Same reason
                # as test_roadmap_service.py's edge setup.
                await db.execute(
                    task_dependencies.insert().values(task_id=t.id, depends_on_task_id=previous)
                )
            previous = t.id

        await db.commit()
        return project.id


@pytest.mark.asyncio
async def test_quality_endpoint_returns_stored_generation_and_live_shape(tmp_db):
    project_id = await _seed(
        plan_quality={
            "resolution": {
                "edges_proposed": 4,
                "edges_kept": 3,
                "edges_dropped": 1,
                "dropped_by_reason": {"dangling": 1},
            },
            "source": "generate",
            "recorded_at": "2026-08-04T12:00:00",
        },
        chain=3,
    )

    with _patch_clerk():
        async with _client() as client:
            resp = await client.get(f"/api/projects/{project_id}/roadmap/quality", headers=AUTH)

    assert resp.status_code == 200
    body = resp.json()
    # Generation fidelity comes from the stored column...
    assert body["generation"]["droppedEdgeRate"] == 0.25
    assert body["generation"]["source"] == "generate"
    # ...while shape is recomputed from the rows that exist right now.
    assert body["shape"]["taskCount"] == 3
    assert body["shape"]["criticalPathLength"] == 3
    assert body["shape"]["maxParallelWidth"] == 1
    assert body["shape"]["rootCount"] == 1


@pytest.mark.asyncio
async def test_quality_endpoint_reports_null_generation_without_telemetry(tmp_db):
    """A roadmap generated before this column existed has unknown fidelity."""
    project_id = await _seed(chain=2)

    with _patch_clerk():
        async with _client() as client:
            resp = await client.get(f"/api/projects/{project_id}/roadmap/quality", headers=AUTH)

    assert resp.status_code == 200
    assert resp.json()["generation"] is None
    assert resp.json()["shape"]["taskCount"] == 2


# ─── the wiring: building a DAG records telemetry ─────────────────────────────
@pytest.mark.asyncio
async def test_persisting_a_roadmap_records_plan_quality(tmp_db):
    """The point of the whole change — a generation path writes the column.

    Driven through `create_project_with_milestones` rather than POST /adjust or
    /regenerate: those need a live planner key (CI sets ANTHROPIC_API_KEY but
    not GROQ_API_KEY), and this is the shared helper every generation path
    funnels into anyway.
    """
    from src.database import get_db
    from src.models.onboarding_session import OnboardingSession
    from src.models.organization import Organization
    from src.models.team import Team
    from src.services.roadmap_shapes import create_project_with_milestones, validated_milestones

    milestones = validated_milestones(
        {
            "milestones": [
                {
                    "title": "M1",
                    "tasks": [
                        {"title": "Set up repo", "dayOffset": 0, "key": "setup"},
                        {"title": "Build API", "dayOffset": 1, "key": "api", "dependsOn": ["setup"]},
                        # Points at nothing — one dropped edge.
                        {"title": "Ship", "dayOffset": 2, "key": "ship", "dependsOn": ["ghost"]},
                    ],
                }
            ]
        }
    )

    async for db in app.dependency_overrides[get_db]():
        org = Organization(
            id=uuid.uuid4(), clerk_org_id="org_wiring", name="O", slug="org_wiring",
            use_managed_key=False,
        )
        db.add(org)
        await db.flush()
        team = Team(id=uuid.uuid4(), organization_id=org.id, name="T")
        db.add(team)
        await db.flush()
        session = OnboardingSession(
            id=uuid.uuid4(), organization_id=org.id, status="in_progress", project_brief={}
        )
        db.add(session)
        await db.flush()

        project = await create_project_with_milestones(
            session, team, "P", None, None, milestones, db, strict=False, source="import"
        )
        await db.commit()

        recorded = project.plan_quality

    assert recorded["source"] == "import"
    assert recorded["recorded_at"]
    assert recorded["resolution"] == {
        "edges_proposed": 2,
        "edges_kept": 1,
        "edges_dropped": 1,
        "dropped_by_reason": {"dangling": 1},
    }
    # And it reads back through the same summary the endpoint serves.
    assert summarize_dependency_resolution(recorded)["droppedEdgeRate"] == 0.5


@pytest.mark.asyncio
async def test_quality_endpoint_404s_for_another_orgs_project(tmp_db):
    """Telemetry must not leak across tenants — the other org is fully
    provisioned, so this is the ownership check failing, not a missing org
    (which `_get_org` would 409 before the project lookup ever runs)."""
    project_id = await _seed()
    await _seed(clerk_org_id="org_plan_quality_other")

    with _patch_clerk(org_id="org_plan_quality_other"):
        async with _client() as client:
            resp = await client.get(f"/api/projects/{project_id}/roadmap/quality", headers=AUTH)

    assert resp.status_code == 404
