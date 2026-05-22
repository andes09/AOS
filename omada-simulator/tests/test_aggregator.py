"""Tests for the stage-2 multi-run aggregator."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from src.aggregator import CSV_COLUMNS, aggregate


# ---------- Fixture helpers ----------


def _make_sim_results(
    archetype: str,
    strategy: str,
    *,
    committed: int = 10,
    completed: int = 7,
    spillover: int = 3,
    plan_ok: bool = True,
    push_ok: bool = True,
    retro_ok: bool = True,
    sync_ok: bool = True,
    n_sprints: int = 2,
) -> dict:
    sprints = []
    for n in range(1, n_sprints + 1):
        sprints.append({
            "sprint_num": n,
            "jira_sprint_id": 100 + n,
            "committed": committed,
            "completed": completed,
            "spillover": spillover,
            "sync_ok": sync_ok,
            "plan_ok": plan_ok,
            "push_ok": push_ok,
            "retro_ok": retro_ok,
            "health_ok": True,
            "deps_ok": True,
            "features_ok": True,
            "ticket_results": {f"FAKE-{i}": "completed" for i in range(committed)},
        })
    return {
        "env": "local",
        "team": f"{archetype} × {strategy}",
        "archetype": archetype,
        "strategy": strategy,
        "project_key": f"SIM_{archetype[:3].upper()}_{strategy[:4].upper()}",
        "sprint_length_minutes": 1,
        "total_sprints": n_sprints,
        "omada_team_id": None,
        "run_seed": 1234567,
        "sprints": sprints,
        "completed_at": "2026-05-18T00:00:00+00:00",
    }


def _write_team(
    base_output: Path,
    run_idx: int,
    archetype: str,
    strategy: str,
    sim_results: dict,
) -> Path:
    run_dir = base_output / f"run_{run_idx:03d}"
    team_dir = run_dir / f"{archetype}_{strategy}"
    team_dir.mkdir(parents=True, exist_ok=True)
    (team_dir / "simulation_results.json").write_text(json.dumps(sim_results))
    return team_dir


def _build_standard_tree(base_output: Path) -> None:
    """2 runs × 1 archetype (balanced) × 3 strategies × 2 sprints — the
    fixture the spec asks for."""
    for run_idx in (1, 2):
        for strategy in ("random", "omada", "algorithm"):
            sim = _make_sim_results(
                "balanced", strategy,
                committed=10, completed=7, spillover=3, n_sprints=2,
            )
            _write_team(base_output, run_idx, "balanced", strategy, sim)


# ---------- Tests ----------


def test_aggregate_returns_three_cells_for_single_archetype(tmp_path: Path):
    _build_standard_tree(tmp_path)
    summary = aggregate(tmp_path)
    assert len(summary["cells"]) == 3
    strategies = {c["strategy"] for c in summary["cells"]}
    assert strategies == {"random", "omada", "algorithm"}
    for cell in summary["cells"]:
        assert cell["archetype"] == "balanced"
        assert cell["runs"] == 2
        assert cell["sprints"] == 4  # 2 runs × 2 sprints


def test_summary_csv_has_correct_header_and_row_count(tmp_path: Path):
    _build_standard_tree(tmp_path)
    aggregate(tmp_path)
    csv_path = tmp_path / "aggregate" / "summary.csv"
    assert csv_path.exists()
    with csv_path.open() as f:
        reader = csv.reader(f)
        rows = list(reader)
    assert rows[0] == CSV_COLUMNS
    # 3 data rows (one per strategy)
    assert len(rows) == 4
    # spot-check one row has the right number of cells
    assert len(rows[1]) == len(CSV_COLUMNS)


def test_summary_md_exists_and_contains_headline_section(tmp_path: Path):
    _build_standard_tree(tmp_path)
    aggregate(tmp_path)
    md_path = tmp_path / "aggregate" / "summary.md"
    assert md_path.exists()
    text = md_path.read_text()
    assert "Headline" in text or "headline" in text


def test_mean_completion_rate_computed_correctly(tmp_path: Path):
    # All sprints: committed=10, completed=7 → rate=0.7 everywhere
    _build_standard_tree(tmp_path)
    summary = aggregate(tmp_path)
    for cell in summary["cells"]:
        assert cell["mean_completion_rate"] == pytest.approx(0.7)


def test_std_completion_rate_zero_when_identical(tmp_path: Path):
    _build_standard_tree(tmp_path)
    summary = aggregate(tmp_path)
    for cell in summary["cells"]:
        assert cell["std_completion_rate"] == pytest.approx(0.0)


def test_plan_ok_pct_all_true_is_100(tmp_path: Path):
    for run_idx in (1, 2):
        sim = _make_sim_results(
            "balanced", "omada",
            plan_ok=True, push_ok=True, n_sprints=2,
        )
        _write_team(tmp_path, run_idx, "balanced", "omada", sim)
    summary = aggregate(tmp_path)
    assert len(summary["cells"]) == 1
    cell = summary["cells"][0]
    assert cell["plan_ok_pct"] == pytest.approx(100.0)
    assert cell["push_ok_pct"] == pytest.approx(100.0)


def test_plan_ok_pct_all_false_is_zero(tmp_path: Path):
    for run_idx in (1, 2):
        sim = _make_sim_results(
            "balanced", "random",
            plan_ok=False, push_ok=False, n_sprints=2,
        )
        _write_team(tmp_path, run_idx, "balanced", "random", sim)
    summary = aggregate(tmp_path)
    assert len(summary["cells"]) == 1
    cell = summary["cells"][0]
    assert cell["plan_ok_pct"] == pytest.approx(0.0)
    assert cell["push_ok_pct"] == pytest.approx(0.0)


def test_empty_input_returns_empty_cells_and_writes_friendly_md(tmp_path: Path):
    # No run_* dirs at all (just an empty base_output)
    summary = aggregate(tmp_path)
    assert summary == {"cells": []}
    md = (tmp_path / "aggregate" / "summary.md").read_text()
    assert "No runs" in md
    # CSV should still exist and contain just the header
    csv_path = tmp_path / "aggregate" / "summary.csv"
    assert csv_path.exists()
    with csv_path.open() as f:
        rows = list(csv.reader(f))
    assert rows == [CSV_COLUMNS]


def test_missing_simulation_results_increments_failed_setups(tmp_path: Path):
    # Run with one good team and one team dir missing simulation_results.json
    sim = _make_sim_results("balanced", "random", n_sprints=2)
    _write_team(tmp_path, 1, "balanced", "random", sim)

    # balanced_omada dir exists but no simulation_results.json
    missing_dir = tmp_path / "run_001" / "balanced_omada"
    missing_dir.mkdir(parents=True)

    summary = aggregate(tmp_path)
    cells_by_strat = {c["strategy"]: c for c in summary["cells"]}
    # Both cells should be present
    assert set(cells_by_strat.keys()) == {"random", "omada"}
    # The good one
    assert cells_by_strat["random"]["n_failed_setups"] == 0
    assert cells_by_strat["random"]["runs"] == 1
    # The bad one
    assert cells_by_strat["omada"]["n_failed_setups"] == 1
    assert cells_by_strat["omada"]["runs"] == 0
    assert cells_by_strat["omada"]["sprints"] == 0


def test_empty_sprints_list_counts_as_failed_setup(tmp_path: Path):
    """A simulation_results.json with sprints=[] should be treated as failed
    (setup ran but produced nothing usable)."""
    sim = _make_sim_results("balanced", "random", n_sprints=1)
    sim["sprints"] = []
    _write_team(tmp_path, 1, "balanced", "random", sim)
    summary = aggregate(tmp_path)
    assert len(summary["cells"]) == 1
    assert summary["cells"][0]["n_failed_setups"] == 1


def test_csv_rounds_floats_to_four_decimals(tmp_path: Path):
    # 7/13 = 0.538461... — easy to see truncation
    sim = _make_sim_results(
        "balanced", "random",
        committed=13, completed=7, n_sprints=1,
    )
    _write_team(tmp_path, 1, "balanced", "random", sim)
    aggregate(tmp_path)
    with (tmp_path / "aggregate" / "summary.csv").open() as f:
        rows = list(csv.DictReader(f))
    rate = rows[0]["mean_completion_rate"]
    # Should be 0.5385 exactly (4 decimals)
    assert rate == "0.5385"
