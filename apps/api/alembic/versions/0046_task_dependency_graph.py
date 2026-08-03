"""task dependency graph — task_dependencies join table, drop tasks.parallel

Revision ID: 0046
Revises: 0045
Create Date: 2026-08-03
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0046'
down_revision = '0045'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Replaces the flat `parallel` boolean with explicit prerequisite edges:
    # a row (task_id, depends_on_task_id) means task_id can't be completed
    # until depends_on_task_id is done. No data backfill — the old boolean's
    # "doesn't block on whatever's immediately before it" is a positional
    # artifact, not a real prerequisite relationship; existing rows simply
    # become unblocked until the roadmap is regenerated.
    op.create_table(
        'task_dependencies',
        sa.Column('task_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tasks.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('depends_on_task_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tasks.id', ondelete='CASCADE'), primary_key=True),
        sa.CheckConstraint('task_id != depends_on_task_id', name='ck_task_dependencies_no_self_loop'),
    )
    op.drop_column('tasks', 'parallel')


def downgrade() -> None:
    op.add_column(
        'tasks',
        sa.Column('parallel', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.drop_table('task_dependencies')
