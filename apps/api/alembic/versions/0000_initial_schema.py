"""initial schema

Revision ID: 0000
Revises:
Create Date: 2026-03-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'init001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'organizations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('clerk_org_id', sa.String(255), unique=True, nullable=False, index=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('slug', sa.String(100), unique=True, nullable=False, index=True),
        sa.Column('encrypted_anthropic_key', sa.Text, nullable=True),
        sa.Column('use_managed_key', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        'teams',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id'), nullable=False, index=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('jira_board_id', sa.String(100), nullable=True),
        sa.Column('sprint_length_days', sa.Integer, nullable=False, server_default='14'),
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        'developers',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('team_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('teams.id'), nullable=False, index=True),
        sa.Column('clerk_user_id', sa.String(255), nullable=True, index=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('email', sa.String(255), nullable=True),
        sa.Column('role', sa.String(100), nullable=True),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        'jira_connections',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id'), nullable=False, index=True),
        sa.Column('jira_cloud_id', sa.String(255), nullable=False),
        sa.Column('jira_cloud_url', sa.String(500), nullable=False),
        sa.Column('encrypted_access_token', sa.Text, nullable=False),
        sa.Column('encrypted_refresh_token', sa.Text, nullable=False),
        sa.Column('token_expires_at', sa.DateTime, nullable=True),
        sa.Column('scopes', postgresql.JSON, nullable=True),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('last_synced_at', sa.DateTime, nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        'sprints',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('team_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('teams.id'), nullable=False, index=True),
        sa.Column('jira_sprint_id', sa.String(100), nullable=True, index=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('start_date', sa.Date, nullable=True),
        sa.Column('end_date', sa.Date, nullable=True),
        sa.Column('committed_points', sa.Float, nullable=True),
        sa.Column('delivered_points', sa.Float, nullable=True),
        sa.Column('status', sa.Enum('PLANNING', 'ACTIVE', 'COMPLETED', 'CANCELLED', name='sprintstatus'), nullable=False, server_default='PLANNING'),
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        'sprint_tickets',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('sprint_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('sprints.id'), nullable=False, index=True),
        sa.Column('ticket_id', sa.String(100), nullable=False, index=True),
        sa.Column('assignee_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('developers.id'), nullable=True, index=True),
        sa.Column('estimated_points', sa.Float, nullable=True),
        sa.Column('actual_points', sa.Float, nullable=True),
        sa.Column('completed', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('slip_cause', sa.String(100), nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        'developer_velocity_profiles',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('developer_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('developers.id'), nullable=False, index=True),
        sa.Column('team_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('teams.id'), nullable=False, index=True),
        sa.Column('ticket_type', sa.String(100), nullable=True),
        sa.Column('domain', sa.String(255), nullable=True),
        sa.Column('mean_completion_days', sa.Float, nullable=True),
        sa.Column('std_dev', sa.Float, nullable=True),
        sa.Column('sample_size', sa.Integer, nullable=False, server_default='0'),
        sa.Column('sprint_count', sa.Integer, nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table('developer_velocity_profiles')
    op.drop_table('sprint_tickets')
    op.drop_table('sprints')
    op.execute("DROP TYPE IF EXISTS sprintstatus")
    op.drop_table('jira_connections')
    op.drop_table('developers')
    op.drop_table('teams')
    op.drop_table('organizations')
