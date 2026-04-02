"""create dependencies table for dependency radar

Revision ID: 0008
Revises: 0007
Create Date: 2026-04-02
"""
from alembic import op

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS dependencies (
          id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          team_id         UUID NOT NULL REFERENCES teams(id),
          ticket_key      VARCHAR(50) NOT NULL,
          ticket_title    TEXT,
          blocked_by_key  VARCHAR(50),
          dependency_type VARCHAR(30) NOT NULL,
          risk_level      VARCHAR(10) NOT NULL,
          description     TEXT,
          source          VARCHAR(10) NOT NULL DEFAULT 'manual',
          resolved_at     TIMESTAMP,
          created_at      TIMESTAMP NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_dep_team_resolved ON dependencies(team_id, resolved_at)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS dependencies")
