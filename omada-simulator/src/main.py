"""CLI entry point for the Omada simulator."""

from __future__ import annotations

import argparse
import asyncio

from src.config import (
    load_environment,
    load_secrets,
    load_team,
    print_environment_banner,
    validate_safety,
    verify_connectivity,
)
from src.simulation import run_clean, run_reset, run_setup, run_simulation


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
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    cmds = [args.check_env, args.setup, args.simulate, args.reset, args.clean]
    if sum(cmds) == 0:
        parser.error(
            "Specify one of --check-env, --setup, --simulate, --reset, --clean."
        )
    if sum(cmds) > 1:
        parser.error("Specify only one command at a time.")

    if args.clean and not args.project_key:
        parser.error("--clean requires --project-key.")

    env = load_environment(args.env)
    validate_safety(env)

    # Dry-run never loads secrets, never touches the network. That's the
    # whole point — the integration-verification step in the orchestrator
    # spec runs --setup --dry-run without any creds configured.
    if args.dry_run:
        print(f"[DRY RUN] env={env.name}  team={args.team}")
        team_config = load_team(args.team)

        class _StubSecrets:
            jira_email = ""
            jira_api_token = ""

        stub = _StubSecrets()
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


if __name__ == "__main__":
    main()
