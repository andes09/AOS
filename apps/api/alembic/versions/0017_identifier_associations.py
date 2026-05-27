"""identifier associations for skill inference

Revision ID: 0017
Revises: 0016
Create Date: 2026-05-26
"""
from alembic import op

revision = '0017'
down_revision = '0016'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # team_identifiers: per-team learned tokens -> skill mappings
    op.execute("""
        CREATE TABLE IF NOT EXISTS team_identifiers (
            id                UUID PRIMARY KEY,
            team_id           UUID NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
            token             TEXT NOT NULL,
            normalized_token  TEXT NOT NULL,
            skill             VARCHAR(100) NOT NULL,
            domain            VARCHAR(50) NULL,
            confidence        FLOAT NOT NULL DEFAULT 0.5,
            source            VARCHAR(30) NOT NULL,
            occurrence_count  INTEGER NOT NULL DEFAULT 1,
            first_seen_at     TIMESTAMP NOT NULL DEFAULT NOW(),
            last_seen_at      TIMESTAMP NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_team_identifier_token UNIQUE (team_id, token)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_team_identifiers_team_id ON team_identifiers(team_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_team_identifiers_team_normalized ON team_identifiers(team_id, normalized_token)")

    # ticket_skill_analyses: cached per-ticket skill/domain vectors
    op.execute("""
        CREATE TABLE IF NOT EXISTS ticket_skill_analyses (
            id                  UUID PRIMARY KEY,
            ticket_id           UUID NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
            skill_vector        JSONB NOT NULL DEFAULT '{}'::jsonb,
            domain_vector       JSONB NOT NULL DEFAULT '{}'::jsonb,
            matched_identifiers JSONB NOT NULL DEFAULT '[]'::jsonb,
            analyzed_at         TIMESTAMP NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_ticket_skill_analysis UNIQUE (ticket_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_ticket_skill_analyses_ticket_id ON ticket_skill_analyses(ticket_id)")

    # developers: per-skill rating JSON (e.g. {"react": 0.8, "postgres": 0.6})
    op.execute("ALTER TABLE developers ADD COLUMN IF NOT EXISTS skill_ratings JSONB NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE developers DROP COLUMN IF EXISTS skill_ratings")
    op.execute("DROP INDEX IF EXISTS ix_ticket_skill_analyses_ticket_id")
    op.execute("DROP TABLE IF EXISTS ticket_skill_analyses")
    op.execute("DROP INDEX IF EXISTS ix_team_identifiers_team_normalized")
    op.execute("DROP INDEX IF EXISTS ix_team_identifiers_team_id")
    op.execute("DROP TABLE IF EXISTS team_identifiers")
