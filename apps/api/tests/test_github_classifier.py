"""
Tests for the LLM matching tier (services/github_classifier.py).

The Groq call is patched at `_call_planner`, the same seam
test_roadmap_generator.py uses — no network, no key, no tokens. What's
actually under test is everything around the call: which rows get selected,
the confidence floor, the "stamp everything so we never re-bill for it" rule,
and the invariant that an LLM match is evidence and never authority.
"""

import uuid
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from src.main import app
from src.database import get_db
from src.models.organization import Organization
from src.models.team import Team
from src.models.onboarding_session import OnboardingSession
from src.models.project import Project
from src.models.milestone import Milestone
from src.models.task import Task, TaskStatus
from src.models.github_activity_event import GithubActivityEvent, MatchMethod
from src.services import github_classifier
from src.services.github_classifier import classify_unmatched_events_async

CALL_PLANNER = "src.services.roadmap_generator._call_planner"


class _Usage:
    prompt_tokens = 100
    completion_tokens = 20


def _status(task: Task) -> str:
    status = task.status
    return status.value if isinstance(status, TaskStatus) else status


async def _seed(*, n_events=1, task_title="Implement JWT refresh token rotation", messages=None):
    """Org + one open task + `n_events` unmatched, unclassified events."""
    ids = {k: uuid.uuid4() for k in ("org", "team", "session", "project", "milestone", "task")}
    ids["events"] = []
    messages = messages or [f"opaque commit {i}" for i in range(n_events)]

    async for db in app.dependency_overrides[get_db]():
        db.add(Organization(
            id=ids["org"], clerk_org_id=f"org_{ids['org'].hex[:8]}", name="O",
            slug=ids["org"].hex[:8], use_managed_key=False,
        ))
        db.add(Team(id=ids["team"], organization_id=ids["org"], name="T"))
        db.add(OnboardingSession(id=ids["session"], organization_id=ids["org"], status="completed"))
        db.add(Project(
            id=ids["project"], team_id=ids["team"], onboarding_session_id=ids["session"],
            name="P", purpose="hobby",
        ))
        await db.flush()
        db.add(Milestone(id=ids["milestone"], project_id=ids["project"], title="M", sort_order=0))
        await db.flush()
        db.add(Task(
            id=ids["task"], milestone_id=ids["milestone"], short_id="AOS-1",
            title=task_title, status=TaskStatus.TODO.value, sort_order=0,
        ))
        for i, message in enumerate(messages):
            event_id = uuid.uuid4()
            ids["events"].append(event_id)
            db.add(GithubActivityEvent(
                id=event_id, organization_id=ids["org"], repo_full_name="a/b",
                event_type="push", external_id=f"sha{i}", title_or_message=message,
                match_method=MatchMethod.UNMATCHED, occurred_at=datetime.utcnow(),
            ))
        await db.commit()
    return ids


async def _events(org_id) -> list[GithubActivityEvent]:
    async for db in app.dependency_overrides[get_db]():
        rows = (await db.execute(
            select(GithubActivityEvent)
            .where(GithubActivityEvent.organization_id == org_id)
            .order_by(GithubActivityEvent.external_id)
        )).scalars().all()
        return list(rows)


def _planner(results):
    return AsyncMock(return_value=({"results": results}, _Usage()))


# ─── the confidence floor ────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_confident_match_is_recorded_as_llm(tmp_db):
    ids = await _seed()
    planner = _planner([{"eventIndex": 1, "taskIndex": 1, "confidence": 0.9}])

    async for db in app.dependency_overrides[get_db]():
        with patch(CALL_PLANNER, new=planner), patch.object(github_classifier.settings, "groq_api_key", "k"):
            matched = await classify_unmatched_events_async(ids["org"], db)
        break

    assert matched == 1
    event = (await _events(ids["org"]))[0]
    assert event.matched_task_id == ids["task"]
    assert event.match_method == MatchMethod.LLM
    assert event.match_confidence == 0.9
    assert event.classified_at is not None


@pytest.mark.asyncio
async def test_low_confidence_match_is_discarded_but_still_stamped(tmp_db):
    """An unconfident guess recorded as a match would understate unplanned
    work — the exact error this tier exists to avoid. It must be dropped, but
    the row still has to be stamped so we don't pay to ask again."""
    ids = await _seed()
    planner = _planner([{"eventIndex": 1, "taskIndex": 1, "confidence": 0.2}])

    async for db in app.dependency_overrides[get_db]():
        with patch(CALL_PLANNER, new=planner), patch.object(github_classifier.settings, "groq_api_key", "k"):
            matched = await classify_unmatched_events_async(ids["org"], db)
        break

    assert matched == 0
    event = (await _events(ids["org"]))[0]
    assert event.matched_task_id is None
    assert event.match_method == MatchMethod.UNMATCHED
    assert event.classified_at is not None


@pytest.mark.asyncio
async def test_explicit_unplanned_verdict_is_stamped(tmp_db):
    ids = await _seed()
    planner = _planner([{"eventIndex": 1, "taskIndex": None, "confidence": 0.95}])

    async for db in app.dependency_overrides[get_db]():
        with patch(CALL_PLANNER, new=planner), patch.object(github_classifier.settings, "groq_api_key", "k"):
            assert await classify_unmatched_events_async(ids["org"], db) == 0
        break

    event = (await _events(ids["org"]))[0]
    assert event.match_method == MatchMethod.UNMATCHED
    assert event.classified_at is not None


# ─── idempotency / cost control ─────────────────────────────────────────────
@pytest.mark.asyncio
async def test_already_classified_events_are_not_resent(tmp_db):
    ids = await _seed()
    planner = _planner([{"eventIndex": 1, "taskIndex": None, "confidence": 0.9}])

    async for db in app.dependency_overrides[get_db]():
        with patch(CALL_PLANNER, new=planner), patch.object(github_classifier.settings, "groq_api_key", "k"):
            await classify_unmatched_events_async(ids["org"], db)
            await classify_unmatched_events_async(ids["org"], db)
        break

    # Second run found nothing to do — one call total, not two.
    assert planner.await_count == 1


@pytest.mark.asyncio
async def test_events_omitted_by_the_model_are_still_stamped(tmp_db):
    """A model that returns fewer results than events must not leave rows to be
    retried at full cost forever."""
    ids = await _seed(n_events=3)
    planner = _planner([{"eventIndex": 1, "taskIndex": None, "confidence": 0.9}])

    async for db in app.dependency_overrides[get_db]():
        with patch(CALL_PLANNER, new=planner), patch.object(github_classifier.settings, "groq_api_key", "k"):
            await classify_unmatched_events_async(ids["org"], db)
        break

    assert all(e.classified_at is not None for e in await _events(ids["org"]))


@pytest.mark.asyncio
async def test_out_of_range_indices_from_the_model_are_ignored(tmp_db):
    ids = await _seed()
    planner = _planner([
        {"eventIndex": 99, "taskIndex": 1, "confidence": 0.9},
        {"eventIndex": 1, "taskIndex": 99, "confidence": 0.9},
    ])

    async for db in app.dependency_overrides[get_db]():
        with patch(CALL_PLANNER, new=planner), patch.object(github_classifier.settings, "groq_api_key", "k"):
            assert await classify_unmatched_events_async(ids["org"], db) == 0
        break

    assert (await _events(ids["org"]))[0].matched_task_id is None


# ─── degradation ─────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_missing_api_key_is_a_quiet_noop(tmp_db):
    ids = await _seed()
    async for db in app.dependency_overrides[get_db]():
        with patch.object(github_classifier.settings, "groq_api_key", ""):
            assert await classify_unmatched_events_async(ids["org"], db) == 0
        break
    assert (await _events(ids["org"]))[0].classified_at is None


@pytest.mark.asyncio
async def test_groq_failure_leaves_rows_for_the_next_sweep(tmp_db):
    ids = await _seed()
    async for db in app.dependency_overrides[get_db]():
        with (
            patch(CALL_PLANNER, new=AsyncMock(side_effect=RuntimeError("groq down"))),
            patch.object(github_classifier.settings, "groq_api_key", "k"),
        ):
            assert await classify_unmatched_events_async(ids["org"], db) == 0
        break
    # Not stamped — it gets another turn, which is the desired degradation.
    assert (await _events(ids["org"]))[0].classified_at is None


@pytest.mark.asyncio
async def test_org_with_no_open_tasks_is_stamped_without_calling_groq(tmp_db):
    ids = await _seed()
    async for db in app.dependency_overrides[get_db]():
        task = await db.get(Task, ids["task"])
        task.status = TaskStatus.DONE.value
        await db.commit()
        break

    planner = _planner([])
    async for db in app.dependency_overrides[get_db]():
        with patch(CALL_PLANNER, new=planner), patch.object(github_classifier.settings, "groq_api_key", "k"):
            assert await classify_unmatched_events_async(ids["org"], db) == 0
        break

    assert planner.await_count == 0
    assert (await _events(ids["org"]))[0].classified_at is not None


# ─── the evidence-only rule ─────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_llm_match_never_moves_the_task(tmp_db):
    """The same guarantee the heuristic tier has, at the tier most likely to be
    wrong. A model's opinion is evidence for drift, never a status change."""
    ids = await _seed()
    planner = _planner([{"eventIndex": 1, "taskIndex": 1, "confidence": 1.0}])

    async for db in app.dependency_overrides[get_db]():
        with patch(CALL_PLANNER, new=planner), patch.object(github_classifier.settings, "groq_api_key", "k"):
            await classify_unmatched_events_async(ids["org"], db)
        break

    async for db in app.dependency_overrides[get_db]():
        task = await db.get(Task, ids["task"])
        assert _status(task) == TaskStatus.TODO.value
        assert task.completed_at is None
        break


# ─── selection window ────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_events_older_than_the_window_are_left_alone(tmp_db):
    ids = await _seed()
    async for db in app.dependency_overrides[get_db]():
        event = await db.get(GithubActivityEvent, ids["events"][0])
        event.occurred_at = datetime.utcnow() - timedelta(days=github_classifier._MAX_AGE_DAYS + 1)
        await db.commit()
        break

    planner = _planner([])
    async for db in app.dependency_overrides[get_db]():
        with patch(CALL_PLANNER, new=planner), patch.object(github_classifier.settings, "groq_api_key", "k"):
            assert await classify_unmatched_events_async(ids["org"], db) == 0
        break
    assert planner.await_count == 0
