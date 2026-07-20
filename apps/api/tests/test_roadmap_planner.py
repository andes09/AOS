"""
Planner attribution + time-blocking endpoints (migration 0031).

Covers the lane sidebar (GET /members), assignee/time/duration on tasks, task
creation, and bulk reschedule. The cross-tenant assignment tests are the
important ones — without `_owned_developer`, a guessed UUID from another org
would succeed and leak that person into this org's planner.
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
    """Seed an org → team → (developers, onboarding session, project/milestone)."""
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
        if with_project:
            session = OnboardingSession(
                id=uuid.uuid4(), organization_id=org.id, status="in_progress"
            )
            db.add(session)
            await db.flush()
            project = Project(
                id=uuid.uuid4(),
                team_id=team.id,
                onboarding_session_id=session.id,
                name="Test Project",
            )
            db.add(project)
            await db.flush()
            milestone = Milestone(
                id=uuid.uuid4(), project_id=project.id, title="M1", sort_order=0
            )
            db.add(milestone)
            milestone_id = milestone.id

        await db.commit()
        return {"org_id": org.id, "team_id": team.id, "dev_ids": dev_ids, "milestone_id": milestone_id}


async def _create_task(client, **body):
    payload = {"title": "Task"} | body
    return await client.post("/api/roadmap/tasks", json=payload, headers=AUTH)


# ─── GET /members ───────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_members_returns_lanes_with_distinct_colors(tmp_db):
    await _seed(developers=["Ada Lovelace", "Grace Hopper"])
    with _patch_clerk():
        async with _client() as client:
            resp = await client.get("/api/roadmap/members", headers=AUTH)

    assert resp.status_code == 200
    members = resp.json()["members"]
    assert [m["name"] for m in members] == ["Ada Lovelace", "Grace Hopper"]
    assert [m["colorIndex"] for m in members] == [0, 1]
    assert [m["initials"] for m in members] == ["AL", "GH"]
    assert all(m["scheduledCount"] == 0 for m in members)


@pytest.mark.asyncio
async def test_members_excludes_other_orgs(tmp_db):
    await _seed(developers=["Ada Lovelace"])
    await _seed(OTHER_ORG, developers=["Someone Else"], with_project=False)

    with _patch_clerk():
        async with _client() as client:
            resp = await client.get("/api/roadmap/members", headers=AUTH)

    names = [m["name"] for m in resp.json()["members"]]
    assert names == ["Ada Lovelace"]


@pytest.mark.asyncio
async def test_members_scheduled_count_ignores_done_and_unscheduled(tmp_db):
    seeded = await _seed(developers=["Ada Lovelace"])
    dev_id = str(seeded["dev_ids"][0])

    with _patch_clerk():
        async with _client() as client:
            # counted: scheduled + not done
            await _create_task(client, assigneeId=dev_id, scheduledDate="2026-02-15")
            # not counted: no date
            await _create_task(client, assigneeId=dev_id)
            # not counted: done
            r = await _create_task(client, assigneeId=dev_id, scheduledDate="2026-02-16")
            await client.patch(
                f"/api/roadmap/tasks/{r.json()['id']}", json={"status": "done"}, headers=AUTH
            )

            resp = await client.get("/api/roadmap/members", headers=AUTH)

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
    await _seed(with_project=False)
    with _patch_clerk():
        async with _client() as client:
            resp = await _create_task(client)
    assert resp.status_code == 409
    assert resp.json()["detail"] == "no_milestones"


@pytest.mark.asyncio
async def test_create_task_rejects_cross_tenant_assignee(tmp_db):
    await _seed()
    other = await _seed(OTHER_ORG, developers=["Someone Else"], with_project=False)
    foreign_dev = str(other["dev_ids"][0])

    with _patch_clerk():
        async with _client() as client:
            resp = await _create_task(client, assigneeId=foreign_dev)

    assert resp.status_code == 404
    assert resp.json()["detail"] == "developer_not_found"


@pytest.mark.asyncio
async def test_create_task_rejects_out_of_range_duration(tmp_db):
    await _seed()
    with _patch_clerk():
        async with _client() as client:
            too_short = await _create_task(client, durationMinutes=1)
            too_long = await _create_task(client, durationMinutes=5000)
    assert too_short.status_code == 422
    assert too_long.status_code == 422


# ─── PATCH /tasks/{id} ──────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_patch_assigns_and_unassigns(tmp_db):
    seeded = await _seed(developers=["Ada Lovelace"])
    dev_id = str(seeded["dev_ids"][0])

    with _patch_clerk():
        async with _client() as client:
            task_id = (await _create_task(client)).json()["id"]

            assigned = await client.patch(
                f"/api/roadmap/tasks/{task_id}", json={"assigneeId": dev_id}, headers=AUTH
            )
            # Explicit null clears — this is the model_fields_set contract.
            cleared = await client.patch(
                f"/api/roadmap/tasks/{task_id}", json={"assigneeId": None}, headers=AUTH
            )

    assert assigned.json()["assigneeId"] == dev_id
    assert cleared.json()["assigneeId"] is None


@pytest.mark.asyncio
async def test_patch_omitted_field_leaves_value_untouched(tmp_db):
    seeded = await _seed(developers=["Ada Lovelace"])
    dev_id = str(seeded["dev_ids"][0])

    with _patch_clerk():
        async with _client() as client:
            task_id = (
                await _create_task(client, assigneeId=dev_id, scheduledTime="09:30")
            ).json()["id"]
            # Touch only the title; assignee and time must survive.
            resp = await client.patch(
                f"/api/roadmap/tasks/{task_id}", json={"title": "Renamed"}, headers=AUTH
            )

    body = resp.json()
    assert body["title"] == "Renamed"
    assert body["assigneeId"] == dev_id
    assert body["scheduledTime"] == "09:30"


@pytest.mark.asyncio
async def test_patch_rejects_cross_tenant_assignee(tmp_db):
    """The security-critical case: a guessed UUID from another org must 404."""
    await _seed()
    other = await _seed(OTHER_ORG, developers=["Someone Else"], with_project=False)
    foreign_dev = str(other["dev_ids"][0])

    with _patch_clerk():
        async with _client() as client:
            task_id = (await _create_task(client)).json()["id"]
            resp = await client.patch(
                f"/api/roadmap/tasks/{task_id}",
                json={"assigneeId": foreign_dev},
                headers=AUTH,
            )
            after = await client.get("/api/roadmap", headers=AUTH)

    assert resp.status_code == 404
    assert resp.json()["detail"] == "developer_not_found"
    # And the task must be genuinely unchanged, not merely reported as failed.
    tasks = after.json()["milestones"][0]["tasks"]
    assert tasks[0]["assigneeId"] is None


@pytest.mark.asyncio
async def test_patch_clears_time_for_all_day(tmp_db):
    await _seed()
    with _patch_clerk():
        async with _client() as client:
            task_id = (await _create_task(client, scheduledTime="09:30")).json()["id"]
            resp = await client.patch(
                f"/api/roadmap/tasks/{task_id}", json={"scheduledTime": None}, headers=AUTH
            )
    assert resp.json()["scheduledTime"] is None


# ─── POST /tasks/reschedule ─────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_reschedule_moves_several_tasks(tmp_db):
    seeded = await _seed(developers=["Ada Lovelace"])
    dev_id = str(seeded["dev_ids"][0])

    with _patch_clerk():
        async with _client() as client:
            a = (await _create_task(client, title="A")).json()["id"]
            b = (await _create_task(client, title="B")).json()["id"]

            resp = await client.post(
                "/api/roadmap/tasks/reschedule",
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
    await _seed()
    with _patch_clerk():
        async with _client() as client:
            good = (await _create_task(client, title="Good")).json()["id"]

            resp = await client.post(
                "/api/roadmap/tasks/reschedule",
                json={
                    "updates": [
                        {"id": good, "scheduledDate": "2026-03-02"},
                        {"id": str(uuid.uuid4()), "scheduledDate": "2026-03-02"},
                    ]
                },
                headers=AUTH,
            )
            after = await client.get("/api/roadmap", headers=AUTH)

    assert resp.status_code == 404
    tasks = after.json()["milestones"][0]["tasks"]
    assert tasks[0]["scheduledDate"] is None  # the valid one was NOT applied


@pytest.mark.asyncio
async def test_reschedule_rejects_cross_tenant_task(tmp_db):
    await _seed()
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
                "/api/roadmap/tasks/reschedule",
                json={"updates": [{"id": foreign_id, "scheduledDate": "2026-03-02"}]},
                headers=AUTH,
            )

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_reschedule_rejects_empty_batch(tmp_db):
    await _seed()
    with _patch_clerk():
        async with _client() as client:
            resp = await client.post(
                "/api/roadmap/tasks/reschedule", json={"updates": []}, headers=AUTH
            )
    assert resp.status_code == 422
