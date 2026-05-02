"""CLI entry point for the Omada simulator config layer."""

from __future__ import annotations

import argparse
import asyncio

from src.config import (
    load_environment,
    load_secrets,
    print_environment_banner,
    validate_safety,
    verify_connectivity,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="omada-simulator",
        description="Omada simulator config foundation. "
        "Use --check-env to verify a target environment.",
    )
    parser.add_argument(
        "--env",
        required=True,
        help="Environment name (local, sims, prod_blocked)",
    )
    parser.add_argument(
        "--check-env",
        action="store_true",
        help="Verify env config and connectivity",
    )
    args = parser.parse_args()

    if args.check_env:
        env = load_environment(args.env)
        validate_safety(env)
        secrets = load_secrets()
        print_environment_banner(env, secrets)
        asyncio.run(verify_connectivity(env, secrets))
        print("✓ All checks passed")
    else:
        parser.error("No command specified. Use --check-env to verify.")


if __name__ == "__main__":
    main()
