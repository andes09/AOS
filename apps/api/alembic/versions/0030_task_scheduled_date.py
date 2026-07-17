"""roadmap — task scheduled_date (per-day calendar scheduling)

Revision ID: 0030
Revises: 0029
Create Date: 2026-07-17
"""
from alembic import op
import sqlalchemy as sa

revision = '0030'
down_revision = '0029'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('tasks', sa.Column('scheduled_date', sa.Date(), nullable=True))
    op.create_index('ix_tasks_scheduled_date', 'tasks', ['scheduled_date'])


def downgrade() -> None:
    op.drop_index('ix_tasks_scheduled_date', table_name='tasks')
    op.drop_column('tasks', 'scheduled_date')
