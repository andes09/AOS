"""add jira_project_key to teams

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-18
"""
from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('teams', sa.Column('jira_project_key', sa.String(100), nullable=True))


def downgrade() -> None:
    op.drop_column('teams', 'jira_project_key')
