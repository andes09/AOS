"""Materialize an archetype + strategy + run_idx into a team_config dict.

Stage-2 runs cross-product (archetype × strategy × run_idx). For same-pool
fairness (plan §8), all three strategies within one (archetype, run_idx)
share the same `run_seed` so they face an identical generated ticket pool.
"""

from __future__ import annotations

import copy
import hashlib
from typing import Optional


def stable_seed(archetype: str, run_idx: int) -> int:
    """Deterministic 31-bit int derived from (archetype, run_idx).

    Same archetype + run_idx always yields the same seed, regardless of
    strategy — that's the lever for same-pool fairness.
    """
    h = hashlib.sha256(f"{archetype}|{run_idx}".encode()).digest()
    return int.from_bytes(h[:4], "big") & 0x7FFFFFFF


def materialize_team(
    archetype_cfg: dict,
    strategy: str,
    run_idx: int,
    *,
    omada_team_id: Optional[str] = None,
) -> dict:
    """Return a team_config dict: archetype fields + stage-2 additions.

    The result is a superset of stage-1 team_config — same keys
    (developers, sprint_length_minutes, total_sprints, ticket_pool_size,
    ticket_distribution, dependency_density) plus stage-2 metadata
    (team_name, archetype, strategy, run_seed, omada_team_id).

    Deep-copies the archetype config so callers can safely reuse the dict
    across the three strategies in one run without bleed-through.
    """
    team = copy.deepcopy(archetype_cfg)
    archetype_name = archetype_cfg["name"]
    team["team_name"] = f"{archetype_name} × {strategy}"
    team["archetype"] = archetype_name
    team["strategy"] = strategy
    team["run_seed"] = stable_seed(archetype_name, run_idx)
    team["omada_team_id"] = omada_team_id
    return team
