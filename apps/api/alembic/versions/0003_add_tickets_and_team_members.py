"""add tickets and team_members tables

Revision ID: 0003
Revises: 0002
Create Date: 2026-03-25
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'init004'
down_revision = 'init003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'team_members',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('team_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('teams.id'), nullable=False, index=True),
        sa.Column('jira_account_id', sa.String(255), nullable=False, index=True),
        sa.Column('display_name', sa.String(255), nullable=False),
        sa.Column('email', sa.String(255), nullable=True),
    )

    op.create_table(
        'tickets',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('sprint_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('sprints.id'), nullable=False, index=True),
        sa.Column('team_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('teams.id'), nullable=False, index=True),
        sa.Column('assignee_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('team_members.id'), nullable=True, index=True),
        sa.Column('jira_issue_id', sa.String(100), nullable=False, unique=True, index=True),
        sa.Column('jira_issue_key', sa.String(50), nullable=True),
        sa.Column('title', sa.Text, nullable=False),
        sa.Column('status', sa.Enum('TODO', 'IN_PROGRESS', 'IN_REVIEW', 'DONE', 'CANCELLED', name='ticketstatus'), nullable=False, server_default='TODO'),
        sa.Column('ticket_type', sa.String(100), nullable=True),
        sa.Column('story_points_estimated', sa.Float, nullable=True),
        sa.Column('time_estimate_hours', sa.Float, nullable=True),
        sa.Column('time_actual_hours', sa.Float, nullable=True),
        sa.Column('labels', postgresql.JSON, nullable=True),
        sa.Column('components', postgresql.JSON, nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column('completed_at', sa.DateTime, nullable=True),
        sa.Column('jira_updated_at', sa.DateTime, nullable=True),
    )


def downgrade() -> None:
    op.drop_table('tickets')
    op.execute("DROP TYPE IF EXISTS ticketstatus")
    op.drop_table('team_members')
