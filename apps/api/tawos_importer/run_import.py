"""CLI for the TAWOS importer.

Usage (from apps/api/):
    python -m tawos_importer.run_import --list
    python -m tawos_importer.run_import --project APACHE-KAFKA
    python -m tawos_importer.run_import --project APACHE-KAFKA --limit-issues 500
    python -m tawos_importer.run_import --all-small         # <1000 issues per project
    python -m tawos_importer.run_import --all
    python -m tawos_importer.run_import --reset --confirm

Safety: every subcommand that writes to Postgres first calls
`assert_not_production(DATABASE_URL)`. The hostname pattern list is in config.py.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Iterable

from sqlalchemy import delete, select, text

from src.config import settings
from src.database import AsyncSessionLocal
from src.models import Organization
from tawos_importer.config import assert_not_production, setup_logging
from tawos_importer.importer import import_project
from tawos_importer.source_db import tawos_connection
from tawos_importer.tawos_queries import list_projects

log = setup_logging()

SMALL_PROJECT_CEILING = 1000


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #

def cmd_list() -> int:
    """Print TAWOS projects sorted by issue count. Read-only — no safety guard."""
    with tawos_connection() as conn:
        projects = list_projects(conn)
    print(f"{'Key':<30} {'Name':<40} {'Issues':>10}")
    print("-" * 82)
    for p in projects:
        print(f"{(p.get('Key') or ''):<30} {(p.get('Name') or ''):<40} {p.get('issue_count', 0):>10,}")
    print(f"\n{len(projects)} projects, {sum(p.get('issue_count', 0) for p in projects):,} total issues")
    return 0


async def cmd_project(identifier: str, limit_issues: int | None) -> int:
    assert_not_production(settings.database_url)
    # If the CLI passed an all-digit string, treat it as the numeric Project.ID.
    project_id: int | str = int(identifier) if identifier.isdigit() else identifier
    summary = await import_project(project_id, limit_issues=limit_issues)
    print(summary.as_log_line())
    return 0


async def cmd_all_small() -> int:
    assert_not_production(settings.database_url)
    with tawos_connection() as conn:
        projects = list_projects(conn)
    targets = [p for p in projects if (p.get("issue_count") or 0) < SMALL_PROJECT_CEILING]
    log.info("importing %d small projects (<%d issues each)", len(targets), SMALL_PROJECT_CEILING)
    return await _import_many(targets)


async def cmd_all() -> int:
    assert_not_production(settings.database_url)
    with tawos_connection() as conn:
        projects = list_projects(conn)
    log.info("importing all %d projects (this can take hours)", len(projects))
    return await _import_many(projects)


async def _import_many(projects: Iterable[dict]) -> int:
    """Import each project one at a time. One project failing does NOT abort
    the rest — we log and continue so `--all` is resumable after a crash."""
    project_list = list(projects)
    failed = 0
    for p in project_list:
        key = p.get("Key") or str(p.get("ID"))
        try:
            await import_project(int(p["ID"]))
        except Exception as e:
            log.error("project %s failed: %s", key, e)
            failed += 1
    log.info("done. %d projects failed out of %d", failed, len(project_list))
    return 1 if failed else 0


async def cmd_reset(confirm: bool) -> int:
    """Delete every row in simulated orgs (is_simulated=TRUE).

    Requires --confirm to prevent accidental invocation. Uses ON DELETE CASCADE
    where it's already defined in the schema, and explicit deletes for tables
    that don't cascade from organizations.
    """
    assert_not_production(settings.database_url)
    if not confirm:
        log.error("--reset requires --confirm. Refusing to proceed.")
        return 2

    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(Organization.id, Organization.name).where(Organization.is_simulated == True)  # noqa: E712
        )).all()
        if not rows:
            log.info("no simulated organizations found — nothing to delete")
            return 0

        log.info("deleting %d simulated organizations:", len(rows))
        for oid, name in rows:
            log.info("  - %s (%s)", name, oid)

        # The schema doesn't have ON DELETE CASCADE from organizations down.
        # Delete in dependency order. We walk teams for the target orgs and
        # clear everything tied to each team, then delete the orgs.
        # A raw SQL bulk delete keeps this to one query per table.
        org_ids = [r[0] for r in rows]
        org_ids_sql = ", ".join(f"'{str(oid)}'::uuid" for oid in org_ids)

        team_ids = (await session.execute(
            text(f"SELECT id FROM teams WHERE organization_id IN ({org_ids_sql})")
        )).scalars().all()

        if team_ids:
            team_ids_sql = ", ".join(f"'{str(tid)}'::uuid" for tid in team_ids)
            # Order matters: child tables first.
            for stmt in (
                f"DELETE FROM sprint_tickets WHERE sprint_id IN (SELECT id FROM sprints WHERE team_id IN ({team_ids_sql}))",
                f"DELETE FROM sprint_alerts WHERE team_id IN ({team_ids_sql})",
                f"DELETE FROM tickets WHERE team_id IN ({team_ids_sql})",
                f"DELETE FROM sprints WHERE team_id IN ({team_ids_sql})",
                f"DELETE FROM dependencies WHERE team_id IN ({team_ids_sql})",
                f"DELETE FROM developer_velocity_profiles WHERE team_id IN ({team_ids_sql})",
                f"DELETE FROM team_members WHERE team_id IN ({team_ids_sql})",
                f"DELETE FROM developers WHERE team_id IN ({team_ids_sql})",
                f"DELETE FROM teams WHERE id IN ({team_ids_sql})",
            ):
                await session.execute(text(stmt))

        await session.execute(delete(Organization).where(Organization.id.in_(org_ids)))
        await session.commit()
        log.info("reset complete")
    return 0


# --------------------------------------------------------------------------- #
# Entrypoint
# --------------------------------------------------------------------------- #

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="TAWOS → Omada importer")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true", help="list TAWOS projects with issue counts")
    group.add_argument("--project", metavar="KEY_OR_ID", help="import one project by Key or numeric ID")
    group.add_argument("--all-small", action="store_true",
                       help=f"import every project with <{SMALL_PROJECT_CEILING} issues")
    group.add_argument("--all", action="store_true",
                       help="import every project (can take hours)")
    group.add_argument("--reset", action="store_true",
                       help="delete every is_simulated=TRUE organization (requires --confirm)")

    p.add_argument("--limit-issues", type=int, default=None,
                   help="only import the first N issues per project (testing)")
    p.add_argument("--confirm", action="store_true",
                   help="required companion flag for --reset")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.list:
        return cmd_list()

    if args.project:
        return asyncio.run(cmd_project(args.project, args.limit_issues))

    if args.all_small:
        return asyncio.run(cmd_all_small())

    if args.all:
        return asyncio.run(cmd_all())

    if args.reset:
        return asyncio.run(cmd_reset(args.confirm))

    return 2  # unreachable — argparse required=True


if __name__ == "__main__":
    sys.exit(main())
