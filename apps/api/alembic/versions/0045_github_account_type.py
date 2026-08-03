"""github account type — github_connections.account_type (User | Organization)

Revision ID: 0045
Revises: 0044
Create Date: 2026-08-03
"""
from alembic import op
import sqlalchemy as sa

revision = '0045'
down_revision = '0044'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('github_connections', sa.Column('account_type', sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column('github_connections', 'account_type')
