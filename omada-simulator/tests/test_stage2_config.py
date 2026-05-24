"""Tests for stage-2 matrix config loading and team materialization."""

from __future__ import annotations

import pytest

from src.stage2_config import (
    build_project_key,
    load_archetype,
    load_stage2_config,
)
from src.team_factory import materialize_team, stable_seed


def test_load_stage2_config_shape():
    cfg = load_stage2_config()
    assert len(cfg.archetypes) == 5
    assert {a.name for a in cfg.archetypes} == {
        "balanced",
        "small",
        "large",
        "struggling",
        "meeting_heavy",
    }
    assert cfg.strategies == ["random", "omada", "algorithm"]
    assert cfg.parallel_teams is False
    assert cfg.defaults.runs == 1
    assert cfg.project_key.prefix == "SIM"


def test_load_archetype_balanced():
    arc = load_archetype("balanced")
    assert arc["name"] == "balanced"
    assert isinstance(arc["developers"], list)
    assert len(arc["developers"]) == 4


def test_load_archetype_missing_raises():
    with pytest.raises(FileNotFoundError) as exc:
        load_archetype("does_not_exist")
    # The "Available archetypes" hint matches the load_team convention.
    assert "Available archetypes" in str(exc.value)


def test_build_project_key_happy_path():
    cfg = load_stage2_config()
    assert build_project_key(cfg.project_key, "balanced", "random") == "SIM_BAL_RAND"
    assert (
        build_project_key(cfg.project_key, "meeting_heavy", "algorithm")
        == "SIM_MTG_ALGO"
    )


def test_build_project_key_unknown_strategy_raises():
    cfg = load_stage2_config()
    with pytest.raises(ValueError):
        build_project_key(cfg.project_key, "balanced", "unknown_strategy")


def test_build_project_key_unknown_archetype_raises():
    cfg = load_stage2_config()
    with pytest.raises(ValueError):
        build_project_key(cfg.project_key, "not_an_archetype", "random")


def test_stable_seed_is_deterministic():
    assert stable_seed("balanced", 1) == stable_seed("balanced", 1)


def test_stable_seed_varies_with_run_idx():
    assert stable_seed("balanced", 1) != stable_seed("balanced", 2)


def test_stable_seed_varies_with_archetype():
    assert stable_seed("balanced", 1) != stable_seed("small", 1)


def test_stable_seed_fits_in_31_bits():
    assert 0 <= stable_seed("balanced", 1) < 2**31


def test_materialize_team_shape():
    arc = load_archetype("balanced")
    team = materialize_team(arc, "random", 1)
    assert team["archetype"] == "balanced"
    assert team["strategy"] == "random"
    assert team["team_name"] == "balanced × random"
    assert isinstance(team["run_seed"], int)
    # Stage-1 fields preserved from the archetype.
    assert team["developers"] == arc["developers"]
    assert team["sprint_length_minutes"] == arc["sprint_length_minutes"]
    assert team["total_sprints"] == arc["total_sprints"]
    assert team["ticket_pool_size"] == arc["ticket_pool_size"]
    assert team["ticket_distribution"] == arc["ticket_distribution"]
    assert team["dependency_density"] == arc["dependency_density"]
    assert team["omada_team_id"] is None


def test_materialize_team_passes_omada_team_id():
    arc = load_archetype("balanced")
    team = materialize_team(arc, "omada", 0, omada_team_id="uuid-123")
    assert team["omada_team_id"] == "uuid-123"


def test_materialize_team_does_not_mutate_input():
    arc = load_archetype("balanced")
    original_keys = set(arc.keys())
    _ = materialize_team(arc, "random", 1)
    assert set(arc.keys()) == original_keys
    assert "team_name" not in arc
    assert "strategy" not in arc


def test_materialize_team_same_seed_across_strategies():
    """Same-pool fairness: same (archetype, run_idx) -> same seed across strategies."""
    arc = load_archetype("balanced")
    a = materialize_team(arc, "random", 7)
    b = materialize_team(arc, "omada", 7)
    c = materialize_team(arc, "algorithm", 7)
    assert a["run_seed"] == b["run_seed"] == c["run_seed"]
