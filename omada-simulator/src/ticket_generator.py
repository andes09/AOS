"""Synthetic ticket pool generation and per-sprint assignment."""

from __future__ import annotations

import random
import re
from typing import Any


TICKET_TEMPLATES: dict[str, Any] = {
    "Story": {
        "backend": [
            "Add caching layer to {service} API",
            "Refactor {module} authentication flow",
            "Implement rate limiting on {endpoint}",
            "Add pagination to {resource} endpoint",
            "Optimize {query} database query",
        ],
        "frontend": [
            "Build {component} UI component",
            "Add loading states to {page} page",
            "Implement {feature} modal",
            "Fix layout issues on {page} mobile view",
        ],
        "infra": [
            "Set up {service} monitoring alerts",
            "Update {dependency} to latest version",
            "Configure {environment} environment variables",
        ],
    },
    "Bug": [
        "{component} crashes when {condition}",
        "Missing error handling in {module}",
        "{feature} not working for {user_type} users",
        "Performance regression in {endpoint}",
    ],
    "Task": [
        "Write tests for {module}",
        "Update documentation for {feature}",
        "Code review {component} PR",
        "Set up {tool} integration",
    ],
}

PLACEHOLDER_VALUES: dict[str, list[str]] = {
    "service": ["auth", "payment", "notification", "search"],
    "module": ["user", "billing", "dashboard", "reporting"],
    "endpoint": ["/api/users", "/api/orders", "/api/search"],
    "component": ["Header", "DataTable", "Modal", "Form"],
    "page": ["dashboard", "settings", "profile", "reports"],
    "feature": ["dark mode", "export", "filtering", "sorting"],
    "resource": ["users", "orders", "products", "reports"],
    "query": ["user lookup", "order history", "search index"],
    "condition": ["empty state", "network error", "timeout"],
    "user_type": ["admin", "guest", "premium"],
    "dependency": ["React", "FastAPI", "SQLAlchemy"],
    "environment": ["staging", "production", "testing"],
    "tool": ["Sentry", "DataDog", "PagerDuty"],
}

_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")
_STORY_SKILLS = ("backend", "frontend", "infra")


def _fill_placeholders(template: str, rng: random.Random) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        choices = PLACEHOLDER_VALUES.get(key)
        if not choices:
            return match.group(0)
        return rng.choice(choices)

    return _PLACEHOLDER_RE.sub(replace, template)


def _weighted_type(distribution: dict[str, float], rng: random.Random) -> str:
    types = list(distribution.keys())
    weights = list(distribution.values())
    return rng.choices(types, weights=weights, k=1)[0]


def generate_ticket_pool(team_config: dict, *, seed: int | None = None) -> list[dict]:
    # Stage 1 calls without seed → unseeded RNG, pools vary per run.
    # Stage 2's matrix passes a seed derived from (archetype, run_idx) so
    # the 3 strategies for one (archetype, run) face the same pool.
    rng = random.Random(seed) if seed is not None else random.Random()
    pool_size = int(team_config["ticket_pool_size"])
    type_dist = team_config["ticket_distribution"]["type"]
    point_choices = team_config["ticket_distribution"]["story_points"]

    pool: list[dict] = []
    for _ in range(pool_size):
        issue_type = _weighted_type(type_dist, rng)

        if issue_type == "Story":
            skill = rng.choice(_STORY_SKILLS)
            template = rng.choice(TICKET_TEMPLATES["Story"][skill])
            required_skill = skill
        elif issue_type == "Bug":
            template = rng.choice(TICKET_TEMPLATES["Bug"])
            required_skill = "any"
        else:
            template = rng.choice(TICKET_TEMPLATES["Task"])
            required_skill = "any"

        summary = _fill_placeholders(template, rng)
        story_points = rng.choice(point_choices)

        pool.append(
            {
                "summary": summary,
                "issue_type": issue_type,
                "story_points": story_points,
                "required_skill": required_skill,
                "description": (
                    f"Auto-generated ticket for simulation. "
                    f"Skill: {required_skill}."
                ),
                "label_suffix": "sim_pool",
            }
        )

    return pool


def pick_sprint_tickets(
    pool: list[dict], developers: list[dict], sprint_num: int
) -> list[dict]:
    rng = random.Random(42 + sprint_num)
    assigned: list[dict] = []
    dev_count = len(developers)
    if dev_count == 0 or not pool:
        return assigned

    # Round-robin index per skill bucket so we can prefer-match when devs
    # declare skills, falling back to plain rotation when they don't.
    rr_index = 0

    for dev in developers:
        target = rng.randint(5, 8)
        dev_skills = dev.get("skills") or []

        picked_for_dev = 0
        scan = 0
        while picked_for_dev < target and pool and scan < len(pool):
            ticket = pool[scan]
            req = ticket["required_skill"]
            matches = (
                req == "any"
                or not dev_skills
                or req in dev_skills
            )
            if matches:
                chosen = pool.pop(scan)
                chosen["assigned_dev"] = dev["name"]
                chosen["label_suffix"] = f"sim_{dev['name']}"
                assigned.append(chosen)
                picked_for_dev += 1
                # Don't advance scan; next ticket shifts into this index.
            else:
                scan += 1

        # If skill-strict matching left this dev short, top up round-robin
        # so sprints don't shrink just because the pool lacks their skill.
        while picked_for_dev < target and pool:
            chosen = pool.pop(rr_index % len(pool))
            chosen["assigned_dev"] = dev["name"]
            chosen["label_suffix"] = f"sim_{dev['name']}"
            assigned.append(chosen)
            picked_for_dev += 1
            rr_index += 1

    return assigned
