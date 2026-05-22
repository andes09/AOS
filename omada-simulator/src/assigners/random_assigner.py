"""Random assigner: uniform random dev per ticket.

Baseline against which Omada and Algorithm are compared. The matrix
experiment's null hypothesis is that smart assignment isn't worth the
complexity — Random is the strawman we want to beat.

Seeded by ``ctx.run_seed`` XOR ``ctx.sprint_num`` so the same archetype
across the 3 strategies in a single run faces the same picked tickets
(via BaseAssigner.select_tickets) but Random's *assignment* of those
tickets is reproducible per (run_seed, sprint).
"""

from __future__ import annotations

import random

from src.assigners.base import (
    AssignmentResult,
    BaseAssigner,
    SprintContext,
    TicketAssignment,
    empty_by_dev,
)


class RandomAssigner(BaseAssigner):
    name = "random"

    def assign(self, ctx: SprintContext) -> AssignmentResult:
        rng = random.Random(ctx.run_seed ^ hash(("random", ctx.sprint_num)))
        by_dev = empty_by_dev(ctx.developers)
        assignments: list[TicketAssignment] = []
        for ticket in ctx.picked_tickets:
            dev = rng.choice(ctx.developers)
            by_dev[dev["name"]].append(ticket["jira_key"])
            assignments.append(
                TicketAssignment(
                    jira_key=ticket["jira_key"],
                    dev_name=dev["name"],
                    source="random",
                )
            )
        return AssignmentResult(by_dev=by_dev, assignments=assignments)
