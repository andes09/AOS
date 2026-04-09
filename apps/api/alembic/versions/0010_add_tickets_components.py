"""add components column to tickets table

Revision ID: 0010
Revises: 0009
Create Date: 2026-04-07
"""
from alembic import op

revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS components JSON")


def downgrade() -> None:
    op.execute("ALTER TABLE tickets DROP COLUMN IF EXISTS components")
