"""meeting overhead pct on teams and developer capacity overrides table

Revision ID: 0012
Revises: 0011
Create Date: 2026-04-09
"""
from alembic import op

revision = '0012'
down_revision = '0011'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE teams
            ADD COLUMN IF NOT EXISTS meeting_overhead_pct FLOAT NOT NULL DEFAULT 0.0
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS developer_capacity_overrides (
            id           UUID PRIMARY KEY,
            developer_id UUID NOT NULL REFERENCES developers(id) ON DELETE CASCADE,
            sprint_id    UUID REFERENCES sprints(id) ON DELETE CASCADE,
            capacity_pct FLOAT,
            pto_days     FLOAT,
            notes        TEXT,
            created_by   VARCHAR(255) NOT NULL,
            created_at   TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """)

    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_dev_capacity_sprint
            ON developer_capacity_overrides(developer_id, sprint_id)
            WHERE sprint_id IS NOT NULL
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_dev_capacity_dev_id
            ON developer_capacity_overrides(developer_id)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS developer_capacity_overrides")
    op.execute("ALTER TABLE teams DROP COLUMN IF EXISTS meeting_overhead_pct")
