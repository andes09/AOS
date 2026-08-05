"""
Tests for drift detection (services/roadmap_drift.py) and its endpoint.

The negative cases carry most of the weight. This signal drives a banner on
the planner's landing surface, so a false positive interrupts someone who is
doing fine — and the two most likely false positives (a roadmap with nothing
scheduled, a repo connected five minutes ago) are both here by name.
"""

import uuid
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.main import app
from src.database import get_db
from src.models.organization import Organization
from src.models.team import Team
from src.models.onboarding_session import OnboardingSession
from src.models.project import Project
from src.models.milestone import Milestone
from src.models.task import Task, TaskStatus
from src.models.github_connection import GithubConnection
from src.models.github_activity_event import GithubActivityEvent, MatchMethod
from src.services import roadmap_drift
from src.services.roadmap_drift import compute_drift

TODAY = date(2026, 8, 5)
NOW = datetime(2026, 8, 5, 12, 0, 0)


async def _load_project(project_id) -> Project:
    """Re-fetch with milestones+tasks eager-loaded, the way
    project_common._owned_project hands it to the service."""
    async for db in app.dependency_overrides[get_db]():
        return await db.scalar(
            select(Project)
            .where(Project.id == project_id)
            .options(selectinload(Project.milestones).selectinload(Milestone.tasks))
        )


async def _seed(
    *,
    repo="octo/app",
    connection_age_days=90,
    with_connection=True,
):
    ids = {k: uuid.uuid4() for k in ("org", "team", "session", "project")}
    async for db in app.dependency_overrides[get_db]():
        db.add(Organization(
            id=ids["org"], clerk_org_id=f"org_{ids['org'].hex[:8]}", name="O",
            slug=ids["org"].hex[:8], use_managed_key=False,
        ))
        db.add(Team(id=ids["team"], organization_id=ids["org"], name="T"))
        db.add(OnboardingSession(id=ids["session"], organization_id=ids["org"], status="completed"))
        db.add(Project(
            id=ids["project"], team_id=ids["team"], onboarding_session_id=ids["session"],
            name="P", purpose="hobby", github_repo_full_name=repo,
        ))
        if with_connection:
            db.add(GithubConnection(
                id=uuid.uuid4(), organization_id=ids["org"], installation_id="1",
                github_user_id="1", github_login="octo", encrypted_access_token="e",
                is_active=True, created_at=NOW - timedelta(days=connection_age_days),
            ))
        await db.commit()
    return ids


async def _add_milestone(ids, title, tasks):
    """`tasks` is a list of dicts: {title, status?, scheduled_date?, completed_at?}."""
    milestone_id = uuid.uuid4()
    async for db in app.dependency_overrides[get_db]():
        db.add(Milestone(id=milestone_id, project_id=ids["project"], title=title, sort_order=0))
        await db.flush()
        for i, spec in enumerate(tasks):
            db.add(Task(
                id=spec.get("id") or uuid.uuid4(),
                milestone_id=milestone_id,
                title=spec["title"],
                status=spec.get("status", TaskStatus.TODO.value),
                scheduled_date=spec.get("scheduled_date"),
                completed_at=spec.get("completed_at"),
                sort_order=i,
            ))
        await db.commit()
    return milestone_id


async def _add_events(ids, n, *, matched_task_id=None, occurred_at=None, branch=None):
    async for db in app.dependency_overrides[get_db]():
        for i in range(n):
            db.add(GithubActivityEvent(
                id=uuid.uuid4(), organization_id=ids["org"], repo_full_name="octo/app",
                event_type="push", external_id=f"{uuid.uuid4().hex}",
                title_or_message=f"commit {i}", branch=branch,
                matched_task_id=matched_task_id,
                match_method=MatchMethod.HEURISTIC if matched_task_id else MatchMethod.UNMATCHED,
                occurred_at=occurred_at or (NOW - timedelta(days=1)),
            ))
        await db.commit()


async def _drift(ids):
    project = await _load_project(ids["project"])
    async for db in app.dependency_overrides[get_db]():
        return await compute_drift(ids["org"], project, db, today=TODAY)


def _kinds(result) -> set[str]:
    return {s["kind"] for s in result["signals"]}


# ─── healthy project ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_healthy_project_has_no_drift(tmp_db):
    ids = await _seed()
    task_id = uuid.uuid4()
    await _add_milestone(ids, "M1", [
        {"id": task_id, "title": "Build the thing", "scheduled_date": TODAY + timedelta(days=2)},
    ])
    await _add_events(ids, 6, matched_task_id=task_id)

    result = await _drift(ids)
    assert result["hasDrift"] is False
    assert result["signals"] == []


# ─── stalled milestones ──────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_overdue_milestone_with_no_activity_is_stalled(tmp_db):
    ids = await _seed()
    milestone_id = await _add_milestone(ids, "Auth work", [
        {"title": "Add login", "scheduled_date": TODAY - timedelta(days=10)},
    ])

    result = await _drift(ids)
    assert "stalled_milestone" in _kinds(result)
    assert result["hasDrift"] is True
    signal = next(s for s in result["signals"] if s["kind"] == "stalled_milestone")
    assert str(milestone_id) in signal["milestoneIds"]
    assert "Auth work" in signal["detail"]


@pytest.mark.asyncio
async def test_overdue_milestone_with_recent_commits_is_not_stalled(tmp_db):
    """Overdue alone is just an optimistic estimate. Overdue *and silent* is
    the thing worth interrupting someone about."""
    ids = await _seed()
    task_id = uuid.uuid4()
    await _add_milestone(ids, "Auth work", [
        {"id": task_id, "title": "Add login", "scheduled_date": TODAY - timedelta(days=10)},
    ])
    await _add_events(ids, 3, matched_task_id=task_id)

    assert "stalled_milestone" not in _kinds(await _drift(ids))


@pytest.mark.asyncio
async def test_unscheduled_milestone_never_stalls(tmp_db):
    """The most important false positive to avoid: Milestone has no dates of
    its own, so a roadmap where nobody scheduled anything must read as fine,
    not as permanently overdue.

    Seeded without a GitHub connection so the silent-repo signal (which would
    legitimately fire here) doesn't mask what's under test.
    """
    ids = await _seed(with_connection=False)
    await _add_milestone(ids, "Someday work", [
        {"title": "Add login", "scheduled_date": None},
        {"title": "Add logout", "scheduled_date": None},
    ])

    result = await _drift(ids)
    assert "stalled_milestone" not in _kinds(result)
    assert result["hasDrift"] is False


@pytest.mark.asyncio
async def test_fully_done_milestone_never_stalls(tmp_db):
    ids = await _seed()
    await _add_milestone(ids, "Finished work", [
        {
            "title": "Add login",
            "status": TaskStatus.DONE.value,
            "scheduled_date": TODAY - timedelta(days=30),
            "completed_at": NOW - timedelta(days=29),
        },
    ])
    assert "stalled_milestone" not in _kinds(await _drift(ids))


@pytest.mark.asyncio
async def test_barely_overdue_milestone_is_within_the_grace_period(tmp_db):
    ids = await _seed()
    await _add_milestone(ids, "Auth work", [
        {"title": "Add login", "scheduled_date": TODAY - timedelta(days=1)},
    ])
    assert "stalled_milestone" not in _kinds(await _drift(ids))


# ─── unplanned work ──────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_mostly_unmatched_activity_reports_unplanned_work(tmp_db):
    ids = await _seed()
    await _add_milestone(ids, "M1", [
        {"title": "Build the thing", "scheduled_date": TODAY + timedelta(days=5)},
    ])
    await _add_events(ids, 8, branch="feat/something-else")

    result = await _drift(ids)
    assert "unplanned_work" in _kinds(result)
    signal = next(s for s in result["signals"] if s["kind"] == "unplanned_work")
    assert "100%" in signal["headline"]
    assert signal["evidence"]  # concrete branch names, not just a number


@pytest.mark.asyncio
async def test_a_couple_of_stray_commits_are_not_a_trend(tmp_db):
    ids = await _seed()
    await _add_milestone(ids, "M1", [
        {"title": "Build the thing", "scheduled_date": TODAY + timedelta(days=5)},
    ])
    await _add_events(ids, 2)
    assert "unplanned_work" not in _kinds(await _drift(ids))


@pytest.mark.asyncio
async def test_mostly_matched_activity_is_not_unplanned(tmp_db):
    ids = await _seed()
    task_id = uuid.uuid4()
    await _add_milestone(ids, "M1", [
        {"id": task_id, "title": "Build the thing", "scheduled_date": TODAY + timedelta(days=5)},
    ])
    await _add_events(ids, 8, matched_task_id=task_id)
    await _add_events(ids, 1)
    assert "unplanned_work" not in _kinds(await _drift(ids))


@pytest.mark.asyncio
async def test_events_outside_the_window_are_ignored(tmp_db):
    ids = await _seed()
    await _add_milestone(ids, "M1", [
        {"title": "Build the thing", "scheduled_date": TODAY + timedelta(days=5)},
    ])
    await _add_events(ids, 8, occurred_at=NOW - timedelta(days=60))
    assert "unplanned_work" not in _kinds(await _drift(ids))


# ─── silent repo ─────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_linked_repo_with_no_activity_and_open_work_is_silent(tmp_db):
    ids = await _seed()
    await _add_milestone(ids, "M1", [{"title": "Build the thing"}])
    result = await _drift(ids)
    assert "silent_repo" in _kinds(result)
    assert result["hasDrift"] is True


@pytest.mark.asyncio
async def test_freshly_connected_repo_is_not_reported_as_silent(tmp_db):
    """The other false positive that matters: greeting someone with "no
    activity for 14 days" the day after they connected their repo."""
    ids = await _seed(connection_age_days=1)
    await _add_milestone(ids, "M1", [{"title": "Build the thing"}])
    assert "silent_repo" not in _kinds(await _drift(ids))


@pytest.mark.asyncio
async def test_no_connection_means_no_silent_repo_signal(tmp_db):
    ids = await _seed(with_connection=False)
    await _add_milestone(ids, "M1", [{"title": "Build the thing"}])
    result = await _drift(ids)
    assert "silent_repo" not in _kinds(result)
    assert result["repoConnected"] is False


@pytest.mark.asyncio
async def test_no_open_tasks_means_no_silent_repo_signal(tmp_db):
    ids = await _seed()
    await _add_milestone(ids, "M1", [
        {"title": "Done", "status": TaskStatus.DONE.value, "completed_at": NOW - timedelta(days=40)},
    ])
    assert "silent_repo" not in _kinds(await _drift(ids))


# ─── ahead of plan ───────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_tasks_finished_early_report_ahead_of_plan(tmp_db):
    ids = await _seed()
    task_id = uuid.uuid4()
    await _add_milestone(ids, "M1", [
        {
            "title": "Ship auth", "status": TaskStatus.DONE.value,
            "scheduled_date": TODAY + timedelta(days=10),
            "completed_at": NOW - timedelta(days=1),
        },
        {
            "title": "Ship billing", "status": TaskStatus.DONE.value,
            "scheduled_date": TODAY + timedelta(days=8),
            "completed_at": NOW - timedelta(days=1),
        },
        {"id": task_id, "title": "Ship search", "scheduled_date": TODAY + timedelta(days=20)},
    ])
    await _add_events(ids, 6, matched_task_id=task_id)

    result = await _drift(ids)
    assert "ahead_of_plan" in _kinds(result)
    # Being early is informational — it must not trip the warning banner.
    assert result["hasDrift"] is False


@pytest.mark.asyncio
async def test_one_early_task_is_not_a_pattern(tmp_db):
    ids = await _seed()
    task_id = uuid.uuid4()
    await _add_milestone(ids, "M1", [
        {
            "title": "Ship auth", "status": TaskStatus.DONE.value,
            "scheduled_date": TODAY + timedelta(days=10),
            "completed_at": NOW - timedelta(days=1),
        },
        {"id": task_id, "title": "Ship search", "scheduled_date": TODAY + timedelta(days=20)},
    ])
    await _add_events(ids, 6, matched_task_id=task_id)
    assert "ahead_of_plan" not in _kinds(await _drift(ids))


# ─── payload shape ───────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_warnings_sort_before_info(tmp_db):
    ids = await _seed()
    await _add_milestone(ids, "Auth work", [
        {"title": "Add login", "scheduled_date": TODAY - timedelta(days=10)},
        {
            "title": "Ship auth", "status": TaskStatus.DONE.value,
            "scheduled_date": TODAY + timedelta(days=10),
            "completed_at": NOW - timedelta(days=1),
        },
        {
            "title": "Ship billing", "status": TaskStatus.DONE.value,
            "scheduled_date": TODAY + timedelta(days=8),
            "completed_at": NOW - timedelta(days=1),
        },
    ])

    result = await _drift(ids)
    severities = [s["severity"] for s in result["signals"]]
    assert severities == sorted(severities, key=lambda s: s != "warning")


@pytest.mark.asyncio
async def test_payload_has_the_documented_keys(tmp_db):
    ids = await _seed()
    await _add_milestone(ids, "M1", [{"title": "Build the thing"}])
    result = await _drift(ids)
    assert set(result) == {"hasDrift", "computedAt", "windowDays", "repoConnected", "signals"}
    assert result["windowDays"] == roadmap_drift.DEFAULT_WINDOW_DAYS
    for signal in result["signals"]:
        assert set(signal) == {"kind", "severity", "headline", "detail", "milestoneIds", "evidence"}
