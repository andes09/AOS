"""onboarding v2 — awaiting_confirmation flag on idea-interview sessions

Revision ID: 0048
Revises: 0047
Create Date: 2026-07-23
"""
from alembic import op
import sqlalchemy as sa

revision = '0048'
down_revision = '0047'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'onboarding_sessions',
        sa.Column('awaiting_confirmation', sa.Boolean(), nullable=False, server_default='false'),
    )


def downgrade() -> None:
    op.drop_column('onboarding_sessions', 'awaiting_confirmation')
