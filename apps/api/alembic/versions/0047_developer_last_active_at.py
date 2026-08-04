"""developer last_active_at — anti-dormancy activity tracking

A single mutable timestamp, not an event log: dormancy only ever needs "when
did this person last do something," which one O(1)-written column answers for
both the pull-based in-app banner and the (later) push-based email job. See
docs/plans/2026-07-20-anti-dormancy-mvp.md.

Nullable: a brand-new developer has no activity yet, and the dormancy read
falls back to Organization.onboarding_completed_at via COALESCE.

Revision ID: 0047
Revises: 0046
Create Date: 2026-08-03
"""
from alembic import op
import sqlalchemy as sa

revision = '0047'
down_revision = '0046'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('developers', sa.Column('last_active_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('developers', 'last_active_at')
