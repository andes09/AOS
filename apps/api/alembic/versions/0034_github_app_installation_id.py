"""github app — installation_id column

Revision ID: 0034
Revises: 0033
Create Date: 2026-07-21
"""
from alembic import op
import sqlalchemy as sa

revision = '0034'
down_revision = '0033'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('github_connections', sa.Column('installation_id', sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column('github_connections', 'installation_id')
