"""Source the downloaded TAWOS .sql dump into the local MySQL container.

Idempotent: checks whether the `tawos` database already has the expected tables
populated, and skips if so. If MySQL isn't up, instructs the user to run
`docker compose up -d`.

Usage (from apps/api/):
    python -m tawos_importer.load_mysql
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from tawos_importer.config import (
    TAWOS_DUMP_SQL,
    TAWOS_MYSQL_DATABASE,
    TAWOS_MYSQL_HOST,
    TAWOS_MYSQL_PASSWORD,
    TAWOS_MYSQL_PORT,
    TAWOS_MYSQL_USER,
    setup_logging,
)

log = setup_logging()


def mysql_client_available() -> bool:
    return shutil.which("mysql") is not None


def run_mysql_query(sql: str) -> str | None:
    """Run a single query and return stdout, or None if the connection failed."""
    cmd = [
        "mysql",
        f"-h{TAWOS_MYSQL_HOST}",
        f"-P{TAWOS_MYSQL_PORT}",
        f"-u{TAWOS_MYSQL_USER}",
        f"-p{TAWOS_MYSQL_PASSWORD}",
        "-N",  # no column headers
        "-e",
        sql,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def looks_already_loaded() -> bool:
    """Cheap test: the TAWOS dump has many tables, most importantly `Issue`."""
    out = run_mysql_query(
        f"SELECT COUNT(*) FROM information_schema.tables "
        f"WHERE table_schema='{TAWOS_MYSQL_DATABASE}' AND table_name='Issue'"
    )
    if out is None or out != "1":
        return False
    out = run_mysql_query(f"USE `{TAWOS_MYSQL_DATABASE}`; SELECT COUNT(*) FROM Issue")
    if out is None:
        return False
    try:
        return int(out) > 0
    except ValueError:
        return False


def source_dump(sql_file: Path) -> None:
    """Pipe the SQL dump into mysql. Use subprocess.Popen with stdin so we
    don't load the whole file into Python memory."""
    log.info("sourcing %s into mysql (this can take 10–30 minutes on first run)", sql_file)
    cmd = [
        "mysql",
        f"-h{TAWOS_MYSQL_HOST}",
        f"-P{TAWOS_MYSQL_PORT}",
        f"-u{TAWOS_MYSQL_USER}",
        f"-p{TAWOS_MYSQL_PASSWORD}",
        TAWOS_MYSQL_DATABASE,
    ]
    with sql_file.open("rb") as f:
        proc = subprocess.run(cmd, stdin=f, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"mysql source failed (exit {proc.returncode}): "
            f"{proc.stderr.decode(errors='replace')[:500]}"
        )
    log.info("dump sourced successfully")


def main() -> int:
    if not TAWOS_DUMP_SQL.exists():
        log.error("tawos.sql not found at %s — run download.py first", TAWOS_DUMP_SQL)
        return 1

    if not mysql_client_available():
        log.error("mysql CLI not found on PATH. Install via `brew install mysql-client` and add to PATH.")
        return 1

    ping = run_mysql_query("SELECT 1")
    if ping != "1":
        log.error(
            "cannot reach tawos mysql at %s:%s. Start it with:\n"
            "    cd apps/api/tawos_importer && docker compose up -d",
            TAWOS_MYSQL_HOST, TAWOS_MYSQL_PORT,
        )
        return 1

    if looks_already_loaded():
        log.info("tawos database already populated — skipping source")
        return 0

    source_dump(TAWOS_DUMP_SQL)
    if not looks_already_loaded():
        log.error("dump sourced but Issue table is still empty. Inspect mysql logs.")
        return 1
    log.info("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
