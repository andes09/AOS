"""team profile fields for onboarding wizard

Revision ID: 0015
Revises: 0014
Create Date: 2026-05-20
"""
from alembic import op

revision = '0015'
down_revision = '0014'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # teams: onboarding profile fields
    op.execute("ALTER TABLE teams ADD COLUMN IF NOT EXISTS size_tier VARCHAR(20) NULL")
    op.execute("ALTER TABLE teams ADD COLUMN IF NOT EXISTS methodology VARCHAR(20) NULL")
    op.execute("ALTER TABLE teams ADD COLUMN IF NOT EXISTS tech_stack TEXT NULL")
    op.execute("ALTER TABLE teams ADD COLUMN IF NOT EXISTS profile_setup_at TIMESTAMP NULL")

    # developers: capacity / seniority fields
    op.execute("ALTER TABLE developers ADD COLUMN IF NOT EXISTS seniority VARCHAR(20) NULL")
    op.execute("ALTER TABLE developers ADD COLUMN IF NOT EXISTS capacity_hours_per_week INT NULL")
    op.execute("ALTER TABLE developers ADD COLUMN IF NOT EXISTS domain_strengths TEXT NULL")
    op.execute("ALTER TABLE developers ADD COLUMN IF NOT EXISTS meeting_hours_bucket VARCHAR(10) NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE developers DROP COLUMN IF EXISTS meeting_hours_bucket")
    op.execute("ALTER TABLE developers DROP COLUMN IF EXISTS domain_strengths")
    op.execute("ALTER TABLE developers DROP COLUMN IF EXISTS capacity_hours_per_week")
    op.execute("ALTER TABLE developers DROP COLUMN IF EXISTS seniority")

    op.execute("ALTER TABLE teams DROP COLUMN IF EXISTS profile_setup_at")
    op.execute("ALTER TABLE teams DROP COLUMN IF EXISTS tech_stack")
    op.execute("ALTER TABLE teams DROP COLUMN IF EXISTS methodology")
    op.execute("ALTER TABLE teams DROP COLUMN IF EXISTS size_tier")
