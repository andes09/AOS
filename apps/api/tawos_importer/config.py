"""Shared config for the TAWOS importer.

Holds paths, connection details for the local TAWOS MySQL, logging setup, and
the production-DB safety check.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
LOG_FILE = HERE / "import.log"

# Local MySQL where the TAWOS dump is loaded. Override via env if needed.
TAWOS_MYSQL_HOST = os.environ.get("TAWOS_MYSQL_HOST", "127.0.0.1")
TAWOS_MYSQL_PORT = int(os.environ.get("TAWOS_MYSQL_PORT", "3307"))  # 3307 to avoid collision
TAWOS_MYSQL_USER = os.environ.get("TAWOS_MYSQL_USER", "root")
TAWOS_MYSQL_PASSWORD = os.environ.get("TAWOS_MYSQL_PASSWORD", "tawos")
TAWOS_MYSQL_DATABASE = os.environ.get("TAWOS_MYSQL_DATABASE", "tawos")

# UCL Research Data Repository hosts the official dump.
# If this URL breaks (UCL can rotate file IDs), set TAWOS_DUMP_URL in env.
TAWOS_DUMP_URL = os.environ.get(
    "TAWOS_DUMP_URL",
    "https://rdr.ucl.ac.uk/ndownloader/files/37817003",
)
TAWOS_DUMP_ZIP = DATA_DIR / "tawos.sql.zip"
TAWOS_DUMP_SQL = DATA_DIR / "tawos.sql"

# Hostname substrings that identify the production DB. Any DATABASE_URL that
# contains one of these is refused. User-supplied list; extend as prod infra grows.
PROD_HOSTNAME_PATTERNS = (
    "api-production-2054",
    "caboose.proxy.rlwy.net",  # Railway production Postgres endpoint
)


def assert_not_production(database_url: str) -> None:
    """Raise RuntimeError if database_url points at the production DB.

    Called before every mutation so a misconfigured .env can never touch prod.
    """
    if not database_url:
        raise RuntimeError("DATABASE_URL is empty — refusing to run TAWOS import")
    for pattern in PROD_HOSTNAME_PATTERNS:
        if pattern in database_url:
            raise RuntimeError(
                f"Refusing to run TAWOS import against production DB "
                f"(matched pattern {pattern!r} in DATABASE_URL)"
            )


def setup_logging(verbose: bool = False) -> logging.Logger:
    """Logger that writes to both stderr and apps/api/tawos_importer/import.log."""
    logger = logging.getLogger("tawos")
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)

    fmt = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(LOG_FILE)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    return logger
