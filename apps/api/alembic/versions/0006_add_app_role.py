"""add app_role column to developers

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-02
"""
from alembic import op

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE developers ADD COLUMN IF NOT EXISTS app_role VARCHAR(20) NOT NULL DEFAULT 'developer'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE developers DROP COLUMN IF EXISTS app_role")
