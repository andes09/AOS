"""onboarding_sessions.github_setup_needed_at — "I don't have GitHub yet"

The onboarding GitHub step's escape hatch used to be a silent skip, which told
the roadmap generator nothing. Founders who have never used GitHub now say so
explicitly, and that stamp makes services/github_setup_plan prepend a fixed
"Get set up with GitHub" milestone to their plan.

Deliberately a separate column from github_skipped_at rather than a reason on
it: skips recorded before this feature existed meant "not right now", and
regenerating one of those roadmaps must not sprout a beginner setup milestone.

Nullable with no backfill — null is exactly the pre-existing behaviour.

Revision ID: 0051
Revises: 0050
Create Date: 2026-08-05
"""
from alembic import op
import sqlalchemy as sa

revision = '0051'
down_revision = '0050'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'onboarding_sessions',
        sa.Column('github_setup_needed_at', sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('onboarding_sessions', 'github_setup_needed_at')
