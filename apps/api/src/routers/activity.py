"""
Activity — the anti-dormancy re-engagement surface.

GET /api/activity/summary → the "welcome back" banner's payload.

Org-scoped, not project-scoped: `last_active_at` is a fact about a *person*
(who may carry several projects), and the banner lives on the /app landing
(the Project Hub), above any single project. The one write this feature makes —
touching the caller's `last_active_at` — happens here via mark_developer_active,
whose return value (the *previous* timestamp) is exactly what the summary needs
to measure how long they were away.

See docs/plans/2026-07-20-anti-dormancy-mvp.md.
"""

from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_org_id
from src.database import get_db
from src.dependencies import mark_developer_active
from src.routers.project_common import _get_org
from src.services import activity

router = APIRouter(prefix="/api/activity", tags=["activity"])


@router.get("/summary")
async def get_summary(
    # Explicit Depends (not router-level) so the handler receives the previous
    # last_active_at — read before this request overwrites it to now.
    previous_last_active: datetime | None = Depends(mark_developer_active),
    clerk_org_id: str = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    org = await _get_org(clerk_org_id, db)
    return await activity.re_engagement_summary(org, previous_last_active, db)
