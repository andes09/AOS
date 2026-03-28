"""make tickets.sprint_id nullable for backlog tickets

Revision ID: 0004
Revises: init004
Create Date: 2026-03-28
"""
from alembic import op

revision = 'init005'
down_revision = 'init004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tickets ALTER COLUMN sprint_id DROP NOT NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE tickets ALTER COLUMN sprint_id SET NOT NULL")
