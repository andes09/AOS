"""onboarding columns and invitations table

Revision ID: 0011
Revises: 0010
Create Date: 2026-04-09
"""
from alembic import op

revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE organizations
            ADD COLUMN IF NOT EXISTS onboarding_completed_at TIMESTAMP
    """)

    op.execute("""
        ALTER TABLE teams
            ADD COLUMN IF NOT EXISTS jira_import_status VARCHAR(20) NOT NULL DEFAULT 'pending'
    """)
    op.execute("""
        ALTER TABLE teams
            ADD COLUMN IF NOT EXISTS jira_import_sprints_imported INTEGER
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS invitations (
            id              UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            team_id         UUID NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
            inviter_id      VARCHAR(255) NOT NULL,
            email           VARCHAR(255) NOT NULL,
            role            VARCHAR(20)  NOT NULL DEFAULT 'developer',
            token           VARCHAR(64)  NOT NULL,
            status          VARCHAR(20)  NOT NULL DEFAULT 'pending',
            accepted_at     TIMESTAMP,
            expires_at      TIMESTAMP    NOT NULL,
            created_at      TIMESTAMP    NOT NULL DEFAULT NOW()
        )
    """)

    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_invitation_token
            ON invitations(token)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_invitations_org_id
            ON invitations(organization_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_invitations_email
            ON invitations(email)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS invitations")
    op.execute("ALTER TABLE teams DROP COLUMN IF EXISTS jira_import_sprints_imported")
    op.execute("ALTER TABLE teams DROP COLUMN IF EXISTS jira_import_status")
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS onboarding_completed_at")
