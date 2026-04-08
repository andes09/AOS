#!/usr/bin/env bash
# Idempotent local DB setup — safe to run multiple times.
# Creates the 'agileos' role and database if they don't exist, then applies all migrations.
set -e

psql postgres -tc "SELECT 1 FROM pg_roles WHERE rolname='agileos'" | grep -q 1 || \
  psql postgres -c "CREATE ROLE agileos WITH LOGIN PASSWORD 'agileos_dev' CREATEDB;"

psql postgres -tc "SELECT 1 FROM pg_database WHERE datname='agileos'" | grep -q 1 || \
  psql postgres -c "CREATE DATABASE agileos OWNER agileos;"

cd "$(dirname "$0")/.." && .venv/bin/alembic upgrade head

echo "DB ready."
