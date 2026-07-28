"""
Tests for the platform admin dashboard (routers/platform_admin.py):
- experimental.master_dashboard feature-flag gate (404 while off — an extra
  kill switch, same posture as artifact_import.py/github_webhooks.py)
- require_platform_admin Clerk-allowlist auth (403 non-allowlisted, 200
  allowlisted) — the real security boundary
- the commit endpoints reading from github_activity_events (event_type
  'push', not a separate github_commit_daily table — see this repo's
  docs/plans/2026-07-20-master-dashboard.md Implementation Notes)
- basic shape/content of overview, signups, cost, commits, orgs
"""

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient

from src.config import settings
from src.main import app

USER = "user_platform_admin_test"
NON_ADMIN_USER = "user_regular"
AUTH = {"Authorization": "Bearer tok"}


def _patch_clerk(user_id=USER):
    payload = {"sub": user_id}
    state = type("S", (), {"is_signed_in": True, "payload": payload})()
    return patch("src.auth._clerk.authenticate_request_async", new=AsyncMock(return_value=state))


def _enable_flag(enabled: bool = True):
    """Same idiom as test_artifact_import.py/test_github_webhooks.py:
    Settings.is_feature_enabled patched at the class level, real behavior
    preserved for every other flag."""
    real = type(settings).is_feature_enabled

    def fake(self, flag_name: str) -> bool:
        if flag_name == "experimental.master_dashboard":
            return enabled
        return real(self, flag_name)

    return patch.object(type(settings), "is_feature_enabled", new=fake)


def _allowlist(*user_ids: str):
    return patch.object(settings, "platform_admin_user_ids", ",".join(user_ids))


def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _seed_org_team_dev(clerk_org_id="org_pa"):
    from src.database import get_db
    from src.models.developer import Developer
    from src.models.organization import Organization
    from src.models.team import Team

    async for db in app.dependency_overrides[get_db]():
        org = Organization(
            id=uuid.uuid4(), clerk_org_id=clerk_org_id, name="Org", slug=clerk_org_id, use_managed_key=True
        )
        db.add(org)
        await db.flush()
        team = Team(id=uuid.uuid4(), organization_id=org.id, name="Team")
        db.add(team)
        await db.flush()
        dev = Developer(id=uuid.uuid4(), team_id=team.id, clerk_user_id="dev_1", name="Dev One")
        db.add(dev)
        await db.commit()
        return org.id, team.id


# ─── feature flag gate ──────────────────────────────────────────────────────
async def test_404s_when_flag_disabled(tmp_db):
    with _enable_flag(False), _allowlist(USER), _patch_clerk():
        async with _client() as client:
            resp = await client.get("/api/platform-admin/overview", headers=AUTH)
    assert resp.status_code == 404


# ─── auth (real security boundary) ──────────────────────────────────────────
async def test_403_when_not_allowlisted(tmp_db):
    with _enable_flag(True), _allowlist("someone_else"), _patch_clerk(user_id=NON_ADMIN_USER):
        async with _client() as client:
            resp = await client.get("/api/platform-admin/overview", headers=AUTH)
    assert resp.status_code == 403


async def test_403_when_allowlist_empty_by_default(tmp_db):
    with _enable_flag(True), _allowlist(), _patch_clerk(user_id=USER):
        async with _client() as client:
            resp = await client.get("/api/platform-admin/overview", headers=AUTH)
    assert resp.status_code == 403


async def test_200_when_allowlisted(tmp_db):
    with _enable_flag(True), _allowlist(USER), _patch_clerk(user_id=USER):
        async with _client() as client:
            resp = await client.get("/api/platform-admin/overview", headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"totalOrgs", "totalUsers", "cost", "commits"}


# ─── overview content ────────────────────────────────────────────────────────
async def test_overview_counts_orgs_and_distinct_users(tmp_db):
    await _seed_org_team_dev()
    with _enable_flag(True), _allowlist(USER), _patch_clerk(user_id=USER):
        async with _client() as client:
            resp = await client.get("/api/platform-admin/overview", headers=AUTH)
    body = resp.json()
    assert body["totalOrgs"] == 1
    assert body["totalUsers"] == 1


# ─── commit endpoints read github_activity_events, event_type == 'push' ─────
async def test_commits_only_count_push_events_not_pr_events(tmp_db):
    org_id, _team_id = await _seed_org_team_dev()
    from src.database import get_db
    from src.models.github_activity_event import GithubActivityEvent

    now = datetime.utcnow()
    async for db in app.dependency_overrides[get_db]():
        db.add(
            GithubActivityEvent(
                id=uuid.uuid4(), organization_id=org_id, repo_full_name="acme/repo",
                event_type="push", external_id="sha1", occurred_at=now,
            )
        )
        db.add(
            GithubActivityEvent(
                id=uuid.uuid4(), organization_id=org_id, repo_full_name="acme/repo",
                event_type="pr_opened", external_id="pr-1-opened", occurred_at=now,
            )
        )
        await db.commit()
        break

    with _enable_flag(True), _allowlist(USER), _patch_clerk(user_id=USER):
        async with _client() as client:
            overview_resp = await client.get("/api/platform-admin/overview", headers=AUTH)
            series_resp = await client.get("/api/platform-admin/commits?range=30d", headers=AUTH)

    assert overview_resp.json()["commits"]["allTime"] == 1
    series = series_resp.json()["series"]
    assert sum(s["commits"] for s in series) == 1


# ─── /orgs rollup ────────────────────────────────────────────────────────────
async def test_orgs_rollup_includes_cost_and_commits(tmp_db):
    org_id, team_id = await _seed_org_team_dev()
    from src.database import get_db
    from src.models.ai_usage_event import AIUsageEvent
    from src.models.github_activity_event import GithubActivityEvent

    async for db in app.dependency_overrides[get_db]():
        db.add(
            AIUsageEvent(
                id=uuid.uuid4(), organization_id=org_id, team_id=team_id, provider="anthropic",
                operation="roadmap_generate", model="claude", input_tokens=1_000_000, output_tokens=0,
                cache_write_tokens=0, cache_read_tokens=0, call_count=1, cost_usd=3.0,
            )
        )
        db.add(
            GithubActivityEvent(
                id=uuid.uuid4(), organization_id=org_id, repo_full_name="acme/repo",
                event_type="push", external_id="sha1", occurred_at=datetime.utcnow(),
            )
        )
        await db.commit()
        break

    with _enable_flag(True), _allowlist(USER), _patch_clerk(user_id=USER):
        async with _client() as client:
            resp = await client.get("/api/platform-admin/orgs", headers=AUTH)
    orgs = resp.json()["orgs"]
    assert len(orgs) == 1
    row = orgs[0]
    assert row["userCount"] == 1
    assert row["costAllTimeUsd"] == 3.0
    assert row["commitsAllTime"] == 1
    assert row["onboardingCompleted"] is False


# ─── /signups cumulative counts ──────────────────────────────────────────────
async def test_signups_series_has_cumulative_counts(tmp_db):
    await _seed_org_team_dev()
    with _enable_flag(True), _allowlist(USER), _patch_clerk(user_id=USER):
        async with _client() as client:
            resp = await client.get("/api/platform-admin/signups?range=all", headers=AUTH)
    series = resp.json()["series"]
    assert series
    assert series[-1]["cumulativeUsers"] >= 1
    assert series[-1]["cumulativeOrgs"] >= 1


async def test_invalid_range_422(tmp_db):
    with _enable_flag(True), _allowlist(USER), _patch_clerk(user_id=USER):
        async with _client() as client:
            resp = await client.get("/api/platform-admin/cost?range=bogus", headers=AUTH)
    assert resp.status_code == 422
