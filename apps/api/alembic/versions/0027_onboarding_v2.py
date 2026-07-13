"""onboarding v2 — developer phone, github connections, idea-interview sessions

Revision ID: 0027
Revises: 0026
Create Date: 2026-07-13
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0027'
down_revision = '0026'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('developers', sa.Column('phone', sa.String(32), nullable=True))

    op.create_table(
        'github_connections',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('github_user_id', sa.String(255), nullable=False),
        sa.Column('github_login', sa.String(255), nullable=False),
        sa.Column('avatar_url', sa.String(500), nullable=True),
        sa.Column('encrypted_access_token', sa.Text(), nullable=False),
        sa.Column('encrypted_refresh_token', sa.Text(), nullable=True),
        sa.Column('token_expires_at', sa.DateTime(), nullable=True),
        sa.Column('scopes', sa.JSON(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('connected_by_user_id', sa.String(255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_github_connections_organization_id', 'github_connections', ['organization_id'])

    op.create_table(
        'onboarding_sessions',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_by_user_id', sa.String(255), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='in_progress'),
        sa.Column('project_brief', postgresql.JSONB(), nullable=True),
        sa.Column('brief_complete', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('github_skipped_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organization_id', name='uq_onboarding_sessions_organization_id'),
    )
    op.create_index('ix_onboarding_sessions_organization_id', 'onboarding_sessions', ['organization_id'])

    op.create_table(
        'onboarding_messages',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('session_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('role', sa.String(20), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('seq', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['session_id'], ['onboarding_sessions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_onboarding_messages_session_id', 'onboarding_messages', ['session_id'])
    op.create_index('ix_onboarding_messages_session_seq', 'onboarding_messages', ['session_id', 'seq'])


def downgrade() -> None:
    op.drop_table('onboarding_messages')
    op.drop_table('onboarding_sessions')
    op.drop_table('github_connections')
    op.drop_column('developers', 'phone')
