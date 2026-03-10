# apps/api/src/services/velocity/capacity.py
from .schemas import SprintMeta, PtoEntry, MeetingOverhead, DeveloperCapacity

_HOURS_PER_DAY = 8.0


class CapacityModel:
    """Converts sprint calendar facts into per-developer availability ratios."""

    def model(
        self,
        sprint: SprintMeta,
        pto: list[PtoEntry],
        meetings: list[MeetingOverhead],
    ) -> list[DeveloperCapacity]:
        """
        Returns DeveloperCapacity for each member in sprint.team_members.
        availability_ratio is the fraction of the sprint the developer is present
        after deducting PTO and meeting time.
        """
        pto_map = {p.developer_id: p.days_off for p in pto}
        meeting_map = {m.developer_id: m.hours_per_day for m in meetings}
        total = sprint.total_working_days

        results = []
        for dev_id in sprint.team_members:
            days_off = pto_map.get(dev_id, 0.0)
            # Convert recurring meeting hours into equivalent full days lost
            meeting_days = (meeting_map.get(dev_id, 0.0) * total) / _HOURS_PER_DAY
            available = round(max(0.0, total - days_off - meeting_days), 2)
            ratio = round(available / total, 4)
            results.append(
                DeveloperCapacity(
                    developer_id=dev_id,
                    available_days=available,
                    availability_ratio=ratio,
                )
            )
        return results
