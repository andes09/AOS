"""Base assigner contract: two-phase select-then-assign.

Random and Algorithm strategies do all their work in ``assign`` before
the Jira sprint is created. The Omada strategy needs the sprint to exist
first (SprintBrain plans against a real Jira sprint), so the contract
splits work into two phases:

1. ``select_tickets`` — pop N tickets from the shared pool. Implemented
   once on ``BaseAssigner``; subclasses inherit. Same logic for all
   strategies so a fixed ``(archetype, run_idx)`` faces the same tickets.

2. ``assign(SprintContext)`` — return who gets each ticket. Subclasses
   override. For Omada, this is where /api/sprint-brain/plan is called
   and parsed.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from src.jira_driver import JiraDriver
    from src.omada_observer import OmadaObserver


@dataclass
class TicketAssignment:
    jira_key: str
    dev_name: str
    source: str  # "random" | "omada_plan" | "algorithm" | "fallback"


@dataclass
class AssignmentResult:
    by_dev: dict[str, list[str]]
    assignments: list[TicketAssignment]
    plan_used: Optional[dict] = None
    push_response: Optional[dict] = None


@dataclass
class SprintContext:
    sprint_num: int
    sprint_id: int
    committed_keys: list[str]
    picked_tickets: list[dict]
    developers: list[dict]
    jira: "JiraDriver"
    omada: "OmadaObserver"
    omada_team_id: Optional[str]
    archetype: str
    strategy: str
    run_seed: int
    output_dir: Path


class BaseAssigner:
    """Default ``select_tickets`` impl shared by all strategies.

    Pops ``sum(rng.randint(5, 8) for each dev)`` tickets from the front of
    the pool, in order. No assignment — subclasses do that in ``assign``.
    The 5-8 range matches stage-1's per-dev target (see
    ``ticket_generator.pick_sprint_tickets`` line 137) so commit sizes
    stay comparable.
    """

    name: str = "base"

    def select_tickets(
        self,
        pool: list[dict],
        developers: list[dict],
        sprint_num: int,
        *,
        rng: random.Random,
    ) -> list[dict]:
        if not developers or not pool:
            return []
        targets = [rng.randint(5, 8) for _ in developers]
        total = min(sum(targets), len(pool))
        picked: list[dict] = []
        for _ in range(total):
            picked.append(pool.pop(0))
        return picked

    def assign(self, ctx: SprintContext) -> AssignmentResult:
        raise NotImplementedError(
            f"{type(self).__name__} must override assign(SprintContext)"
        )


def empty_by_dev(developers: list[dict]) -> dict[str, list[str]]:
    """Build the standard {dev_name: []} dict that orchestrators consume."""
    return {d["name"]: [] for d in developers}
