"""DB foundations — unique constraint on team_members(team_id, jira_account_id)

Revision ID: 0005
Revises: init005
Create Date: 2026-04-02
"""
from alembic import op

revision = '0005'
down_revision = 'init005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_team_member_jira'
                  AND conrelid = 'team_members'::regclass
            ) THEN
                ALTER TABLE team_members ADD CONSTRAINT uq_team_member_jira
                    UNIQUE (team_id, jira_account_id);
            END IF;
        END $$
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE team_members DROP CONSTRAINT IF EXISTS uq_team_member_jira"
    )
