"""Download the TAWOS MySQL dump into apps/api/tawos_importer/data/.

The dump is hosted on UCL's Research Data Repository (~600MB zipped). Download
is idempotent: if the zip is already present and non-empty, we skip. If only
the unzipped .sql is present, we skip both.

Usage (from apps/api/):
    python -m tawos_importer.download
    python -m tawos_importer.download --url <override>

Paths are resolved off __file__ so the tool works from any cwd.
"""
from __future__ import annotations

import argparse
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from tawos_importer.config import (
    DATA_DIR,
    TAWOS_DUMP_SQL,
    TAWOS_DUMP_URL,
    TAWOS_DUMP_ZIP,
    setup_logging,
)

log = setup_logging()


def _human_size(num_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num_bytes < 1024:
            return f"{num_bytes:.1f}{unit}"
        num_bytes //= 1024
    return f"{num_bytes:.1f}TB"


def download(url: str, dest: Path) -> None:
    """Stream-download with progress. Writes to dest.tmp then renames, so a
    partial download never looks complete."""
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    log.info("downloading %s → %s", url, dest)
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            total = int(resp.headers.get("Content-Length", "0"))
            downloaded = 0
            with tmp.open("wb") as out:
                while True:
                    chunk = resp.read(1024 * 256)
                    if not chunk:
                        break
                    out.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        pct = downloaded * 100 // total
                        print(
                            f"\r  {_human_size(downloaded)}/{_human_size(total)} ({pct}%)",
                            end="",
                            flush=True,
                        )
        print()
    except urllib.error.URLError as e:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"failed to download {url}: {e}") from e
    tmp.rename(dest)
    log.info("downloaded %s (%s)", dest.name, _human_size(dest.stat().st_size))


def unzip_if_needed(zip_path: Path, sql_path: Path) -> None:
    if sql_path.exists() and sql_path.stat().st_size > 0:
        log.info("sql dump already unzipped at %s (%s)", sql_path, _human_size(sql_path.stat().st_size))
        return
    log.info("unzipping %s", zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        sql_members = [n for n in zf.namelist() if n.lower().endswith(".sql")]
        if not sql_members:
            raise RuntimeError(f"no .sql file found inside {zip_path}")
        # The TAWOS zip has a single top-level .sql; extract it and rename.
        member = sql_members[0]
        with zf.open(member) as src, sql_path.open("wb") as dst:
            while True:
                chunk = src.read(1024 * 1024)
                if not chunk:
                    break
                dst.write(chunk)
    log.info("unzipped → %s (%s)", sql_path, _human_size(sql_path.stat().st_size))


def main() -> int:
    parser = argparse.ArgumentParser(description="Download the TAWOS MySQL dump")
    parser.add_argument("--url", default=TAWOS_DUMP_URL, help="override the download URL")
    parser.add_argument(
        "--force", action="store_true", help="re-download even if files already exist"
    )
    args = parser.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if TAWOS_DUMP_SQL.exists() and TAWOS_DUMP_SQL.stat().st_size > 0 and not args.force:
        log.info("tawos.sql already present (%s) — skipping download",
                 _human_size(TAWOS_DUMP_SQL.stat().st_size))
        return 0

    if TAWOS_DUMP_ZIP.exists() and TAWOS_DUMP_ZIP.stat().st_size > 0 and not args.force:
        log.info("tawos.sql.zip already present (%s) — skipping download",
                 _human_size(TAWOS_DUMP_ZIP.stat().st_size))
    else:
        download(args.url, TAWOS_DUMP_ZIP)

    unzip_if_needed(TAWOS_DUMP_ZIP, TAWOS_DUMP_SQL)
    log.info("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
