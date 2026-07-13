"""onboarding v2 — project purpose classification (hobby/startup/learning)

Revision ID: 0028
Revises: 0027
Create Date: 2026-07-13
"""
from alembic import op
import sqlalchemy as sa

revision = '0028'
down_revision = '0027'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('onboarding_sessions', sa.Column('project_purpose', sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column('onboarding_sessions', 'project_purpose')
