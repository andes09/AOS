"""Simulated developer that drives Jira tickets through a sprint in real time."""

from __future__ import annotations

import asyncio
import logging
import random
import time

from src.jira_driver import JiraDriver


logger = logging.getLogger("developer")


async def run_developer(
    dev_config: dict,
    assigned_tickets: list[str],
    sprint_duration_minutes: int,
    jira: JiraDriver,
    results: dict,
) -> None:
    """Drive one developer through their assigned tickets in real time.

    See module docstring / Stage 1 spec for behaviour. All progress is reported
    via the shared ``results`` dict so callers can ``asyncio.gather`` many devs.
    """
    if not assigned_tickets:
        return

    name = dev_config["name"]
    completion_rate = float(dev_config["completion_rate"])
    speed = float(dev_config.get("speed", 1.0)) or 1.0

    # Per-dev RNG so concurrent devs don't fight over global random state and
    # so a given dev's outcomes are reproducible across runs.
    rng = random.Random(hash(name))

    sprint_total_seconds = sprint_duration_minutes * 60
    deadline = time.monotonic() + sprint_total_seconds
    per_ticket_budget = sprint_total_seconds / len(assigned_tickets)
    pre_work_delay = per_ticket_budget * 0.2

    for key in assigned_tickets:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            results[key] = "missed"
            logger.info("%s ran out of sprint time before %s", name, key)
            continue

        # Stagger the In-Progress transitions across the sprint so all devs
        # aren't hitting Jira at the same instant.
        await asyncio.sleep(min(pre_work_delay, max(0.0, remaining - 1)))

        try:
            jira.transition_issue(key, "In Progress")
        except Exception as e:
            logger.warning("transition to In Progress failed for %s: %s", key, e)
            results[key] = "missed"
            continue

        remaining = deadline - time.monotonic()
        if remaining <= 1:
            # Out of time — leave ticket In Progress and move on.
            results[key] = "missed"
            continue

        work_duration = per_ticket_budget * (1.0 / speed) * rng.uniform(0.6, 1.0)
        work_duration = max(1.0, min(work_duration, remaining - 1))
        await asyncio.sleep(work_duration)

        if rng.random() <= completion_rate:
            try:
                jira.transition_issue(key, "Done")
                results[key] = "completed"
            except Exception as e:
                logger.warning("transition to Done failed for %s: %s", key, e)
                results[key] = "missed"
        else:
            results[key] = "missed"
            logger.info("%s left %s in In Progress (missed)", name, key)
