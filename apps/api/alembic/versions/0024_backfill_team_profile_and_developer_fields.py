"""backfill team profile and developer fields skipped by 0015

Revision ID: 0024
Revises: 0023
Create Date: 2026-06-11
"""
from alembic import op

revision = '0024'
down_revision = '0023'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Re-apply 0015 columns — all use IF NOT EXISTS so safe to run even if
    # some already exist (e.g. on dev DBs that ran 0015 correctly).
    op.execute("ALTER TABLE teams ADD COLUMN IF NOT EXISTS size_tier VARCHAR(20) NULL")
    op.execute("ALTER TABLE teams ADD COLUMN IF NOT EXISTS methodology VARCHAR(20) NULL")
    op.execute("ALTER TABLE teams ADD COLUMN IF NOT EXISTS tech_stack TEXT NULL")
    op.execute("ALTER TABLE teams ADD COLUMN IF NOT EXISTS profile_setup_at TIMESTAMP NULL")

    op.execute("ALTER TABLE developers ADD COLUMN IF NOT EXISTS seniority VARCHAR(20) NULL")
    op.execute("ALTER TABLE developers ADD COLUMN IF NOT EXISTS capacity_hours_per_week INT NULL")
    op.execute("ALTER TABLE developers ADD COLUMN IF NOT EXISTS domain_strengths TEXT NULL")
    op.execute("ALTER TABLE developers ADD COLUMN IF NOT EXISTS meeting_hours_bucket VARCHAR(10) NULL")


def downgrade() -> None:
    pass
