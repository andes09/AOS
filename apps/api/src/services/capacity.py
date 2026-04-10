import uuid
from dataclasses import dataclass

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.developer import Developer
from src.models.team import Team
from src.models.sprint import Sprint, SprintStatus
from src.models.sprint import SprintTicket
from src.models.capacity import DeveloperCapacityOverride


SPRINT_WORKING_DAYS = 10
HOURS_PER_DAY = 7.5


@dataclass
class DeveloperEffectiveCapacity:
    developer_id: str
    display_name: str
    base_velocity: float
    meeting_overhead_pct: float
    pto_days: float
    capacity_pct: float
    effective_capacity_pts: float
    is_high_meeting_load: bool
    warning_message: str | None


async def get_team_capacity(
    team_id: str,
    sprint_id: str | None,
    db: AsyncSession,
) -> list[DeveloperEffectiveCapacity]:
    """
    For each active developer on the team:
    1. Load base_velocity from completed sprint history (avg delivered_points per sprint / active dev count)
    2. Load team.meeting_overhead_pct
    3. Load DeveloperCapacityOverride for (developer_id, sprint_id) if exists
    4. Compute effective_capacity_pts
    5. Set is_high_meeting_load if effective < base * 0.60
    Returns list sorted by display_name.
    """
    team_uuid = uuid.UUID(team_id) if isinstance(team_id, str) else team_id

    # Load team
    team_result = await db.execute(select(Team).where(Team.id == team_uuid))
    team = team_result.scalar_one_or_none()
    if not team:
        return []

    meeting_overhead_pct = team.meeting_overhead_pct or 0.0

    # Load active developers
    devs_result = await db.execute(
        select(Developer).where(
            Developer.team_id == team_uuid,
            Developer.is_active == True,
        )
    )
    developers = devs_result.scalars().all()
    if not developers:
        return []

    # Compute base velocity: average delivered_points per completed sprint, divided equally
    sprints_result = await db.execute(
        select(Sprint).where(
            Sprint.team_id == team_uuid,
            Sprint.status == SprintStatus.COMPLETED,
        ).order_by(Sprint.end_date.desc()).limit(5)
    )
    completed_sprints = sprints_result.scalars().all()

    avg_team_velocity = 0.0
    if completed_sprints:
        total_delivered = sum(s.delivered_points or 0.0 for s in completed_sprints)
        avg_team_velocity = total_delivered / len(completed_sprints)

    dev_count = len(developers)
    base_velocity_per_dev = avg_team_velocity / dev_count if dev_count > 0 else 0.0

    # Load capacity overrides for these developers
    sprint_uuid = uuid.UUID(sprint_id) if sprint_id else None
    dev_ids = [d.id for d in developers]
    overrides_query = select(DeveloperCapacityOverride).where(
        DeveloperCapacityOverride.developer_id.in_(dev_ids),
    )
    if sprint_uuid:
        overrides_query = overrides_query.where(
            DeveloperCapacityOverride.sprint_id == sprint_uuid
        )
    else:
        overrides_query = overrides_query.where(
            DeveloperCapacityOverride.sprint_id.is_(None)
        )
    overrides_result = await db.execute(overrides_query)
    overrides = {o.developer_id: o for o in overrides_result.scalars().all()}

    result = []
    for dev in sorted(developers, key=lambda d: d.name):
        override = overrides.get(dev.id)
        capacity_pct = override.capacity_pct if override and override.capacity_pct is not None else 1.0
        pto_days = override.pto_days if override and override.pto_days is not None else 0.0

        # PTO adjustment: each pto_day reduces capacity proportionally
        pto_adjustment = (pto_days / SPRINT_WORKING_DAYS) * base_velocity_per_dev

        effective = (
            base_velocity_per_dev
            * capacity_pct
            * (1 - meeting_overhead_pct)
            - pto_adjustment
        )
        effective = max(0.0, effective)

        is_high_meeting_load = effective < base_velocity_per_dev * 0.60

        warning_message = None
        if is_high_meeting_load:
            meeting_hours = meeting_overhead_pct * SPRINT_WORKING_DAYS * HOURS_PER_DAY
            effective_pct = int((effective / base_velocity_per_dev * 100)) if base_velocity_per_dev > 0 else 0
            warning_message = (
                f"{dev.name} has {meeting_hours:.0f}h of meetings — "
                f"effective capacity reduced to {effective_pct}%"
            )

        result.append(DeveloperEffectiveCapacity(
            developer_id=str(dev.id),
            display_name=dev.name,
            base_velocity=round(base_velocity_per_dev, 2),
            meeting_overhead_pct=meeting_overhead_pct,
            pto_days=pto_days,
            capacity_pct=capacity_pct,
            effective_capacity_pts=round(effective, 2),
            is_high_meeting_load=is_high_meeting_load,
            warning_message=warning_message,
        ))

    return result
