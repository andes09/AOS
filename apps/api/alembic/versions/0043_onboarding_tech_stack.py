"""onboarding tech-stack step — onboarding_sessions known_tech_stack/tech_experience

Revision ID: 0043
Revises: 0042
Create Date: 2026-07-29
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0043'
down_revision = '0042'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('onboarding_sessions', sa.Column('known_tech_stack', postgresql.JSONB(), nullable=True))
    op.add_column('onboarding_sessions', sa.Column('tech_experience', sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column('onboarding_sessions', 'tech_experience')
    op.drop_column('onboarding_sessions', 'known_tech_stack')
