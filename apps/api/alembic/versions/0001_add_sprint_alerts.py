"""add sprint_alerts table

Revision ID: 0001
Revises:
Create Date: 2026-03-17
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0001'
down_revision = '0000'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'sprint_alerts',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('sprint_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('sprints.id'), nullable=False, index=True),
        sa.Column('team_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('teams.id'), nullable=False, index=True),
        sa.Column('type', sa.Enum('stalled_ticket', 'over_capacity', 'dependency_risk', 'spillover_prediction', name='alerttype'), nullable=False),
        sa.Column('description', sa.Text, nullable=False),
        sa.Column('recommended_action', sa.Text, nullable=False),
        sa.Column('dismissed', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table('sprint_alerts')
    op.execute("DROP TYPE IF EXISTS alerttype")
