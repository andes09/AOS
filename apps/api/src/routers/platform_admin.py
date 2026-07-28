"""
Platform admin dashboard — a cross-org, founder-only view of business health
(total users, AI cost, GitHub commit activity, per-org rollup). Distinct
from the existing org-scoped ExecDashboardPage; this reads across every org.

Gated behind BOTH:
  - the `experimental.master_dashboard` feature flag (404s while off — same
    posture as artifact_import.py/github_webhooks.py's own flag gates: the
    route is invisible, not just refused, while unshipped)
  - `require_platform_admin` (src/auth_platform.py), a Clerk user-ID
    allowlist (403 if not allowlisted) — this is the REAL security boundary;
    the flag above is just an extra kill switch, same posture as the other
    stages' flags.

Commit data reads from `github_activity_events` (see
src/models/github_activity_event.py), not a separate aggregate table — that
table already logs one row per commit with `event_type="push"` (fed by both
the GitHub App webhook and the reconciliation sweep from stage 3's
github-task-autocomplete work), so it's a strict superset of what a
`github_commit_daily` rollup table would have provided. See this repo's
docs/plans/2026-07-20-master-dashboard.md "Implementation Notes" for the
full list of corrections from the original plan doc.

GET /api/platform-admin/overview
GET /api/platform-admin/signups?range=7d|30d|90d|all
GET /api/platform-admin/cost?range=7d|30d|90d|all
GET /api/platform-admin/commits?range=7d|30d|90d|all
GET /api/platform-admin/orgs
"""

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth_platform import require_platform_admin
from src.config import settings
from src.database import get_db
from src.models.ai_usage_event import AIUsageEvent
from src.models.developer import Developer
from src.models.github_activity_event import GithubActivityEvent
from src.models.organization import Organization
from src.models.team import Team

logger = logging.getLogger(__name__)

_RANGE_DAYS = {"7d": 7, "30d": 30, "90d": 90}
_VALID_RANGES = (*_RANGE_DAYS, "all")


def _require_master_dashboard_enabled() -> None:
    if not settings.is_feature_enabled("experimental.master_dashboard"):
        raise HTTPException(status_code=404, detail="not_found")


router = APIRouter(
    prefix="/api/platform-admin",
    tags=["platform-admin"],
    dependencies=[Depends(_require_master_dashboard_enabled), Depends(require_platform_admin)],
)


def _validate_range(range_: str) -> str:
    if range_ not in _VALID_RANGES:
        raise HTTPException(status_code=422, detail=f"range must be one of {', '.join(_VALID_RANGES)}")
    return range_


def _range_start(range_: str) -> datetime | None:
    """None means 'all time' (no lower bound)."""
    days = _RANGE_DAYS.get(range_)
    return None if days is None else datetime.utcnow() - timedelta(days=days)


def _day(dt: datetime) -> str:
    return dt.date().isoformat()


@router.get("/overview")
async def get_overview(db: AsyncSession = Depends(get_db)):
    total_orgs = await db.scalar(select(func.count()).select_from(Organization)) or 0
    total_users = (
        await db.scalar(
            select(func.count(func.distinct(Developer.clerk_user_id))).where(
                Developer.clerk_user_id.is_not(None)
            )
        )
        or 0
    )

    last30 = datetime.utcnow() - timedelta(days=30)

    cost_all_time = await db.scalar(select(func.coalesce(func.sum(AIUsageEvent.cost_usd), 0)))
    cost_30d = await db.scalar(
        select(func.coalesce(func.sum(AIUsageEvent.cost_usd), 0)).where(AIUsageEvent.created_at >= last30)
    )

    commits_all_time = (
        await db.scalar(
            select(func.count()).select_from(GithubActivityEvent).where(GithubActivityEvent.event_type == "push")
        )
        or 0
    )
    commits_30d = (
        await db.scalar(
            select(func.count())
            .select_from(GithubActivityEvent)
            .where(GithubActivityEvent.event_type == "push", GithubActivityEvent.occurred_at >= last30)
        )
        or 0
    )

    return {
        "totalOrgs": total_orgs,
        "totalUsers": total_users,
        "cost": {"allTimeUsd": float(cost_all_time or 0), "last30dUsd": float(cost_30d or 0)},
        "commits": {"allTime": commits_all_time, "last30d": commits_30d},
    }


@router.get("/signups")
async def get_signups(range: str = Query("30d"), db: AsyncSession = Depends(get_db)):
    range_ = _validate_range(range)
    start = _range_start(range_)

    user_conditions = [Developer.clerk_user_id.is_not(None)]
    org_conditions = []
    if start:
        user_conditions.append(Developer.created_at >= start)
        org_conditions.append(Organization.created_at >= start)

    user_rows = (await db.execute(select(Developer.created_at).where(*user_conditions))).all()
    org_rows = (await db.execute(select(Organization.created_at).where(*org_conditions))).all()

    user_buckets: dict[str, int] = {}
    for (created_at,) in user_rows:
        user_buckets[_day(created_at)] = user_buckets.get(_day(created_at), 0) + 1
    org_buckets: dict[str, int] = {}
    for (created_at,) in org_rows:
        org_buckets[_day(created_at)] = org_buckets.get(_day(created_at), 0) + 1

    baseline_users = baseline_orgs = 0
    if start:
        baseline_users = (
            await db.scalar(
                select(func.count())
                .select_from(Developer)
                .where(Developer.clerk_user_id.is_not(None), Developer.created_at < start)
            )
            or 0
        )
        baseline_orgs = (
            await db.scalar(select(func.count()).select_from(Organization).where(Organization.created_at < start))
            or 0
        )

    all_days = sorted(set(user_buckets) | set(org_buckets))
    series = []
    cum_users, cum_orgs = baseline_users, baseline_orgs
    for day in all_days:
        cum_users += user_buckets.get(day, 0)
        cum_orgs += org_buckets.get(day, 0)
        series.append(
            {
                "date": day,
                "newUsers": user_buckets.get(day, 0),
                "newOrgs": org_buckets.get(day, 0),
                "cumulativeUsers": cum_users,
                "cumulativeOrgs": cum_orgs,
            }
        )
    return {"range": range_, "series": series}


@router.get("/cost")
async def get_cost_series(range: str = Query("30d"), db: AsyncSession = Depends(get_db)):
    range_ = _validate_range(range)
    start = _range_start(range_)

    conditions = []
    if start:
        conditions.append(AIUsageEvent.created_at >= start)

    rows = (
        await db.execute(select(AIUsageEvent.created_at, AIUsageEvent.provider, AIUsageEvent.cost_usd).where(*conditions))
    ).all()

    buckets: dict[str, dict[str, float]] = {}
    for created_at, provider, cost_usd in rows:
        b = buckets.setdefault(_day(created_at), {"anthropicUsd": 0.0, "groqUsd": 0.0})
        if provider == "anthropic":
            b["anthropicUsd"] += float(cost_usd)
        elif provider == "groq":
            b["groqUsd"] += float(cost_usd)

    series = [
        {
            "date": day,
            "anthropicUsd": round(buckets[day]["anthropicUsd"], 6),
            "groqUsd": round(buckets[day]["groqUsd"], 6),
            "totalUsd": round(buckets[day]["anthropicUsd"] + buckets[day]["groqUsd"], 6),
        }
        for day in sorted(buckets)
    ]
    return {"range": range_, "series": series}


@router.get("/commits")
async def get_commits_series(range: str = Query("30d"), db: AsyncSession = Depends(get_db)):
    range_ = _validate_range(range)
    start = _range_start(range_)

    conditions = [GithubActivityEvent.event_type == "push"]
    if start:
        conditions.append(GithubActivityEvent.occurred_at >= start)

    rows = (await db.execute(select(GithubActivityEvent.occurred_at).where(*conditions))).all()

    buckets: dict[str, int] = {}
    for (occurred_at,) in rows:
        buckets[_day(occurred_at)] = buckets.get(_day(occurred_at), 0) + 1

    series = [{"date": day, "commits": buckets[day]} for day in sorted(buckets)]
    return {"range": range_, "series": series}


@router.get("/orgs")
async def get_org_rollup(db: AsyncSession = Depends(get_db)):
    orgs = (await db.execute(select(Organization))).scalars().all()
    if not orgs:
        return {"orgs": []}
    org_ids = [o.id for o in orgs]
    last30 = datetime.utcnow() - timedelta(days=30)

    user_counts = dict(
        (
            await db.execute(
                select(Team.organization_id, func.count(func.distinct(Developer.clerk_user_id)))
                .join(Developer, Developer.team_id == Team.id)
                .where(Developer.clerk_user_id.is_not(None), Team.organization_id.in_(org_ids))
                .group_by(Team.organization_id)
            )
        ).all()
    )
    cost_all = dict(
        (
            await db.execute(
                select(AIUsageEvent.organization_id, func.sum(AIUsageEvent.cost_usd))
                .where(AIUsageEvent.organization_id.in_(org_ids))
                .group_by(AIUsageEvent.organization_id)
            )
        ).all()
    )
    cost_30d = dict(
        (
            await db.execute(
                select(AIUsageEvent.organization_id, func.sum(AIUsageEvent.cost_usd))
                .where(AIUsageEvent.organization_id.in_(org_ids), AIUsageEvent.created_at >= last30)
                .group_by(AIUsageEvent.organization_id)
            )
        ).all()
    )
    commits_all = dict(
        (
            await db.execute(
                select(GithubActivityEvent.organization_id, func.count())
                .where(GithubActivityEvent.organization_id.in_(org_ids), GithubActivityEvent.event_type == "push")
                .group_by(GithubActivityEvent.organization_id)
            )
        ).all()
    )
    commits_30d = dict(
        (
            await db.execute(
                select(GithubActivityEvent.organization_id, func.count())
                .where(
                    GithubActivityEvent.organization_id.in_(org_ids),
                    GithubActivityEvent.event_type == "push",
                    GithubActivityEvent.occurred_at >= last30,
                )
                .group_by(GithubActivityEvent.organization_id)
            )
        ).all()
    )

    rollup = [
        {
            "id": str(org.id),
            "name": org.name,
            "slug": org.slug,
            "createdAt": org.created_at.isoformat(),
            "userCount": user_counts.get(org.id, 0),
            "costAllTimeUsd": float(cost_all.get(org.id, 0) or 0),
            "cost30dUsd": float(cost_30d.get(org.id, 0) or 0),
            "commitsAllTime": commits_all.get(org.id, 0),
            "commits30d": commits_30d.get(org.id, 0),
            "onboardingCompleted": org.onboarding_completed_at is not None,
        }
        for org in sorted(orgs, key=lambda o: o.created_at, reverse=True)
    ]
    return {"orgs": rollup}
