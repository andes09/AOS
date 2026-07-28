"""roadmap — task parallel flag (drives the "PARALLEL" tag / waiting fade)

Revision ID: 0035
Revises: 0034
Create Date: 2026-07-28
"""
from alembic import op
import sqlalchemy as sa

revision = '0035'
down_revision = '0034'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # server_default false: existing tasks are sequential (not parallel) by
    # default, and the generator sets the flag explicitly on new work.
    op.add_column(
        'tasks',
        sa.Column('parallel', sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column('tasks', 'parallel')
