"""oauth_states table for cross-instance OAuth 2.0 state management

Replaces the in-process `_oauth_states` dict in the Jira OAuth router with a
durable DB-backed store that survives across multiple API worker instances.
Each row is short-lived (10-minute TTL) and is deleted on first use or on
expiry via best-effort cleanup in the callback handler.

Revision ID: 0022
Revises: 0021
Create Date: 2026-05-29
"""
from alembic import op


revision = '0022'
down_revision = '0021'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS oauth_states (
            state       VARCHAR(64) PRIMARY KEY,
            user_id     VARCHAR(255) NOT NULL,
            org_id      VARCHAR(255) NOT NULL,
            return_to   VARCHAR(255) NOT NULL DEFAULT '/onboarding',
            expires_at  TIMESTAMP NOT NULL
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_oauth_states_expires_at "
        "ON oauth_states(expires_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_oauth_states_expires_at")
    op.execute("DROP TABLE IF EXISTS oauth_states")
