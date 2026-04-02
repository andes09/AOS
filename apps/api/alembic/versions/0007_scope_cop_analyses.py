"""create ticket_analyses table for scope cop

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-02
"""
from alembic import op

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS ticket_analyses (
          id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          team_id         UUID NOT NULL REFERENCES teams(id),
          ticket_key      VARCHAR(50) NOT NULL,
          ticket_title    TEXT,
          readiness_score INT,
          status          VARCHAR(20) NOT NULL,
          issues          JSONB,
          suggestions     JSONB,
          analyzed_at     TIMESTAMP NOT NULL DEFAULT now(),
          CONSTRAINT uq_ticket_analysis UNIQUE (team_id, ticket_key)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ticket_analyses")
