"""ticket_complexity_cache table for skipping Claude complexity calls on warm runs

Caches Claude's `analyse_tickets` output keyed by a sha256 of the prompt-relevant
ticket fields (title, description, story_points, priority, labels). Content-hash
means automatic invalidation when ticket text changes. Model column ensures a
model swap invalidates old entries (different model → potentially different
analysis). No team_id: identical ticket content across teams can safely share.

Revision ID: 0023
Revises: 0022
Create Date: 2026-06-02
"""
from alembic import op


revision = '0023'
down_revision = '0022'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS ticket_complexity_cache (
            content_hash    VARCHAR(64) NOT NULL,
            model           VARCHAR(64) NOT NULL,
            complexity_json JSONB NOT NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (content_hash, model)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_ticket_complexity_cache_created_at "
        "ON ticket_complexity_cache(created_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_ticket_complexity_cache_created_at")
    op.execute("DROP TABLE IF EXISTS ticket_complexity_cache")
