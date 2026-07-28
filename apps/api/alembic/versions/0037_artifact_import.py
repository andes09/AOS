"""artifact import — onboarding_sessions plan-source/import/repo columns, projects.github_repo_full_name

Revision ID: 0037
Revises: 0036
Create Date: 2026-07-28
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0037'
down_revision = '0036'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('onboarding_sessions', sa.Column('onboarding_path', sa.String(length=20), nullable=True))
    # Extracted text only, kept for debugging/audit — the original uploaded
    # file is never persisted (see docs/plans/2026-07-20-import-artifacts.md).
    op.add_column('onboarding_sessions', sa.Column('raw_import_text', sa.Text(), nullable=True))
    op.add_column('onboarding_sessions', sa.Column('proposed_roadmap', postgresql.JSONB(), nullable=True))
    op.add_column('onboarding_sessions', sa.Column('import_analyzed_at', sa.DateTime(), nullable=True))
    op.add_column('onboarding_sessions', sa.Column('selected_github_repo_full_name', sa.String(length=255), nullable=True))
    op.add_column('onboarding_sessions', sa.Column('repo_select_skipped_at', sa.DateTime(), nullable=True))

    op.add_column('projects', sa.Column('github_repo_full_name', sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column('projects', 'github_repo_full_name')

    op.drop_column('onboarding_sessions', 'repo_select_skipped_at')
    op.drop_column('onboarding_sessions', 'selected_github_repo_full_name')
    op.drop_column('onboarding_sessions', 'import_analyzed_at')
    op.drop_column('onboarding_sessions', 'proposed_roadmap')
    op.drop_column('onboarding_sessions', 'raw_import_text')
    op.drop_column('onboarding_sessions', 'onboarding_path')
