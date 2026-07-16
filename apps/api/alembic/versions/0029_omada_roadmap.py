"""omada roadmap — projects, milestones, tasks

Revision ID: 0029
Revises: 0028
Create Date: 2026-07-16
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0029'
down_revision = '0028'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'projects',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('team_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('onboarding_session_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('purpose', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['team_id'], ['teams.id']),
        sa.ForeignKeyConstraint(['onboarding_session_id'], ['onboarding_sessions.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_projects_team_id', 'projects', ['team_id'])
    op.create_index('ix_projects_onboarding_session_id', 'projects', ['onboarding_session_id'], unique=True)

    op.create_table(
        'milestones',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_milestones_project_id', 'milestones', ['project_id'])
    op.create_index('ix_milestones_project_id_sort_order', 'milestones', ['project_id', 'sort_order'])

    op.create_table(
        'tasks',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('milestone_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='todo'),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.Column('github_repo', sa.String(), nullable=True),
        sa.Column('github_path', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['milestone_id'], ['milestones.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_tasks_milestone_id', 'tasks', ['milestone_id'])
    op.create_index('ix_tasks_milestone_id_sort_order', 'tasks', ['milestone_id', 'sort_order'])


def downgrade() -> None:
    op.drop_table('tasks')
    op.drop_table('milestones')
    op.drop_table('projects')
