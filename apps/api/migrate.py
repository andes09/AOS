"""Production migration entrypoint (Railway preDeployCommand).

Alembic is the single source of truth for schema. This script does NOT carry
its own SQL or a hardcoded head — it only:

  1. Self-heals a corrupted ``alembic_version`` table. The previous version of
     this file ran ``INSERT INTO alembic_version ... ON CONFLICT DO NOTHING``
     once per revision, which violates Alembic's invariant that the table holds
     exactly one row (the current head). That left databases with one row per
     applied revision, after which ``alembic upgrade head`` aborts with
     "Requested revision X overlaps with other requested revisions ...". We
     collapse any such tangle down to the single most-advanced applied revision.
  2. Runs ``alembic upgrade head``.

Step 1 is idempotent: once the table holds <=1 row it is a no-op.
"""
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

API_DIR = Path(__file__).resolve().parent
ALEMBIC_INI = API_DIR / "alembic.ini"


def _alembic_config() -> Config:
    return Config(str(ALEMBIC_INI))


def _heal_version_table(cfg: Config) -> None:
    """Collapse a multi-row alembic_version down to its true tip."""
    from src.config import settings

    script = ScriptDirectory.from_config(cfg)
    head_to_base = [rev.revision for rev in script.walk_revisions()]  # head .. base

    engine = create_engine(settings.database_url_sync)
    try:
        with engine.begin() as conn:
            if conn.execute(text("SELECT to_regclass('public.alembic_version')")).scalar() is None:
                return  # fresh DB; alembic will create and stamp it

            rows = [r[0] for r in conn.execute(text("SELECT version_num FROM alembic_version"))]
            if len(rows) <= 1:
                return

            present = set(rows)
            keep = next((rev for rev in head_to_base if rev in present), None)
            if keep is None:
                # All rows are unknown to the current script tree — don't guess;
                # let `alembic upgrade` surface a clear error instead.
                return

            print(
                f"[migrate] alembic_version had {len(rows)} rows {sorted(rows)}; "
                f"collapsing to '{keep}' (legacy migrate.py corruption)",
                flush=True,
            )
            conn.execute(
                text("DELETE FROM alembic_version WHERE version_num != :keep"),
                {"keep": keep},
            )
    finally:
        engine.dispose()


def main() -> int:
    cfg = _alembic_config()
    _heal_version_table(cfg)
    print("[migrate] running: alembic upgrade head", flush=True)
    command.upgrade(cfg, "head")
    print("[migrate] alembic upgrade head complete", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
