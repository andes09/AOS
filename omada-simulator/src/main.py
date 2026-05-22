"""CLI entry point for the Omada simulator."""

from __future__ import annotations

import argparse
import asyncio

from pathlib import Path

from src.config import (
    load_environment,
    load_secrets,
    load_team,
    print_environment_banner,
    validate_safety,
    verify_connectivity,
)
from src.simulation import (
    run_clean,
    run_reset,
    run_reset_sprints,
    run_setup,
    run_simulation,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="omada-simulator",
        description=(
            "Omada Stage 1 simulator. Use --check-env to verify a target "
            "environment, --setup to create the Jira SIM project + ticket pool, "
            "--simulate to run 3 sprints, --reset to tear down."
        ),
    )
    parser.add_argument(
        "--env",
        required=True,
        help="Environment name (e.g. local, sims, prod_blocked)",
    )
    parser.add_argument(
        "--team",
        default="stage1_team",
        help="Team config name in config/teams/ (default: stage1_team)",
    )
    parser.add_argument(
        "--check-env",
        action="store_true",
        help="Validate safety, then probe Omada /health and /api/me.",
    )
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Create the Jira SIM project, ticket pool, and dependency links.",
    )
    parser.add_argument(
        "--simulate",
        action="store_true",
        help="Run the 3-sprint simulation (requires --setup first).",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete the Jira SIM project and remove setup_state.json. "
             "Requires --confirm.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Full reset: delete the Jira SIM project, remove all "
             "output/*.json files, and truncate audit logs. Requires "
             "--project-key.",
    )
    parser.add_argument(
        "--reset-sprints",
        action="store_true",
        help="Reset sprints/ticket states while PRESERVING the Jira "
             "project, board, and ticket pool. Closes any active sprints, "
             "moves tickets back to backlog, resets statuses to 'To Do', "
             "deletes per-sprint output JSONs, truncates audit logs. "
             "Requires --project-key.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would happen without making API calls. "
             "Works with --setup, --simulate, --reset.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing setup_state.json on --setup.",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Required to actually delete the SIM project on --reset.",
    )
    parser.add_argument(
        "--project-key",
        default=None,
        help="Override the SIM project key (must start with SIM). "
             "Useful when the default SIM key is still in Jira's "
             "post-deletion reservation window.",
    )

    # ----- Stage 2 flags -----
    parser.add_argument(
        "--stage",
        type=int,
        choices=[1, 2],
        default=1,
        help="Simulator stage. 1 = single team (default), 2 = matrix.",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=1,
        help="Stage 2 only: how many full matrix runs to execute.",
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Stage 2 only: 1 archetype (balanced) x 3 strategies x 1 "
             "sprint x 1 run. Fastest end-to-end validation.",
    )
    parser.add_argument(
        "--aggregate",
        action="store_true",
        help="Stage 2 only: aggregate output/run_*/ into output/aggregate/ "
             "(implemented in M3).",
    )
    parser.add_argument(
        "--archetype",
        default=None,
        help="Stage 2 only: restrict matrix to one archetype name.",
    )
    parser.add_argument(
        "--strategy",
        default=None,
        choices=["random", "omada", "algorithm"],
        help="Stage 2 only: restrict matrix to one strategy.",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    cmds = [
        args.check_env,
        args.setup,
        args.simulate,
        args.reset,
        args.clean,
        args.reset_sprints,
        args.smoke_test,
        args.aggregate,
    ]
    if sum(cmds) == 0:
        parser.error(
            "Specify one of --check-env, --setup, --simulate, --reset, "
            "--clean, --reset-sprints, --smoke-test, --aggregate."
        )
    if sum(cmds) > 1:
        parser.error("Specify only one command at a time.")

    # Stage-2-only flags should never be used with --stage 1.
    if args.stage == 1 and (args.smoke_test or args.aggregate
                            or args.archetype or args.strategy):
        parser.error(
            "--smoke-test, --aggregate, --archetype, --strategy require "
            "--stage 2."
        )
    if args.stage == 2:
        if args.setup or args.reset or args.reset_sprints or args.clean:
            parser.error(
                f"--stage 2 only supports --simulate, --smoke-test, "
                f"--aggregate, --check-env. Setup/reset are handled "
                f"inside --simulate for the matrix."
            )

    if args.clean and not args.project_key:
        parser.error("--clean requires --project-key.")
    if args.reset_sprints and not args.project_key:
        parser.error("--reset-sprints requires --project-key.")

    env = load_environment(args.env)
    validate_safety(env)

    # Dry-run never loads secrets, never touches the network. That's the
    # whole point — the integration-verification step in the orchestrator
    # spec runs --setup --dry-run without any creds configured.
    if args.dry_run:
        print(f"[DRY RUN] env={env.name}")

        class _StubSecrets:
            jira_email = ""
            jira_api_token = ""

        stub = _StubSecrets()

        if args.stage == 2:
            _run_stage2(env, stub, args, dry_run=True)
            return

        print(f"[DRY RUN] team={args.team}")
        team_config = load_team(args.team)
        if args.setup:
            asyncio.run(
                run_setup(
                    env, stub, team_config,
                    force=args.force, dry_run=True,
                    project_key_override=args.project_key,
                )
            )
        elif args.simulate:
            asyncio.run(
                run_simulation(
                    env, stub, team_config,
                    dry_run=True,
                    project_key_override=args.project_key,
                )
            )
        elif args.reset:
            asyncio.run(
                run_reset(
                    env, stub,
                    confirm=args.confirm, dry_run=True,
                    project_key_override=args.project_key,
                )
            )
        elif args.clean:
            asyncio.run(
                run_clean(
                    env, stub,
                    project_key_override=args.project_key,
                    dry_run=True,
                )
            )
        elif args.reset_sprints:
            asyncio.run(
                run_reset_sprints(
                    env, stub,
                    project_key_override=args.project_key,
                    dry_run=True,
                )
            )
        else:
            parser.error("--dry-run is not supported with --check-env.")
        return

    secrets = load_secrets()
    print_environment_banner(env, secrets)

    # No Omada-side secrets needed: the simulator runs against a local API
    # with clerk_auth=false, so /api/me succeeds without any auth header.

    if args.check_env:
        asyncio.run(verify_connectivity(env))
        print("✓ All checks passed")
        return

    if args.stage == 2:
        _run_stage2(env, secrets, args)
        return

    team_config = load_team(args.team)

    if args.setup:
        asyncio.run(run_setup(
            env, secrets, team_config,
            force=args.force,
            project_key_override=args.project_key,
        ))
    elif args.simulate:
        asyncio.run(run_simulation(
            env, secrets, team_config,
            project_key_override=args.project_key,
        ))
    elif args.reset:
        asyncio.run(run_reset(
            env, secrets,
            confirm=args.confirm,
            project_key_override=args.project_key,
        ))
    elif args.clean:
        asyncio.run(run_clean(
            env, secrets,
            project_key_override=args.project_key,
        ))
    elif args.reset_sprints:
        asyncio.run(run_reset_sprints(
            env, secrets,
            project_key_override=args.project_key,
        ))


def _run_stage2(env, secrets, args, *, dry_run: bool = False) -> None:
    """Stage-2 dispatch — routes --simulate / --smoke-test / --aggregate
    through src.matrix."""
    from src.matrix import run_matrix
    from src.stage2_config import load_stage2_config

    stage2_cfg = load_stage2_config()
    base_output = Path(__file__).resolve().parent.parent / "output"

    if args.aggregate:
        from src.aggregator import aggregate

        if not base_output.exists() or not any(base_output.glob("run_*")):
            print(
                f"[aggregate] no run_* subdirs under {base_output} — "
                "nothing to aggregate. Run --simulate first."
            )
            return

        summary = aggregate(base_output)
        cells = summary.get("cells", [])
        print(f"\n[aggregate] {len(cells)} cells aggregated")
        print(f"  CSV: {base_output}/aggregate/summary.csv")
        print(f"  MD:  {base_output}/aggregate/summary.md")
        print(f"  HTML: {base_output}/aggregate/summary.html")
        print(f"  (run `.venv/bin/python -m src.report_html` to render)")
        return

    if args.smoke_test:
        # 1 archetype x 3 strategies x 1 sprint x 1 run — the M2 success signal.
        print("=== Stage 2 smoke test ===")
        print("1 archetype (balanced) x 3 strategies x 1 sprint x 1 run")
        asyncio.run(run_matrix(
            env, secrets, stage2_cfg,
            runs=1,
            base_output=base_output,
            archetype_filter="balanced",
            strategy_filter=None,
            sprint_length_override=1,
            total_sprints_override=1,
            dry_run=dry_run,
        ))
        if not dry_run:
            print("\n✓ Smoke test complete")
            print(
                f"  Inspect: {base_output}/run_001/"
                "balanced_*/simulation_results.json"
            )
        return

    if args.simulate:
        asyncio.run(run_matrix(
            env, secrets, stage2_cfg,
            runs=args.runs,
            base_output=base_output,
            archetype_filter=args.archetype,
            strategy_filter=args.strategy,
            dry_run=dry_run,
        ))
        return

    raise SystemExit(
        "Stage 2 needs one of --simulate, --smoke-test, --aggregate."
    )


if __name__ == "__main__":
    main()
