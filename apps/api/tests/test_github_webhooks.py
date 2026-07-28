"""
Tests for the GitHub App webhook receiver (routers/github_webhooks.py) and
its matching/idempotency logic (integrations/github/events.py). See
docs/plans/2026-07-20-github-task-autocomplete.md.

process_github_event.delay(...) is mocked at the router boundary (no Redis
broker in tests, same posture as this repo's other Celery-adjacent tests) —
the matching/idempotency logic itself is exercised directly against
`process_github_event_async`, bypassing Celery entirely, same idiom as
test_artifact_import.py exercising service logic through the router rather
than through a background worker.
"""

import hashlib
import hmac
import json
import uuid
from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient, ASGITransport

from src.config import settings
from src.main import app
from src.database import get_db
from src.models.organization import Organization
from src.models.team import Team
from src.models.onboarding_session import OnboardingSession
from src.models.project import Project
from src.models.milestone import Milestone
from src.models.task import Task, TaskStatus
from src.models.github_connection import GithubConnection
from src.models.github_activity_event import GithubActivityEvent
from src.integrations.github.events import process_github_event_async

ORG = "org_gh_webhook_test"
# GitHub installation ids are plain integers; GithubConnection.installation_id
# stores str(installation_id) (see integrations/github/router.py's callback).
INSTALLATION_ID = "777"
SECRET = "test-webhook-secret"


def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _enable_flag(enabled: bool = True):
    """Same idiom as test_artifact_import.py's `_enable_flag` — Settings'
    `is_feature_enabled` is patched at the class level."""
    real = type(settings).is_feature_enabled

    def fake(self, flag_name: str) -> bool:
        if flag_name == "experimental.github_autocomplete":
            return enabled
        return real(self, flag_name)

    return patch.object(type(settings), "is_feature_enabled", new=fake)


def _sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _status(task: Task) -> str:
    """Normalize a freshly-refetched Task's status to its plain string value.

    `tasks.status` is a SAEnum column: once a row round-trips through the DB
    it reloads as the `TaskStatus` *member*, not the string, so a bare
    `task.status == "done"` (or `== TaskStatus.DONE.value`) silently fails —
    same footgun documented in events.py's `_status_str`.
    """
    status = task.status
    return status.value if isinstance(status, TaskStatus) else status


async def _seed(clerk_org_id=ORG, installation_id=INSTALLATION_ID, short_id="AOS-1"):
    """Org + Team + Project + Milestone + one Task with a known short_id,
    plus an active GithubConnection for that installation_id."""
    ids = {k: uuid.uuid4() for k in ("org", "team", "session", "project", "milestone", "task")}
    async for db in app.dependency_overrides[get_db]():
        db.add(Organization(
            id=ids["org"], clerk_org_id=clerk_org_id, name="Test Org", slug=clerk_org_id,
            use_managed_key=False,
        ))
        db.add(Team(id=ids["team"], organization_id=ids["org"], name="Default"))
        db.add(OnboardingSession(id=ids["session"], organization_id=ids["org"], status="completed"))
        db.add(Project(
            id=ids["project"], team_id=ids["team"], onboarding_session_id=ids["session"],
            name="Proj", purpose="hobby",
        ))
        await db.flush()
        db.add(Milestone(id=ids["milestone"], project_id=ids["project"], title="M0", sort_order=0))
        await db.flush()
        db.add(Task(
            id=ids["task"], milestone_id=ids["milestone"], short_id=short_id,
            title="Do the thing", status=TaskStatus.TODO.value, sort_order=0,
        ))
        if installation_id is not None:
            db.add(GithubConnection(
                id=uuid.uuid4(), organization_id=ids["org"], installation_id=installation_id,
                github_user_id="1", github_login="octocat",
                encrypted_access_token="enc", is_active=True,
            ))
        await db.commit()
        return ids


def _push_payload(short_id: str, sha="abc123", branch="main"):
    return {
        "ref": f"refs/heads/{branch}",
        "repository": {"full_name": "octocat/hello"},
        "installation": {"id": int(INSTALLATION_ID)},
        "sender": {"login": "octocat"},
        "commits": [{
            "id": sha,
            "message": f"Fix the thing ({short_id})",
            "timestamp": "2026-07-28T10:00:00Z",
            "author": {"username": "octocat"},
            "url": f"https://github.com/octocat/hello/commit/{sha}",
        }],
    }


def _pull_request_payload(short_id: str, number=42, action="closed", merged=True):
    return {
        "action": action,
        "repository": {"full_name": "octocat/hello"},
        "installation": {"id": int(INSTALLATION_ID)},
        "pull_request": {
            "number": number,
            "title": f"Implements {short_id}",
            "body": "",
            "merged": merged,
            "merged_at": "2026-07-28T11:00:00Z" if merged else None,
            "updated_at": "2026-07-28T11:00:00Z",
            "created_at": "2026-07-28T09:00:00Z",
            "head": {"ref": f"feature/{short_id.lower()}"},
            "user": {"login": "octocat"},
            "html_url": f"https://github.com/octocat/hello/pull/{number}",
        },
    }


# ─── feature flag gate ──────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_webhook_404s_when_flag_disabled(tmp_db):
    body = json.dumps(_push_payload("AOS-1")).encode()
    with _enable_flag(False), patch("src.config.settings.github_app_webhook_secret", SECRET):
        async with _client() as client:
            resp = await client.post(
                "/api/webhooks/github",
                content=body,
                headers={"X-Hub-Signature-256": _sign(SECRET, body), "X-GitHub-Event": "push"},
            )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_webhook_reachable_when_flag_enabled(tmp_db):
    await _seed()
    body = json.dumps(_push_payload("AOS-1")).encode()
    with (
        _enable_flag(True),
        patch("src.config.settings.github_app_webhook_secret", SECRET),
        patch("src.routers.github_webhooks.process_github_event.delay", new=MagicMock()),
    ):
        async with _client() as client:
            resp = await client.post(
                "/api/webhooks/github",
                content=body,
                headers={"X-Hub-Signature-256": _sign(SECRET, body), "X-GitHub-Event": "push"},
            )
    assert resp.status_code == 200


# ─── signature verification ─────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_webhook_rejects_missing_signature(tmp_db):
    body = json.dumps(_push_payload("AOS-1")).encode()
    with _enable_flag(True), patch("src.config.settings.github_app_webhook_secret", SECRET):
        async with _client() as client:
            resp = await client.post(
                "/api/webhooks/github", content=body, headers={"X-GitHub-Event": "push"},
            )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_webhook_rejects_invalid_signature(tmp_db):
    body = json.dumps(_push_payload("AOS-1")).encode()
    with _enable_flag(True), patch("src.config.settings.github_app_webhook_secret", SECRET):
        async with _client() as client:
            resp = await client.post(
                "/api/webhooks/github",
                content=body,
                headers={"X-Hub-Signature-256": "sha256=deadbeef", "X-GitHub-Event": "push"},
            )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_webhook_accepts_valid_signature(tmp_db):
    await _seed()
    body = json.dumps(_push_payload("AOS-1")).encode()
    with (
        _enable_flag(True),
        patch("src.config.settings.github_app_webhook_secret", SECRET),
        patch("src.routers.github_webhooks.process_github_event.delay", new=MagicMock()) as delay,
    ):
        async with _client() as client:
            resp = await client.post(
                "/api/webhooks/github",
                content=body,
                headers={"X-Hub-Signature-256": _sign(SECRET, body), "X-GitHub-Event": "push"},
            )
    assert resp.status_code == 200
    delay.assert_called_once()


@pytest.mark.asyncio
async def test_webhook_ignores_unrecognized_installation(tmp_db):
    await _seed(installation_id="inst_other")
    body = json.dumps(_push_payload("AOS-1")).encode()
    with (
        _enable_flag(True),
        patch("src.config.settings.github_app_webhook_secret", SECRET),
        patch("src.routers.github_webhooks.process_github_event.delay", new=MagicMock()) as delay,
    ):
        async with _client() as client:
            resp = await client.post(
                "/api/webhooks/github",
                content=body,
                headers={"X-Hub-Signature-256": _sign(SECRET, body), "X-GitHub-Event": "push"},
            )
    assert resp.status_code == 200
    delay.assert_not_called()


# ─── matching rules (exercised directly against process_github_event_async) ─
@pytest.mark.asyncio
async def test_push_referencing_task_marks_in_progress_and_records_event(tmp_db):
    ids = await _seed(short_id="AOS-1")
    payload = _push_payload("AOS-1")

    async for db in app.dependency_overrides[get_db]():
        await process_github_event_async(ids["org"], "push", payload, db)
        break

    from sqlalchemy import select

    async for db in app.dependency_overrides[get_db]():
        task = await db.get(Task, ids["task"])
        assert _status(task) == TaskStatus.IN_PROGRESS.value
        events = (await db.execute(select(GithubActivityEvent))).scalars().all()
        assert len(events) == 1
        assert events[0].event_type == "push"
        assert events[0].matched_task_id == ids["task"]
        break


@pytest.mark.asyncio
async def test_pr_opened_alone_does_not_complete_task(tmp_db):
    ids = await _seed(short_id="AOS-1")
    payload = _pull_request_payload("AOS-1", action="opened", merged=False)

    async for db in app.dependency_overrides[get_db]():
        await process_github_event_async(ids["org"], "pull_request", payload, db)
        break

    async for db in app.dependency_overrides[get_db]():
        task = await db.get(Task, ids["task"])
        assert _status(task) == TaskStatus.TODO.value
        assert task.completed_at is None
        break


@pytest.mark.asyncio
async def test_pr_merged_marks_done_and_sets_completed_at(tmp_db):
    ids = await _seed(short_id="AOS-1")
    payload = _pull_request_payload("AOS-1", action="closed", merged=True)

    async for db in app.dependency_overrides[get_db]():
        await process_github_event_async(ids["org"], "pull_request", payload, db)
        break

    async for db in app.dependency_overrides[get_db]():
        task = await db.get(Task, ids["task"])
        assert _status(task) == TaskStatus.DONE.value
        assert task.completed_at is not None
        break


@pytest.mark.asyncio
async def test_pr_closed_without_merge_does_not_complete_task(tmp_db):
    ids = await _seed(short_id="AOS-1")
    payload = _pull_request_payload("AOS-1", action="closed", merged=False)

    async for db in app.dependency_overrides[get_db]():
        await process_github_event_async(ids["org"], "pull_request", payload, db)
        break

    async for db in app.dependency_overrides[get_db]():
        task = await db.get(Task, ids["task"])
        assert _status(task) == TaskStatus.TODO.value
        break


@pytest.mark.asyncio
async def test_push_never_downgrades_a_done_task(tmp_db):
    ids = await _seed(short_id="AOS-1")
    async for db in app.dependency_overrides[get_db]():
        task = await db.get(Task, ids["task"])
        task.status = TaskStatus.DONE.value
        await db.commit()
        break

    payload = _push_payload("AOS-1")
    async for db in app.dependency_overrides[get_db]():
        await process_github_event_async(ids["org"], "push", payload, db)
        break

    async for db in app.dependency_overrides[get_db]():
        task = await db.get(Task, ids["task"])
        assert _status(task) == TaskStatus.DONE.value
        break


# ─── idempotency ─────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_duplicate_push_delivery_does_not_double_write_event(tmp_db):
    ids = await _seed(short_id="AOS-1")
    payload = _push_payload("AOS-1", sha="same-sha")

    async for db in app.dependency_overrides[get_db]():
        await process_github_event_async(ids["org"], "push", payload, db)
        await process_github_event_async(ids["org"], "push", payload, db)
        break

    from sqlalchemy import select

    async for db in app.dependency_overrides[get_db]():
        events = (await db.execute(select(GithubActivityEvent))).scalars().all()
        assert len(events) == 1
        break


@pytest.mark.asyncio
async def test_duplicate_merged_pr_delivery_does_not_double_write_or_re_apply(tmp_db):
    ids = await _seed(short_id="AOS-1")
    payload = _pull_request_payload("AOS-1", number=99, action="closed", merged=True)

    async for db in app.dependency_overrides[get_db]():
        await process_github_event_async(ids["org"], "pull_request", payload, db)
        break

    # Manually revert status to simulate a human re-opening it — if the
    # duplicate delivery re-applied the mutation it would flip back to DONE;
    # since it's a dup, it must be a no-op instead.
    async for db in app.dependency_overrides[get_db]():
        task = await db.get(Task, ids["task"])
        task.status = TaskStatus.TODO.value
        task.completed_at = None
        await db.commit()
        break

    async for db in app.dependency_overrides[get_db]():
        await process_github_event_async(ids["org"], "pull_request", payload, db)
        break

    from sqlalchemy import select

    async for db in app.dependency_overrides[get_db]():
        events = (await db.execute(select(GithubActivityEvent))).scalars().all()
        assert len(events) == 1
        task = await db.get(Task, ids["task"])
        assert _status(task) == TaskStatus.TODO.value
        break


# ─── org scoping (a lookalike short_id in another org must never match) ─────
@pytest.mark.asyncio
async def test_short_id_match_is_scoped_to_the_event_org(tmp_db):
    ids_a = await _seed(clerk_org_id="org_a_scope_test", installation_id="inst_a", short_id="AOS-1")
    ids_b = await _seed(clerk_org_id="org_b_scope_test", installation_id="inst_b", short_id="AOS-1")

    payload = _push_payload("AOS-1")
    async for db in app.dependency_overrides[get_db]():
        await process_github_event_async(ids_a["org"], "push", payload, db)
        break

    async for db in app.dependency_overrides[get_db]():
        task_a = await db.get(Task, ids_a["task"])
        task_b = await db.get(Task, ids_b["task"])
        assert _status(task_a) == TaskStatus.IN_PROGRESS.value
        assert _status(task_b) == TaskStatus.TODO.value
        break
