"""Algorithm assigner: load-balanced by story points.

Placeholder for a future "smart" non-Omada algorithm. Current heuristic:
biggest tickets land on the lightest dev (greedy bin-packing), respecting
``required_skill`` when at least one dev has a matching skill tag.

This is intentionally simple. The point is to fill the third slot in the
matrix so we have a non-random, non-Omada baseline to compare against.
Swap the body of ``assign`` out — keep the class shape — to plug in any
other algorithm (ML model, capacity-aware, dependency-graph-ordered, …)
without touching the rest of the harness.
"""

from __future__ import annotations

from src.assigners.base import (
    AssignmentResult,
    BaseAssigner,
    SprintContext,
    TicketAssignment,
    empty_by_dev,
)


class AlgorithmAssigner(BaseAssigner):
    name = "algorithm"

    def assign(self, ctx: SprintContext) -> AssignmentResult:
        loads: dict[str, int] = {d["name"]: 0 for d in ctx.developers}
        by_dev = empty_by_dev(ctx.developers)
        assignments: list[TicketAssignment] = []

        # Largest tickets first — put big rocks where there's slack.
        ordered = sorted(
            ctx.picked_tickets,
            key=lambda t: -int(t.get("story_points", 0)),
        )

        for ticket in ordered:
            req = ticket.get("required_skill", "any")
            eligible = [
                d for d in ctx.developers
                if req == "any" or req in (d.get("skills") or [])
            ] or ctx.developers
            chosen = min(eligible, key=lambda d: loads[d["name"]])
            loads[chosen["name"]] += int(ticket.get("story_points", 0))
            by_dev[chosen["name"]].append(ticket["jira_key"])
            assignments.append(
                TicketAssignment(
                    jira_key=ticket["jira_key"],
                    dev_name=chosen["name"],
                    source="algorithm",
                )
            )
        return AssignmentResult(by_dev=by_dev, assignments=assignments)
