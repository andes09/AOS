"""add sync_status table

Revision ID: 0026
Revises: 0025
Create Date: 2026-06-17
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0026'
down_revision = '0025'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'sync_status',
        sa.Column('team_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('state', sa.String(20), nullable=False, server_default='queued'),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('error_code', sa.String(50), nullable=True),
        sa.Column('error_message', sa.String(500), nullable=True),
        sa.Column('tickets_synced', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('members_synced', sa.Integer(), nullable=False, server_default='0'),
        sa.ForeignKeyConstraint(['team_id'], ['teams.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('team_id'),
    )


def downgrade() -> None:
    op.drop_table('sync_status')
