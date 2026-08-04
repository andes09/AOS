#!/usr/bin/env bash
# Starts the full local Omada dev stack — postgres/redis, the API, the celery
# worker, and web — and stops everything together on Ctrl+C.
set -e

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "==> Starting postgres/redis (docker-compose)..."
docker-compose up -d postgres redis

# kill 0 signals this script's whole process group, which includes every
# background job started below (and their children, e.g. uvicorn's reload
# subprocess and celery's worker pool) — but not the docker containers above,
# which are deliberately left running across dev sessions.
trap 'kill 0' EXIT INT TERM

run() {
  local label="$1"; shift
  ( "$@" 2>&1 | sed -u "s/^/[$label] /" ) &
}

run api    bash -c 'cd apps/api && uv run uvicorn src.main:app --reload --port 8000'
run worker bash -c 'cd apps/api && uv run celery -A src.worker:celery_app worker --loglevel=info -Q celery'
run web    pnpm --filter web dev

wait
