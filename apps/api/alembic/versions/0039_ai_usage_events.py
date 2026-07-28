"""ai_usage_events — persisted AI generation cost log for the platform admin dashboard

Revision ID: 0039
Revises: 0038
Create Date: 2026-07-28

Master Dashboard build (see docs/plans/2026-07-20-master-dashboard.md's
"Implementation Notes" header for what changed from the original plan): only
this table is added in this stage. The doc's §6 `github_commit_daily` table
is NOT created — stage 3 (github_task_autocomplete, migration 0038) already
built `github_activity_events`, an append-only per-event log that is a strict
superset of what that aggregate table would have provided; the dashboard's
commit endpoints read from it directly instead.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0039'
down_revision = '0038'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'ai_usage_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('team_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('provider', sa.String(length=20), nullable=False),
        sa.Column('operation', sa.String(length=50), nullable=False),
        sa.Column('model', sa.String(length=100), nullable=True),
        sa.Column('input_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('output_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('cache_write_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('cache_read_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('call_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('cost_usd', sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column('context', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['team_id'], ['teams.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_ai_usage_events_organization_id', 'ai_usage_events', ['organization_id'])
    op.create_index('ix_ai_usage_events_team_id', 'ai_usage_events', ['team_id'])
    op.create_index('ix_ai_usage_events_org_created_at', 'ai_usage_events', ['organization_id', 'created_at'])
    op.create_index('ix_ai_usage_events_created_at', 'ai_usage_events', ['created_at'])
    op.create_index('ix_ai_usage_events_provider_created_at', 'ai_usage_events', ['provider', 'created_at'])


def downgrade() -> None:
    op.drop_index('ix_ai_usage_events_provider_created_at', table_name='ai_usage_events')
    op.drop_index('ix_ai_usage_events_created_at', table_name='ai_usage_events')
    op.drop_index('ix_ai_usage_events_org_created_at', table_name='ai_usage_events')
    op.drop_index('ix_ai_usage_events_team_id', table_name='ai_usage_events')
    op.drop_index('ix_ai_usage_events_organization_id', table_name='ai_usage_events')
    op.drop_table('ai_usage_events')
