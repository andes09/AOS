"""Connection helper for the TAWOS source MySQL.

Uses PyMySQL (pure-Python, already easy to pip install). The connection is
short-lived per import run; all mutation happens on the Omada Postgres side.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

try:
    import pymysql
    import pymysql.cursors
except ImportError as e:  # pragma: no cover - surfaced at runtime
    raise RuntimeError(
        "pymysql is required for the TAWOS importer. Install with `uv pip install pymysql` "
        "inside apps/api, or add it to pyproject.toml dev deps."
    ) from e

from tawos_importer.config import (
    TAWOS_MYSQL_DATABASE,
    TAWOS_MYSQL_HOST,
    TAWOS_MYSQL_PASSWORD,
    TAWOS_MYSQL_PORT,
    TAWOS_MYSQL_USER,
)


@contextmanager
def tawos_connection() -> Iterator["pymysql.connections.Connection"]:
    """Yield a PyMySQL connection with DictCursor. Auto-closes on exit."""
    conn = pymysql.connect(
        host=TAWOS_MYSQL_HOST,
        port=TAWOS_MYSQL_PORT,
        user=TAWOS_MYSQL_USER,
        password=TAWOS_MYSQL_PASSWORD,
        database=TAWOS_MYSQL_DATABASE,
        cursorclass=pymysql.cursors.DictCursor,
        charset="utf8mb4",
        read_timeout=120,
    )
    try:
        yield conn
    finally:
        conn.close()
