"""Stage-2 multi-team matrix orchestration.

Drives the cartesian product of (archetype × strategy) across multiple
runs. Each cell is a separate ``TeamRun`` with its own Jira project; in
M2-M4 all cells share one Omada team (M5 unblocks true per-team Omada
teams via a new apps/api endpoint).

The orchestrator runs sequentially by default. Setting ``parallel_teams: true``
in config/stage2.yaml enables M6's parallel-by-archetype concurrency (see plan
§9 + §11 M6): archetype groups run concurrently via asyncio.gather while the
3 strategies within an archetype stay sequential (they share a Jira project
and board switch). Setup is always sequential to avoid Jira rate limits.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.assigners import make_assigner
from src.config import EnvironmentConfig, Secrets
from src.jira_driver import JiraDriver
from src.omada_observer import OmadaObserver
from src.simulation import run_team_simulation
from src.stage2_config import (
    Stage2Config,
    build_project_key,
    load_archetype,
)
from src.team_factory import materialize_team, stable_seed
from src.ticket_generator import generate_ticket_pool


logger = logging.getLogger("matrix")


@dataclass
class TeamRun:
    archetype: str
    strategy: str
    project_key: str
    team_config: dict
    output_dir: Path
    run_seed: int
    omada_team_id: Optional[str] = None       # resolved at simulate time (M5: per-team)
    board_id: Optional[int] = None            # filled by _setup_team
    ticket_pool: list[dict] = field(default_factory=list)  # filled by _setup_team


def expand_matrix(
    stage2_cfg: Stage2Config,
    run_idx: int,
    run_root: Path,
    *,
    archetype_filter: Optional[str] = None,
    strategy_filter: Optional[str] = None,
) -> list[TeamRun]:
    """Cartesian product of archetypes × strategies for one run.

    Same ``run_seed`` across the 3 strategies of one archetype (via
    ``stable_seed``) is the same-pool fairness guarantee from plan §8.

    Archetype YAMLs that don't exist yet are silently skipped so stage2.yaml
    can forward-declare all 5 archetypes while M2 only ships balanced.
    """
    runs: list[TeamRun] = []
    for arch_ref in stage2_cfg.archetypes:
        if archetype_filter and arch_ref.name != archetype_filter:
            continue
        try:
            arch_cfg = load_archetype(arch_ref.name)
        except FileNotFoundError:
            logger.warning(
                "Archetype %s has no YAML — skipping (M3 will add it)",
                arch_ref.name,
            )
            continue
        seed = stable_seed(arch_ref.name, run_idx)
        for strategy in stage2_cfg.strategies:
            if strategy_filter and strategy != strategy_filter:
                continue
            project_key = build_project_key(
                stage2_cfg.project_key, arch_ref.name, strategy
            )
            team_cfg = materialize_team(arch_cfg, strategy, run_idx)
            runs.append(
                TeamRun(
                    archetype=arch_ref.name,
                    strategy=strategy,
                    project_key=project_key,
                    team_config=team_cfg,
                    output_dir=run_root / f"{arch_ref.name}_{strategy}",
                    run_seed=seed,
                )
            )
    return runs


def _setup_team(
    env: EnvironmentConfig,
    secrets: Secrets,
    tr: TeamRun,
    *,
    dry_run: bool = False,
) -> None:
    """Create the team's Jira project and seed its ticket pool.

    Mutates ``tr`` in place — fills ``board_id`` and ``ticket_pool``.
    """
    tr.output_dir.mkdir(parents=True, exist_ok=True)

    pool = generate_ticket_pool(tr.team_config, seed=tr.run_seed)

    if dry_run:
        print(
            f"[dry-run]   {tr.project_key}: would create project + "
            f"{len(pool)} tickets"
        )
        tr.ticket_pool = pool
        tr.board_id = 0
        return

    project_name = f"Omada Sim ({tr.project_key})"

    with JiraDriver(
        env.jira.url,
        secrets.jira_email,
        secrets.jira_api_token,
        audit_log_dir=tr.output_dir,
    ) as jira:
        jira.get_or_create_project(tr.project_key, project_name)
        tr.board_id = jira.get_board_id(tr.project_key)

        # The simulator already has setup-time progress bars elsewhere;
        # keep this lightweight to avoid log spam when 15 teams set up
        # in sequence.
        for ticket in pool:
            key = jira.create_ticket(
                tr.project_key,
                ticket["summary"],
                ticket["issue_type"],
                ticket["story_points"],
                labels=[ticket.get("label_suffix", "sim_pool")],
                description=ticket.get("description", ""),
            )
            ticket["jira_key"] = key

    # M5: try to create a dedicated Omada team per cell. Falls through to
    # the M2-M4 shared-team fallback when the apps/api endpoint isn't
    # available (returns None on 403/404/network error — OmadaObserver._request
    # already swallows non-2xx and returns None per the defensive contract).
    with OmadaObserver(env.omada.api_url, audit_log_dir=tr.output_dir) as omada:
        dev_payload = [
            {"name": d["name"], "role": d.get("role", "engineer")}
            for d in tr.team_config["developers"]
        ]
        create_resp = omada.create_team(
            name=f"Sim {tr.archetype} {tr.strategy}",
            developers=dev_payload,
        )
        if create_resp and create_resp.get("teamId"):
            tr.omada_team_id = str(create_resp["teamId"])
            print(
                f"[setup]   {tr.project_key}: created Omada team {tr.omada_team_id}"
            )

            # Seed the team's candidate ticket pool directly. Bypasses
            # sync_jira_team which requires a fresh OAuth token + a running
            # Celery worker — neither of which is guaranteed during a sim
            # run. Without this, /api/sprint-brain/plan returns 422 and
            # OmadaAssigner falls back to random for every sprint.
            seed_payload = [
                {
                    "jira_issue_key": t["jira_key"],
                    "title": t.get("summary", t["jira_key"]),
                    "story_points": float(t.get("story_points", 0) or 0),
                    "ticket_type": t.get("issue_type"),
                    "labels": [t["label_suffix"]] if t.get("label_suffix") else None,
                }
                for t in pool
            ]
            seed_resp = omada.seed_tickets(tr.omada_team_id, seed_payload)
            if seed_resp:
                print(
                    f"[setup]   {tr.project_key}: seeded "
                    f"{seed_resp.get('created', 0)} new + "
                    f"{seed_resp.get('updated', 0)} updated tickets into Omada DB"
                )
            else:
                print(
                    f"[warning] {tr.project_key}: seed_tickets failed — "
                    f"SprintBrain plan will likely 422 for this cell"
                )
        else:
            # M2-M4 fallback: share the org's primary team. Logged once per
            # team so the user knows why omada metrics may look the same
            # across cells.
            print(
                f"[setup]   {tr.project_key}: Omada team creation unavailable "
                f"— sharing org primary team (per-team Omada teams need M5 apps/api)"
            )

    tr.ticket_pool = pool

    state = {
        "project_key": tr.project_key,
        "board_id": tr.board_id,
        "pool": pool,
        "ticket_keys": [t["jira_key"] for t in pool],
        "dependency_pairs": [],  # M3+ may add these
        "created_at": datetime.now(timezone.utc).isoformat(),
        "run_seed": tr.run_seed,
        "archetype": tr.archetype,
        "strategy": tr.strategy,
    }
    (tr.output_dir / "setup_state.json").write_text(
        json.dumps(state, indent=2, default=str)
    )
    print(
        f"[setup]   {tr.project_key}: {len(pool)} tickets created "
        f"(board_id={tr.board_id})"
    )


async def _simulate_team(
    env: EnvironmentConfig,
    secrets: Secrets,
    tr: TeamRun,
    *,
    dry_run: bool = False,
) -> dict:
    """Run a single team's simulation.

    Re-points Omada at the team's board before calling run_team_simulation
    so SprintBrain plans against the right project. In M2-M4 every team
    shares one Omada team id; M5 makes this per-team.
    """
    assigner = make_assigner(tr.strategy)

    if dry_run:
        print(
            f"[dry-run]   {tr.archetype} × {tr.strategy}: "
            f"would run {tr.team_config['total_sprints']} sprint(s)"
        )
        return {}

    with OmadaObserver(env.omada.api_url, audit_log_dir=tr.output_dir) as omada:
        # M5: prefer the per-team id set by _setup_team. Only fall back
        # to resolving the org's primary team (the M2-M4 path) when the
        # M5 endpoint wasn't available at setup time.
        if not tr.omada_team_id:
            resolved = omada.resolve_team_id()
            if resolved:
                tr.omada_team_id = resolved
            elif tr.strategy == "omada":
                logger.warning(
                    "omada team_id unresolved for %s — OmadaAssigner will fall "
                    "back to random",
                    tr.project_key,
                )
        if tr.board_id:
            omada.switch_board(
                tr.board_id, tr.project_key,
                team_id=tr.omada_team_id,
            )

    return await run_team_simulation(
        env, secrets, tr.team_config,
        project_key=tr.project_key,
        board_id=tr.board_id,
        ticket_pool=tr.ticket_pool,
        omada_team_id=tr.omada_team_id,
        run_seed=tr.run_seed,
        output_dir=tr.output_dir,
        assigner=assigner,
        archetype=tr.archetype,
        strategy=tr.strategy,
        dry_run=False,
    )


async def run_matrix(
    env: EnvironmentConfig,
    secrets: Secrets,
    stage2_cfg: Stage2Config,
    *,
    runs: int,
    base_output: Path,
    archetype_filter: Optional[str] = None,
    strategy_filter: Optional[str] = None,
    sprint_length_override: Optional[int] = None,
    total_sprints_override: Optional[int] = None,
    dry_run: bool = False,
) -> None:
    """Outer multi-run loop. Per run: expand matrix → setup all teams →
    simulate all teams → write matrix_meta.json.

    Simulation is sequential by default; opt in to parallel-by-archetype
    concurrency by setting ``parallel_teams: true`` in stage2.yaml (M6).
    """
    base_output.mkdir(parents=True, exist_ok=True)

    for run_idx in range(1, runs + 1):
        run_root = base_output / f"run_{run_idx:03d}"
        run_root.mkdir(parents=True, exist_ok=True)
        team_runs = expand_matrix(
            stage2_cfg, run_idx, run_root,
            archetype_filter=archetype_filter,
            strategy_filter=strategy_filter,
        )

        if not team_runs:
            raise SystemExit(
                "Matrix expanded to zero teams — check --archetype/--strategy "
                "filters and that the target archetype YAMLs exist in "
                "config/archetypes/."
            )

        for tr in team_runs:
            if sprint_length_override is not None:
                tr.team_config["sprint_length_minutes"] = sprint_length_override
            if total_sprints_override is not None:
                tr.team_config["total_sprints"] = total_sprints_override

        print(
            f"\n=== Run {run_idx}/{runs}: "
            f"{len(team_runs)} teams ({len(set(t.archetype for t in team_runs))} "
            f"archetypes × {len(set(t.strategy for t in team_runs))} strategies) ==="
        )

        meta = {
            "run_idx": run_idx,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "teams": [
                {
                    "archetype": tr.archetype,
                    "strategy": tr.strategy,
                    "project_key": tr.project_key,
                    "run_seed": tr.run_seed,
                }
                for tr in team_runs
            ],
        }

        # Setup stays sequential: creating 15 Jira projects in parallel would
        # hammer the rate limit (see plan §11 risk 3). Only simulate parallelizes.
        for tr in team_runs:
            _setup_team(env, secrets, tr, dry_run=dry_run)

        if stage2_cfg.parallel_teams:
            # Group by archetype; strategies within an archetype share a Jira
            # project (when M5 ships) and a board switch, so they must stay
            # sequential. Archetype groups run concurrently.
            groups: dict[str, list[TeamRun]] = defaultdict(list)
            for tr in team_runs:
                groups[tr.archetype].append(tr)

            async def _run_archetype_group(group: list[TeamRun]) -> None:
                for tr in group:
                    print(f"\n[simulate] {tr.archetype} × {tr.strategy}")
                    await _simulate_team(env, secrets, tr, dry_run=dry_run)

            await asyncio.gather(
                *(_run_archetype_group(g) for g in groups.values())
            )
        else:
            for tr in team_runs:
                print(f"\n[simulate] {tr.archetype} × {tr.strategy}")
                await _simulate_team(env, secrets, tr, dry_run=dry_run)

        meta["completed_at"] = datetime.now(timezone.utc).isoformat()
        (run_root / "matrix_meta.json").write_text(
            json.dumps(meta, indent=2, default=str)
        )
        print(f"\n[run {run_idx}] complete → {run_root}")
