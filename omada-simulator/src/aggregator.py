"""Stage-2 multi-run aggregator.

Walks ``output/run_*/<archetype>_<strategy>/simulation_results.json``,
rolls up per-cell statistics (across runs and sprints), and writes
``output/aggregate/summary.csv`` plus ``output/aggregate/summary.md``.

Stdlib only — no pandas/numpy.
"""

from __future__ import annotations

import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Optional


# CSV column order is part of the spec — see plan §7. Do not reorder.
CSV_COLUMNS = [
    "archetype",
    "strategy",
    "runs",
    "sprints",
    "mean_completion_rate",
    "std_completion_rate",
    "mean_spillover",
    "std_spillover",
    "mean_committed",
    "mean_completed",
    "plan_ok_pct",
    "push_ok_pct",
    "retro_ok_pct",
    "sync_ok_pct",
    "n_failed_setups",
]


def _percent(flags: list[bool]) -> float:
    """100 * mean(flags), or 0.0 if list is empty."""
    if not flags:
        return 0.0
    return 100.0 * sum(1 for f in flags if f) / len(flags)


def _round(x: float, digits: int = 4) -> float:
    return round(float(x), digits)


def _stable_sort_key(cell: dict) -> tuple[str, str]:
    return (cell["archetype"], cell["strategy"])


def _load_team_results(
    team_dir: Path,
) -> Optional[dict]:
    """Return the parsed simulation_results.json, or None if missing/empty."""
    path = team_dir / "simulation_results.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    sprints = data.get("sprints") or []
    if not sprints:
        return None
    return data


def _infer_arch_strat(team_dir_name: str) -> Optional[tuple[str, str]]:
    """team_dir is named '<archetype>_<strategy>'. Strategy is one of the
    three known names; everything before the last underscore is archetype.
    Returns None if the dir name doesn't match the expected pattern.
    """
    known_strategies = ("random", "omada", "algorithm")
    for strat in known_strategies:
        suffix = "_" + strat
        if team_dir_name.endswith(suffix):
            archetype = team_dir_name[: -len(suffix)]
            if archetype:
                return archetype, strat
    return None


def _collect_records(
    base_output: Path,
) -> tuple[dict[tuple[str, str], list[dict]], dict[tuple[str, str], int]]:
    """Walk base_output / run_* / <arch>_<strat> / simulation_results.json.

    Returns:
        records: {(arch, strat): [simulation_results_dict, ...]} — one entry
            per run that produced a usable file.
        failed: {(arch, strat): n_failed_setups} — count of team dirs whose
            simulation_results.json was missing or unparsable.
    """
    records: dict[tuple[str, str], list[dict]] = defaultdict(list)
    failed: dict[tuple[str, str], int] = defaultdict(int)

    if not base_output.exists():
        return records, failed

    for run_dir in sorted(base_output.glob("run_*")):
        if not run_dir.is_dir():
            continue
        for team_dir in sorted(p for p in run_dir.iterdir() if p.is_dir()):
            parsed = _infer_arch_strat(team_dir.name)
            if parsed is None:
                # Unknown subdir (e.g. someone dropped a stray folder) —
                # silently ignore. Aggregator should never crash on
                # unexpected filesystem state.
                continue
            arch, strat = parsed
            data = _load_team_results(team_dir)
            if data is None:
                failed[(arch, strat)] += 1
                continue
            records[(arch, strat)].append(data)

    return records, failed


def _build_cell(
    archetype: str,
    strategy: str,
    run_results: list[dict],
    n_failed_setups: int,
) -> dict:
    """Aggregate one (archetype, strategy) cell across runs and sprints."""
    sprint_records: list[dict] = []
    for r in run_results:
        sprint_records.extend(r.get("sprints") or [])

    completion_rates: list[float] = []
    spillovers: list[float] = []
    committed: list[float] = []
    completed: list[float] = []
    plan_ok: list[bool] = []
    push_ok: list[bool] = []
    retro_ok: list[bool] = []
    sync_ok: list[bool] = []

    for s in sprint_records:
        c = s.get("committed") or 0
        done = s.get("completed") or 0
        # completion_rate is undefined when nothing was committed; treat as
        # 0 to keep the cell numeric. The headline diagnostic in §10 cares
        # about the across-many-sprints mean, which absorbs an occasional 0.
        rate = (done / c) if c else 0.0
        completion_rates.append(rate)
        spillovers.append(float(s.get("spillover") or 0))
        committed.append(float(c))
        completed.append(float(done))
        plan_ok.append(bool(s.get("plan_ok")))
        push_ok.append(bool(s.get("push_ok")))
        retro_ok.append(bool(s.get("retro_ok")))
        sync_ok.append(bool(s.get("sync_ok")))

    def _safe_mean(xs: list[float]) -> float:
        return statistics.mean(xs) if xs else 0.0

    def _safe_pstdev(xs: list[float]) -> float:
        # pstdev is defined for n>=1 (returns 0 for n=1, which is what we want
        # for the "single sprint produces stddev=0" behaviour the spec asks for).
        return statistics.pstdev(xs) if xs else 0.0

    return {
        "archetype": archetype,
        "strategy": strategy,
        "runs": len(run_results),
        "sprints": len(sprint_records),
        "mean_completion_rate": _safe_mean(completion_rates),
        "std_completion_rate": _safe_pstdev(completion_rates),
        "mean_spillover": _safe_mean(spillovers),
        "std_spillover": _safe_pstdev(spillovers),
        "mean_committed": _safe_mean(committed),
        "mean_completed": _safe_mean(completed),
        "plan_ok_pct": _percent(plan_ok),
        "push_ok_pct": _percent(push_ok),
        "retro_ok_pct": _percent(retro_ok),
        "sync_ok_pct": _percent(sync_ok),
        "n_failed_setups": n_failed_setups,
    }


def _format_cells(
    records: dict[tuple[str, str], list[dict]],
    failed: dict[tuple[str, str], int],
) -> list[dict]:
    """Build the sorted list of cell dicts. Includes any cell that either
    has run results OR had a failed setup."""
    keys = set(records.keys()) | set(failed.keys())
    cells = [
        _build_cell(arch, strat, records.get((arch, strat), []), failed.get((arch, strat), 0))
        for arch, strat in keys
    ]
    cells.sort(key=_stable_sort_key)
    return cells


def _write_csv(path: Path, cells: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for cell in cells:
            row = {}
            for col in CSV_COLUMNS:
                val = cell[col]
                if isinstance(val, float):
                    row[col] = _round(val, 4)
                else:
                    row[col] = val
            writer.writerow(row)


def _format_rate_pm_std(mean: float, std: float) -> str:
    return f"{mean:.2f} ± {std:.2f}"


def _md_headline_table(cells: list[dict]) -> str:
    lines = [
        "## Headline",
        "",
        "Mean completion rate per (archetype, strategy) across all runs and sprints.",
        "",
        "| archetype | strategy | runs | sprints | completion_rate |",
        "|-----------|----------|------|---------|-----------------|",
    ]
    for c in cells:
        lines.append(
            f"| {c['archetype']} | {c['strategy']} | {c['runs']} | {c['sprints']} | "
            f"{_format_rate_pm_std(c['mean_completion_rate'], c['std_completion_rate'])} |"
        )
    return "\n".join(lines)


def _md_per_archetype(cells: list[dict]) -> str:
    by_arch: dict[str, list[dict]] = defaultdict(list)
    for c in cells:
        by_arch[c["archetype"]].append(c)

    parts = ["## Per-archetype comparison", ""]
    parts.append(
        "Strategy comparison within each archetype — the "
        "'did omada beat random on struggling?' view."
    )
    parts.append("")
    for arch in sorted(by_arch.keys()):
        rows = sorted(by_arch[arch], key=lambda r: r["strategy"])
        parts.append(f"### {arch}")
        parts.append("")
        parts.append("| strategy | completion_rate | spillover | plan_ok_pct | push_ok_pct |")
        parts.append("|----------|-----------------|-----------|-------------|-------------|")
        for r in rows:
            parts.append(
                f"| {r['strategy']} | "
                f"{_format_rate_pm_std(r['mean_completion_rate'], r['std_completion_rate'])} | "
                f"{r['mean_spillover']:.2f} | "
                f"{r['plan_ok_pct']:.1f} | "
                f"{r['push_ok_pct']:.1f} |"
            )
        parts.append("")
    return "\n".join(parts).rstrip()


def _md_integration_health(cells: list[dict]) -> str:
    lines = [
        "## Integration health",
        "",
        "Percent of sprints where each integration step succeeded. "
        "Surfaces SprintBrain / Jira regressions.",
        "",
        "| archetype | strategy | plan_ok_pct | push_ok_pct | retro_ok_pct | sync_ok_pct |",
        "|-----------|----------|-------------|-------------|--------------|-------------|",
    ]
    for c in cells:
        lines.append(
            f"| {c['archetype']} | {c['strategy']} | "
            f"{c['plan_ok_pct']:.1f} | {c['push_ok_pct']:.1f} | "
            f"{c['retro_ok_pct']:.1f} | {c['sync_ok_pct']:.1f} |"
        )
    return "\n".join(lines)


def _md_notes(cells: list[dict]) -> str:
    failures = [c for c in cells if c["n_failed_setups"] > 0]
    parts = ["## Notes", ""]
    if failures:
        parts.append("Cells with failed setups (missing or empty simulation_results.json):")
        parts.append("")
        for c in failures:
            parts.append(
                f"- `{c['archetype']} × {c['strategy']}` — "
                f"{c['n_failed_setups']} failed setup(s)"
            )
        parts.append("")
    parts.append(
        "Caveat: the `omada` strategy's `plan_ok_pct` / `push_ok_pct` reflect a "
        "single shared Omada team in M2-M4; M5 makes this per-team."
    )
    return "\n".join(parts)


def _render_markdown(cells: list[dict]) -> str:
    if not cells:
        return (
            "# Stage 2 — Aggregate Summary\n\n"
            "No runs to aggregate. Run `python -m src.main --env local --stage 2 "
            "--simulate` first, then re-run `--aggregate`.\n"
        )

    sections = [
        "# Stage 2 — Aggregate Summary",
        "",
        _md_headline_table(cells),
        "",
        _md_per_archetype(cells),
        "",
        _md_integration_health(cells),
        "",
        _md_notes(cells),
        "",
    ]
    return "\n".join(sections)


def aggregate(
    base_output: Path,
    *,
    write_csv: bool = True,
    write_md: bool = True,
) -> dict:
    """Walk ``base_output / 'run_*' / '*' / 'simulation_results.json'``.

    Returns the rolled-up summary as a dict::

        {"cells": [ {archetype, strategy, runs, sprints, mean_completion_rate, ...}, ... ]}

    Writes ``summary.csv`` and ``summary.md`` into ``base_output / 'aggregate'``.
    """
    base_output = Path(base_output)
    records, failed = _collect_records(base_output)
    cells = _format_cells(records, failed)

    aggregate_dir = base_output / "aggregate"
    aggregate_dir.mkdir(parents=True, exist_ok=True)

    if write_csv:
        _write_csv(aggregate_dir / "summary.csv", cells)
    if write_md:
        (aggregate_dir / "summary.md").write_text(_render_markdown(cells))

    return {"cells": cells}
