"""
Planner attribution + time-blocking endpoints (migration 0031).

Covers the lane sidebar (GET /members), assignee/time/duration on tasks, task
creation, and bulk reschedule. The cross-tenant assignment tests are the
important ones — without `_owned_developer`, a guessed UUID from another org
would succeed and leak that person into this org's planner.

Routes are project-scoped (see docs/plans/2026-07-20-project-hub.md); every
call goes through /api/projects/{project_id}/roadmap/... now.
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient, ASGITransport

from src.main import app

ORG = "org_planner_test"
OTHER_ORG = "org_planner_other"
USER = "user_planner"

AUTH = {"Authorization": "Bearer tok"}


def _patch_clerk(user_id=USER, org_id=ORG):
    payload = {"sub": user_id, "org_id": org_id}
    state = type("S", (), {"is_signed_in": True, "payload": payload})()
    return patch("src.auth._clerk.authenticate_request_async", new=AsyncMock(return_value=state))


def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _seed(clerk_org_id=ORG, *, developers=(), with_project=True):
    """Seed an org → team → (developers, onboarding session, project/milestone).

    The session carries a minimal `project_brief` so brief-gated endpoints
    (generate/regenerate/adjust) don't 409.
    """
    from src.database import get_db
    from src.models.developer import Developer
    from src.models.milestone import Milestone
    from src.models.onboarding_session import OnboardingSession
    from src.models.organization import Organization
    from src.models.project import Project
    from src.models.team import Team

    async for db in app.dependency_overrides[get_db]():
        org = Organization(
            id=uuid.uuid4(),
            clerk_org_id=clerk_org_id,
            name=f"Org {clerk_org_id}",
            slug=clerk_org_id,
            use_managed_key=False,
        )
        db.add(org)
        await db.flush()

        team = Team(id=uuid.uuid4(), organization_id=org.id, name="Default")
        db.add(team)
        await db.flush()

        dev_ids = []
        for i, name in enumerate(developers):
            dev = Developer(
                id=uuid.uuid4(), team_id=team.id, name=name, color_index=i, is_active=True
            )
            db.add(dev)
            dev_ids.append(dev.id)

        milestone_id = None
        session_id = None
        project_id = None
        if with_project:
            session = OnboardingSession(
                id=uuid.uuid4(),
                organization_id=org.id,
                status="in_progress",
                project_brief={"projectName": "Test Project"},
            )
            db.add(session)
            await db.flush()
            session_id = session.id
            project = Project(
                id=uuid.uuid4(),
                team_id=team.id,
                onboarding_session_id=session.id,
                name="Test Project",
            )
            db.add(project)
            await db.flush()
            project_id = project.id
            milestone = Milestone(
                id=uuid.uuid4(), project_id=project.id, title="M1", sort_order=0
            )
            db.add(milestone)
            milestone_id = milestone.id

        await db.commit()
        return {
            "org_id": org.id,
            "team_id": team.id,
            "dev_ids": dev_ids,
            "project_id": project_id,
            "milestone_id": milestone_id,
            "session_id": session_id,
        }


def _url(project_id, suffix=""):
    return f"/api/projects/{project_id}/roadmap{suffix}"


async def _create_task(client, project_id, **body):
    payload = {"title": "Task"} | body
    return await client.post(_url(project_id, "/tasks"), json=payload, headers=AUTH)


# ─── GET /members ───────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_members_returns_lanes_with_distinct_colors(tmp_db):
    seeded = await _seed(developers=["Ada Lovelace", "Grace Hopper"])
    with _patch_clerk():
        async with _client() as client:
            resp = await client.get(_url(seeded["project_id"], "/members"), headers=AUTH)

    assert resp.status_code == 200
    members = resp.json()["members"]
    assert [m["name"] for m in members] == ["Ada Lovelace", "Grace Hopper"]
    assert [m["colorIndex"] for m in members] == [0, 1]
    assert [m["initials"] for m in members] == ["AL", "GH"]
    assert all(m["scheduledCount"] == 0 for m in members)


@pytest.mark.asyncio
async def test_members_excludes_other_orgs(tmp_db):
    seeded = await _seed(developers=["Ada Lovelace"])
    await _seed(OTHER_ORG, developers=["Someone Else"], with_project=False)

    with _patch_clerk():
        async with _client() as client:
            resp = await client.get(_url(seeded["project_id"], "/members"), headers=AUTH)

    names = [m["name"] for m in resp.json()["members"]]
    assert names == ["Ada Lovelace"]


@pytest.mark.asyncio
async def test_members_scheduled_count_ignores_done_and_unscheduled(tmp_db):
    seeded = await _seed(developers=["Ada Lovelace"])
    dev_id = str(seeded["dev_ids"][0])
    project_id = seeded["project_id"]

    with _patch_clerk():
        async with _client() as client:
            # counted: scheduled + not done
            await _create_task(client, project_id, assigneeId=dev_id, scheduledDate="2026-02-15")
            # not counted: no date
            await _create_task(client, project_id, assigneeId=dev_id)
            # not counted: done
            r = await _create_task(client, project_id, assigneeId=dev_id, scheduledDate="2026-02-16")
            await client.patch(
                _url(project_id, f"/tasks/{r.json()['id']}"), json={"status": "done"}, headers=AUTH
            )

            resp = await client.get(_url(project_id, "/members"), headers=AUTH)

    assert resp.json()["members"][0]["scheduledCount"] == 1


# ─── POST /tasks ────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_create_task_with_time_and_duration(tmp_db):
    seeded = await _seed(developers=["Ada Lovelace"])
    dev_id = str(seeded["dev_ids"][0])

    with _patch_clerk():
        async with _client() as client:
            resp = await _create_task(
                client,
                seeded["project_id"],
                title="Standup",
                assigneeId=dev_id,
                scheduledDate="2026-02-15",
                scheduledTime="09:30",
                durationMinutes=45,
            )

    assert resp.status_code == 201
    body = resp.json()
    assert body["title"] == "Standup"
    assert body["assigneeId"] == dev_id
    assert body["scheduledDate"] == "2026-02-15"
    # "%H:%M", not isoformat — no stray seconds for the frontend to strip.
    assert body["scheduledTime"] == "09:30"
    assert body["durationMinutes"] == 45
    assert body["status"] == "todo"


@pytest.mark.asyncio
async def test_create_task_409_without_a_roadmap(tmp_db):
    seeded = await _seed(with_project=True)
    # Milestone exists but has no tasks yet is fine — what we need is a project
    # with NO milestones at all, which _seed doesn't produce; build it directly.
    from src.database import get_db
    from src.models.milestone import Milestone

    async for db in app.dependency_overrides[get_db]():
        from sqlalchemy import delete
        await db.execute(delete(Milestone).where(Milestone.id == seeded["milestone_id"]))
        await db.commit()
        break

    with _patch_clerk():
        async with _client() as client:
            resp = await _create_task(client, seeded["project_id"])
    assert resp.status_code == 409
    assert resp.json()["detail"] == "no_milestones"


@pytest.mark.asyncio
async def test_create_task_rejects_cross_tenant_assignee(tmp_db):
    seeded = await _seed()
    other = await _seed(OTHER_ORG, developers=["Someone Else"], with_project=False)
    foreign_dev = str(other["dev_ids"][0])

    with _patch_clerk():
        async with _client() as client:
            resp = await _create_task(client, seeded["project_id"], assigneeId=foreign_dev)

    assert resp.status_code == 404
    assert resp.json()["detail"] == "developer_not_found"


@pytest.mark.asyncio
async def test_create_task_rejects_out_of_range_duration(tmp_db):
    seeded = await _seed()
    with _patch_clerk():
        async with _client() as client:
            too_short = await _create_task(client, seeded["project_id"], durationMinutes=1)
            too_long = await _create_task(client, seeded["project_id"], durationMinutes=5000)
    assert too_short.status_code == 422
    assert too_long.status_code == 422


# ─── PATCH /tasks/{id} ──────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_patch_assigns_and_unassigns(tmp_db):
    seeded = await _seed(developers=["Ada Lovelace"])
    dev_id = str(seeded["dev_ids"][0])
    project_id = seeded["project_id"]

    with _patch_clerk():
        async with _client() as client:
            task_id = (await _create_task(client, project_id)).json()["id"]

            assigned = await client.patch(
                _url(project_id, f"/tasks/{task_id}"), json={"assigneeId": dev_id}, headers=AUTH
            )
            # Explicit null clears — this is the model_fields_set contract.
            cleared = await client.patch(
                _url(project_id, f"/tasks/{task_id}"), json={"assigneeId": None}, headers=AUTH
            )

    assert assigned.json()["assigneeId"] == dev_id
    assert cleared.json()["assigneeId"] is None


@pytest.mark.asyncio
async def test_patch_omitted_field_leaves_value_untouched(tmp_db):
    seeded = await _seed(developers=["Ada Lovelace"])
    dev_id = str(seeded["dev_ids"][0])
    project_id = seeded["project_id"]

    with _patch_clerk():
        async with _client() as client:
            task_id = (
                await _create_task(client, project_id, assigneeId=dev_id, scheduledTime="09:30")
            ).json()["id"]
            # Touch only the title; assignee and time must survive.
            resp = await client.patch(
                _url(project_id, f"/tasks/{task_id}"), json={"title": "Renamed"}, headers=AUTH
            )

    body = resp.json()
    assert body["title"] == "Renamed"
    assert body["assigneeId"] == dev_id
    assert body["scheduledTime"] == "09:30"


@pytest.mark.asyncio
async def test_patch_rejects_cross_tenant_assignee(tmp_db):
    """The security-critical case: a guessed UUID from another org must 404."""
    seeded = await _seed()
    project_id = seeded["project_id"]
    other = await _seed(OTHER_ORG, developers=["Someone Else"], with_project=False)
    foreign_dev = str(other["dev_ids"][0])

    with _patch_clerk():
        async with _client() as client:
            task_id = (await _create_task(client, project_id)).json()["id"]
            resp = await client.patch(
                _url(project_id, f"/tasks/{task_id}"),
                json={"assigneeId": foreign_dev},
                headers=AUTH,
            )
            after = await client.get(_url(project_id), headers=AUTH)

    assert resp.status_code == 404
    assert resp.json()["detail"] == "developer_not_found"
    # And the task must be genuinely unchanged, not merely reported as failed.
    tasks = after.json()["milestones"][0]["tasks"]
    assert tasks[0]["assigneeId"] is None


@pytest.mark.asyncio
async def test_patch_clears_time_for_all_day(tmp_db):
    seeded = await _seed()
    project_id = seeded["project_id"]
    with _patch_clerk():
        async with _client() as client:
            task_id = (await _create_task(client, project_id, scheduledTime="09:30")).json()["id"]
            resp = await client.patch(
                _url(project_id, f"/tasks/{task_id}"), json={"scheduledTime": None}, headers=AUTH
            )
    assert resp.json()["scheduledTime"] is None


# ─── POST /tasks/reschedule ─────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_reschedule_moves_several_tasks(tmp_db):
    seeded = await _seed(developers=["Ada Lovelace"])
    dev_id = str(seeded["dev_ids"][0])
    project_id = seeded["project_id"]

    with _patch_clerk():
        async with _client() as client:
            a = (await _create_task(client, project_id, title="A")).json()["id"]
            b = (await _create_task(client, project_id, title="B")).json()["id"]

            resp = await client.post(
                _url(project_id, "/tasks/reschedule"),
                json={
                    "updates": [
                        {"id": a, "scheduledDate": "2026-03-02", "scheduledTime": "10:00"},
                        {"id": b, "scheduledDate": "2026-03-03", "assigneeId": dev_id},
                    ]
                },
                headers=AUTH,
            )

    assert resp.status_code == 200
    tasks = resp.json()["tasks"]
    assert tasks[0]["scheduledDate"] == "2026-03-02"
    assert tasks[0]["scheduledTime"] == "10:00"
    assert tasks[1]["scheduledDate"] == "2026-03-03"
    assert tasks[1]["assigneeId"] == dev_id


@pytest.mark.asyncio
async def test_reschedule_is_all_or_nothing(tmp_db):
    """One unknown id must abort the batch — a partial apply is unrecoverable UX."""
    seeded = await _seed()
    project_id = seeded["project_id"]
    with _patch_clerk():
        async with _client() as client:
            good = (await _create_task(client, project_id, title="Good")).json()["id"]

            resp = await client.post(
                _url(project_id, "/tasks/reschedule"),
                json={
                    "updates": [
                        {"id": good, "scheduledDate": "2026-03-02"},
                        {"id": str(uuid.uuid4()), "scheduledDate": "2026-03-02"},
                    ]
                },
                headers=AUTH,
            )
            after = await client.get(_url(project_id), headers=AUTH)

    assert resp.status_code == 404
    tasks = after.json()["milestones"][0]["tasks"]
    assert tasks[0]["scheduledDate"] is None  # the valid one was NOT applied


@pytest.mark.asyncio
async def test_reschedule_rejects_cross_tenant_task(tmp_db):
    own = await _seed()
    other = await _seed(OTHER_ORG, with_project=True)

    from src.database import get_db
    from src.models.task import Task

    async for db in app.dependency_overrides[get_db]():
        foreign = Task(
            id=uuid.uuid4(),
            milestone_id=other["milestone_id"],
            title="Foreign",
            status="todo",
            sort_order=0,
        )
        db.add(foreign)
        await db.commit()
        foreign_id = str(foreign.id)
        break

    with _patch_clerk():
        async with _client() as client:
            resp = await client.post(
                _url(own["project_id"], "/tasks/reschedule"),
                json={"updates": [{"id": foreign_id, "scheduledDate": "2026-03-02"}]},
                headers=AUTH,
            )

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_reschedule_rejects_empty_batch(tmp_db):
    seeded = await _seed()
    with _patch_clerk():
        async with _client() as client:
            resp = await client.post(
                _url(seeded["project_id"], "/tasks/reschedule"), json={"updates": []}, headers=AUTH
            )
    assert resp.status_code == 422


# ─── per-task feedback (migration 0033) ─────────────────────────────────────────
@pytest.mark.asyncio
async def test_feedback_persists_and_round_trips(tmp_db):
    seeded = await _seed()
    project_id = seeded["project_id"]
    with _patch_clerk():
        async with _client() as client:
            task_id = (await _create_task(client, project_id, title="Ship auth")).json()["id"]

            patched = await client.patch(
                _url(project_id, f"/tasks/{task_id}"),
                json={"feedback": "RLS policies were fiddly, took 2x longer"},
                headers=AUTH,
            )
            roadmap = await client.get(_url(project_id), headers=AUTH)

    assert patched.json()["feedback"] == "RLS policies were fiddly, took 2x longer"
    # Survives a reload (it's really on the row, not just echoed back).
    tasks = roadmap.json()["milestones"][0]["tasks"]
    assert tasks[0]["feedback"] == "RLS policies were fiddly, took 2x longer"


@pytest.mark.asyncio
async def test_feedback_can_be_cleared(tmp_db):
    seeded = await _seed()
    project_id = seeded["project_id"]
    with _patch_clerk():
        async with _client() as client:
            task_id = (await _create_task(client, project_id)).json()["id"]
            await client.patch(
                _url(project_id, f"/tasks/{task_id}"), json={"feedback": "note"}, headers=AUTH
            )
            cleared = await client.patch(
                _url(project_id, f"/tasks/{task_id}"), json={"feedback": None}, headers=AUTH
            )
    assert cleared.json()["feedback"] is None


# ─── POST /adjust (Groq feedback loop) ──────────────────────────────────────────
async def _add_task_row(milestone_id, *, title, status, sort_order):
    """Insert a task directly so we can control its status for adjust tests."""
    from src.database import get_db
    from src.models.task import Task

    async for db in app.dependency_overrides[get_db]():
        t = Task(id=uuid.uuid4(), milestone_id=milestone_id, title=title, status=status, sort_order=sort_order)
        db.add(t)
        await db.commit()
        return t.id


# What the mocked Groq call returns: one existing milestone ("M1") replanned.
_ADJUST_OUTPUT = (
    {
        "milestones": [
            {
                "title": "M1",
                "tasks": [
                    {
                        "title": "Rework auth after feedback",
                        "description": "Revised task",
                        "dayOffset": 1,
                        "startTime": "10:00",
                        "durationMinutes": 60,
                    }
                ],
            }
        ]
    },
    None,  # usage
)


@pytest.mark.asyncio
async def test_adjust_preserves_done_and_replans_todo(tmp_db):
    seeded = await _seed()
    mid = seeded["milestone_id"]
    await _add_task_row(mid, title="Done work", status="done", sort_order=0)
    await _add_task_row(mid, title="Stale todo", status="todo", sort_order=1)

    with _patch_clerk(), \
        patch("src.services.roadmap_adjuster._call_adjuster", new=AsyncMock(return_value=_ADJUST_OUTPUT)), \
        patch("src.services.roadmap_adjuster.record_generation_cost"):
        async with _client() as client:
            resp = await client.post(_url(seeded["project_id"], "/adjust"), json={}, headers=AUTH)

    assert resp.status_code == 200
    tasks = resp.json()["milestones"][0]["tasks"]
    titles = [t["title"] for t in tasks]
    # Done task preserved; stale todo gone; new todo added with a time.
    assert "Done work" in titles
    assert "Stale todo" not in titles
    assert "Rework auth after feedback" in titles
    new_task = next(t for t in tasks if t["title"] == "Rework auth after feedback")
    assert new_task["scheduledTime"] == "10:00"
    assert new_task["durationMinutes"] == 60


@pytest.mark.asyncio
async def test_adjust_empty_output_is_a_noop(tmp_db):
    """A malformed/empty model result must not wipe the existing todo tasks."""
    seeded = await _seed()
    await _add_task_row(seeded["milestone_id"], title="Keep me", status="todo", sort_order=0)

    with _patch_clerk(), \
        patch("src.services.roadmap_adjuster._call_adjuster", new=AsyncMock(return_value=({"milestones": []}, None))), \
        patch("src.services.roadmap_adjuster.record_generation_cost"):
        async with _client() as client:
            resp = await client.post(_url(seeded["project_id"], "/adjust"), json={}, headers=AUTH)

    assert resp.status_code == 200
    titles = [t["title"] for t in resp.json()["milestones"][0]["tasks"]]
    assert titles == ["Keep me"]


@pytest.mark.asyncio
async def test_adjust_409_without_a_roadmap(tmp_db):
    seeded = await _seed(with_project=True)
    from src.database import get_db
    from src.models.milestone import Milestone
    from sqlalchemy import delete

    async for db in app.dependency_overrides[get_db]():
        await db.execute(delete(Milestone).where(Milestone.id == seeded["milestone_id"]))
        await db.commit()
        break

    with _patch_clerk():
        async with _client() as client:
            resp = await client.post(_url(seeded["project_id"], "/adjust"), json={}, headers=AUTH)
    assert resp.status_code == 409
    assert resp.json()["detail"] == "no_roadmap"
