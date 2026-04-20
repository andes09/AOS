"""Introspect the local TAWOS MySQL.

Prints:
  - All tables with row counts (descending)
  - Full column list per table with types
  - Sample 5 rows from each of the main entity tables (Issue, Sprint, Project, User, ...)

Run this before writing the mapper — the TAWOS v1.1 schema has ~30 tables and
the exact column names differ from what the published paper describes.

Usage (from apps/api/):
    python -m tawos_importer.inspect
    python -m tawos_importer.inspect --table Issue
    python -m tawos_importer.inspect --sample 0   # schema only
"""
from __future__ import annotations

import argparse
import sys

from tawos_importer.source_db import tawos_connection

MAIN_TABLES = ("Project", "Issue", "Sprint", "User", "Issue_Link", "Status", "Issue_Type")


def list_tables(cur) -> list[tuple[str, int]]:
    cur.execute(
        "SELECT table_name AS t, table_rows AS r "
        "FROM information_schema.tables "
        "WHERE table_schema = DATABASE() "
        "ORDER BY table_rows DESC"
    )
    # information_schema.table_rows is an estimate for InnoDB — good enough for inspection.
    return [(row["t"], row["r"] or 0) for row in cur.fetchall()]


def describe_table(cur, table: str) -> list[dict]:
    cur.execute(
        "SELECT column_name AS name, column_type AS type, is_nullable AS nullable, "
        "column_key AS key_, column_default AS default_ "
        "FROM information_schema.columns "
        "WHERE table_schema = DATABASE() AND table_name = %s "
        "ORDER BY ordinal_position",
        (table,),
    )
    return cur.fetchall()


def sample_rows(cur, table: str, n: int) -> list[dict]:
    cur.execute(f"SELECT * FROM `{table}` LIMIT {int(n)}")
    return cur.fetchall()


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect the TAWOS MySQL schema")
    parser.add_argument("--table", help="only inspect this one table")
    parser.add_argument("--sample", type=int, default=5, help="sample N rows (0 = schema only)")
    args = parser.parse_args()

    with tawos_connection() as conn:
        cur = conn.cursor()

        tables = list_tables(cur)
        print("=" * 72)
        print(f"TAWOS MySQL — {len(tables)} tables")
        print("=" * 72)
        for name, rows in tables:
            print(f"  {name:40s} ~{rows:>10,} rows")
        print()

        targets = [args.table] if args.table else [t for t, _ in tables]

        for t in targets:
            if args.table is None and t not in MAIN_TABLES and args.sample > 0:
                # Full schema for every table is noisy; only dump samples for main tables.
                continue
            cols = describe_table(cur, t)
            if not cols:
                print(f"(no columns for {t})\n")
                continue
            print("-" * 72)
            print(f"TABLE {t}")
            print("-" * 72)
            for c in cols:
                null = "NULL" if c["nullable"] == "YES" else "NOT NULL"
                key = f" {c['key_']}" if c["key_"] else ""
                print(f"  {c['name']:30s} {c['type']:30s} {null}{key}")
            if args.sample > 0:
                rows = sample_rows(cur, t, args.sample)
                print(f"  --- first {len(rows)} rows ---")
                for row in rows:
                    print("  ", {k: _trunc(v) for k, v in row.items()})
            print()

    return 0


def _trunc(v, n=80):
    s = "" if v is None else str(v)
    return s if len(s) <= n else s[:n] + "…"


if __name__ == "__main__":
    sys.exit(main())
