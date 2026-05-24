"""Tests for src/matrix.py — stage-2 matrix expansion + fairness invariants.

Doesn't exercise run_matrix end-to-end (that needs Jira + Omada running);
focuses on expand_matrix which is pure and where the comparison-fairness
invariant lives.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.jira_driver import AUDIT_LOG_PATH as JIRA_AUDIT_LOG_PATH
from src.jira_driver import JiraDriver
from src.matrix import TeamRun, expand_matrix
from src.omada_observer import AUDIT_LOG_PATH as OMADA_AUDIT_LOG_PATH
from src.omada_observer import OmadaObserver
from src.stage2_config import load_stage2_config


# ---------- expand_matrix ----------

def test_expand_matrix_full_returns_fifteen_teams(tmp_path: Path) -> None:
    """M3 ships all 5 archetype YAMLs. Without filters, expand_matrix should
    return 15 teams (5 archetypes × 3 strategies)."""
    cfg = load_stage2_config()
    runs = expand_matrix(cfg, run_idx=1, run_root=tmp_path)
    assert len(runs) == 15
    assert {tr.archetype for tr in runs} == {
        "balanced", "small", "large", "struggling", "meeting_heavy",
    }
    assert {tr.strategy for tr in runs} == {"random", "omada", "algorithm"}


def test_expand_matrix_project_keys_are_unique(tmp_path: Path) -> None:
    cfg = load_stage2_config()
    runs = expand_matrix(cfg, run_idx=1, run_root=tmp_path)
    keys = [tr.project_key for tr in runs]
    assert len(keys) == len(set(keys)), f"Duplicate project keys: {keys}"
    for k in keys:
        assert k.startswith("SIM_"), f"Project key {k!r} must start with SIM_"


def test_expand_matrix_project_key_format(tmp_path: Path) -> None:
    cfg = load_stage2_config()
    runs = expand_matrix(cfg, run_idx=1, run_root=tmp_path)
    expected = {
        "SIM_BAL_RAND", "SIM_BAL_OMAD", "SIM_BAL_ALGO",
        "SIM_SML_RAND", "SIM_SML_OMAD", "SIM_SML_ALGO",
        "SIM_LRG_RAND", "SIM_LRG_OMAD", "SIM_LRG_ALGO",
        "SIM_STR_RAND", "SIM_STR_OMAD", "SIM_STR_ALGO",
        "SIM_MTG_RAND", "SIM_MTG_OMAD", "SIM_MTG_ALGO",
    }
    assert {tr.project_key for tr in runs} == expected


def test_expand_matrix_shares_seed_across_strategies(tmp_path: Path) -> None:
    """Same-pool fairness (plan §8): the 3 strategies for one archetype in
    one run must share run_seed so they face identical ticket pools."""
    cfg = load_stage2_config()
    runs = expand_matrix(cfg, run_idx=1, run_root=tmp_path)
    bal_seeds = {tr.run_seed for tr in runs if tr.archetype == "balanced"}
    assert len(bal_seeds) == 1, (
        f"Strategies for balanced should share one seed; got {bal_seeds}"
    )


def test_expand_matrix_seed_changes_across_runs(tmp_path: Path) -> None:
    """Different run_idx → different seed so multi-run produces varied pools."""
    cfg = load_stage2_config()
    runs1 = expand_matrix(cfg, run_idx=1, run_root=tmp_path)
    runs2 = expand_matrix(cfg, run_idx=2, run_root=tmp_path)
    seed1 = runs1[0].run_seed
    seed2 = runs2[0].run_seed
    assert seed1 != seed2


def test_expand_matrix_archetype_filter(tmp_path: Path) -> None:
    cfg = load_stage2_config()
    runs = expand_matrix(
        cfg, run_idx=1, run_root=tmp_path, archetype_filter="balanced"
    )
    assert len(runs) == 3
    assert all(tr.archetype == "balanced" for tr in runs)


def test_expand_matrix_strategy_filter(tmp_path: Path) -> None:
    cfg = load_stage2_config()
    runs = expand_matrix(
        cfg, run_idx=1, run_root=tmp_path, strategy_filter="omada"
    )
    # All 5 archetypes ship; filtered to one strategy → 5 teams.
    assert len(runs) == 5
    assert all(tr.strategy == "omada" for tr in runs)
    assert {tr.project_key for tr in runs} == {
        "SIM_BAL_OMAD", "SIM_SML_OMAD", "SIM_LRG_OMAD",
        "SIM_STR_OMAD", "SIM_MTG_OMAD",
    }


def test_expand_matrix_both_filters(tmp_path: Path) -> None:
    cfg = load_stage2_config()
    runs = expand_matrix(
        cfg, run_idx=1, run_root=tmp_path,
        archetype_filter="balanced", strategy_filter="random",
    )
    assert len(runs) == 1
    assert runs[0].project_key == "SIM_BAL_RAND"


def test_expand_matrix_unknown_filter_returns_empty(tmp_path: Path) -> None:
    cfg = load_stage2_config()
    runs = expand_matrix(
        cfg, run_idx=1, run_root=tmp_path, archetype_filter="nonexistent"
    )
    assert runs == []


def test_team_run_output_dir_layout(tmp_path: Path) -> None:
    cfg = load_stage2_config()
    runs = expand_matrix(cfg, run_idx=1, run_root=tmp_path)
    for tr in runs:
        # output_dir is run_root / "{archetype}_{strategy}"
        assert tr.output_dir.parent == tmp_path
        assert tr.output_dir.name == f"{tr.archetype}_{tr.strategy}"


def test_team_run_team_config_carries_archetype_strategy(tmp_path: Path) -> None:
    """team_factory.materialize_team should stamp archetype+strategy onto
    the materialized team_config so downstream code can identify the cell."""
    cfg = load_stage2_config()
    runs = expand_matrix(cfg, run_idx=1, run_root=tmp_path)
    for tr in runs:
        assert tr.team_config["archetype"] == tr.archetype
        assert tr.team_config["strategy"] == tr.strategy
        assert tr.team_config["run_seed"] == tr.run_seed
        # Archetype YAML fields preserved (dev count varies by archetype:
        # small=2, large=8, others=4).
        assert "developers" in tr.team_config
        expected_devs = {
            "small": 2, "large": 8,
            "balanced": 4, "struggling": 4, "meeting_heavy": 4,
        }[tr.archetype]
        assert len(tr.team_config["developers"]) == expected_devs


# ---------- M6: parallel-by-archetype + per-team audit dirs ----------

def test_parallel_teams_default_false() -> None:
    """Stage-2 default reverted to sequential after parallel mode caused
    Jira/Anthropic API contention (5 archetypes hammering same endpoints
    simultaneously) that disproportionately hurt the omada strategy and
    distorted the head-to-head comparison."""
    cfg = load_stage2_config()
    assert cfg.parallel_teams is False


def test_jira_driver_audit_log_dir_override(tmp_path: Path) -> None:
    """Per-team audit log dir (M6): driver should write jira_audit.log into
    the override dir, not the shared module-level output/jira_audit.log."""
    driver = JiraDriver(
        "https://example.atlassian.net",
        "user@example.com",
        "token",
        audit_log_dir=tmp_path,
    )
    # Resolved path must live under the override, not the default.
    assert driver._audit_log_path == tmp_path / "jira_audit.log"
    assert driver._audit_log_path != JIRA_AUDIT_LOG_PATH

    # Trigger a write via the internal _audit helper (no network needed).
    driver._audit("GET", "/rest/api/3/myself", 200, 12)
    assert (tmp_path / "jira_audit.log").exists()


def test_jira_driver_audit_log_default_path() -> None:
    """Backward-compat: constructing without audit_log_dir must keep writing
    to the module-level shared path (stage-1 callers depend on this)."""
    driver = JiraDriver(
        "https://example.atlassian.net", "user@example.com", "token"
    )
    assert driver._audit_log_path == JIRA_AUDIT_LOG_PATH


def test_omada_observer_audit_log_dir_override(tmp_path: Path) -> None:
    """Per-team audit log dir (M6): observer should write omada_audit.log
    into the override dir, not the shared module-level path."""
    observer = OmadaObserver(
        "http://localhost:8000", audit_log_dir=tmp_path
    )
    assert observer._audit_log_path == tmp_path / "omada_audit.log"
    assert observer._audit_log_path != OMADA_AUDIT_LOG_PATH

    observer._log("GET", "/api/me", "200", '{"user_id":"u_x"}')
    assert (tmp_path / "omada_audit.log").exists()


def test_omada_observer_audit_log_default_path() -> None:
    """Backward-compat: constructing without audit_log_dir keeps the shared
    module-level path so stage-1 callers (run_simulation) are unaffected."""
    observer = OmadaObserver("http://localhost:8000")
    assert observer._audit_log_path == OMADA_AUDIT_LOG_PATH
