"""planner — per-task progress feedback

Adds a free-text feedback note per task. The user writes how a task went in the
day agenda; the Groq adjuster reads these notes to re-plan upcoming work.

Revision ID: 0033
Revises: 0032
Create Date: 2026-07-21
"""
from alembic import op
import sqlalchemy as sa

revision = '0033'
down_revision = '0032'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('tasks', sa.Column('feedback', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('tasks', 'feedback')
