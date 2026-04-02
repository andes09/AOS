"""create retrospectives and retro_patterns tables for retro AI

Revision ID: 0009
Revises: 0008
Create Date: 2026-04-02
"""
from alembic import op

revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS retrospectives (
          id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          sprint_id        UUID NOT NULL UNIQUE REFERENCES sprints(id),
          team_id          UUID NOT NULL REFERENCES teams(id),
          generated_at     TIMESTAMP NOT NULL DEFAULT now(),
          went_well        JSONB,
          went_poorly      JSONB,
          action_items     JSONB,
          velocity_summary JSONB
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS retro_patterns (
          id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          team_id               UUID NOT NULL REFERENCES teams(id),
          pattern_type          VARCHAR(30) NOT NULL,
          description           TEXT,
          occurrence_count      INT NOT NULL DEFAULT 1,
          first_seen_sprint_id  UUID REFERENCES sprints(id),
          last_seen_sprint_id   UUID REFERENCES sprints(id),
          status                VARCHAR(10) NOT NULL DEFAULT 'active',
          affected_sprint_names JSONB
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_retro_patterns_team_status ON retro_patterns(team_id, status)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS retro_patterns")
    op.execute("DROP TABLE IF EXISTS retrospectives")
