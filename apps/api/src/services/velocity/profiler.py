# apps/api/src/services/velocity/profiler.py
from collections import defaultdict
from .schemas import TicketRecord, VelocityProfile


class VelocityProfiler:
    """Builds per-developer velocity profiles from historical ticket data."""

    def profile(self, tickets: list[TicketRecord]) -> list[VelocityProfile]:
        """
        Returns one VelocityProfile per (developer, ticket_type, domain) combination.
        Points within the same sprint are summed before averaging across sprints.
        """
        # Step 1: sum points per (dev, type, domain, sprint)
        sprint_points: dict[tuple, float] = defaultdict(float)
        for t in tickets:
            key = (t.developer_id, t.ticket_type, t.domain, t.sprint_id)
            sprint_points[key] += t.story_points

        # Step 2: collect per-sprint totals grouped by (dev, type, domain)
        group_sprints: dict[tuple, list[float]] = defaultdict(list)
        for (dev, ttype, domain, _sprint), pts in sprint_points.items():
            group_sprints[(dev, ttype, domain)].append(pts)

        # Step 3: average across sprints
        return [
            VelocityProfile(
                developer_id=dev,
                ticket_type=ttype,
                domain=domain,
                avg_points_per_sprint=sum(sprint_totals) / len(sprint_totals),
                sample_count=len(sprint_totals),
            )
            for (dev, ttype, domain), sprint_totals in group_sprints.items()
        ]

    def overall_velocity(self, developer_id: str, tickets: list[TicketRecord]) -> float:
        """
        Fallback: developer's average points/sprint across all ticket types and domains.
        Returns 0.0 if the developer has no history.
        """
        dev_tickets = [t for t in tickets if t.developer_id == developer_id]
        if not dev_tickets:
            return 0.0

        sprint_totals: dict[str, float] = defaultdict(float)
        for t in dev_tickets:
            sprint_totals[t.sprint_id] += t.story_points

        totals = list(sprint_totals.values())
        return sum(totals) / len(totals)
