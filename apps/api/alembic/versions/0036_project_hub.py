"""project hub — project status, org max_projects, multi-session onboarding

Revision ID: 0036
Revises: 0035
Create Date: 2026-07-27
"""
from alembic import op
import sqlalchemy as sa

revision = '0036'
down_revision = '0035'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'projects',
        sa.Column('status', sa.String(length=20), nullable=False, server_default='active'),
    )
    op.add_column(
        'organizations',
        sa.Column('max_projects', sa.Integer(), nullable=True),
    )
    # An org can now have multiple onboarding sessions (one per project). Drop
    # the unique constraint but keep the plain index added alongside it in
    # 0027_onboarding_v2.py — the now-multi-row lookups still need it.
    op.drop_constraint(
        'uq_onboarding_sessions_organization_id', 'onboarding_sessions', type_='unique'
    )


def downgrade() -> None:
    # Only safe if no org has >1 OnboardingSession row at downgrade time —
    # same caveat style as other migrations that re-tighten a relaxed
    # constraint.
    op.create_unique_constraint(
        'uq_onboarding_sessions_organization_id', 'onboarding_sessions', ['organization_id']
    )
    op.drop_column('organizations', 'max_projects')
    op.drop_column('projects', 'status')
