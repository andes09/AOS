"""add tickets and team_members tables

Revision ID: 0003
Revises: 0002
Create Date: 2026-03-25
"""
from alembic import op
import sqlalchemy as sa

revision = 'init004'
down_revision = 'init003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS team_members (
            id UUID PRIMARY KEY,
            team_id UUID NOT NULL REFERENCES teams(id),
            jira_account_id VARCHAR(255) NOT NULL,
            display_name VARCHAR(255) NOT NULL,
            email VARCHAR(255)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_team_members_team_id ON team_members(team_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_team_members_jira_account_id ON team_members(jira_account_id)")

    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'ticketstatus') THEN
                CREATE TYPE ticketstatus AS ENUM ('TODO','IN_PROGRESS','IN_REVIEW','DONE','CANCELLED');
            END IF;
        END $$
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            id UUID PRIMARY KEY,
            sprint_id UUID NOT NULL REFERENCES sprints(id),
            team_id UUID NOT NULL REFERENCES teams(id),
            assignee_id UUID REFERENCES team_members(id),
            jira_issue_id VARCHAR(100) NOT NULL UNIQUE,
            jira_issue_key VARCHAR(50),
            title TEXT NOT NULL,
            status ticketstatus NOT NULL DEFAULT 'TODO',
            ticket_type VARCHAR(100),
            story_points_estimated FLOAT,
            time_estimate_hours FLOAT,
            time_actual_hours FLOAT,
            labels JSON,
            completed_at TIMESTAMP,
            jira_updated_at TIMESTAMP,
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_tickets_sprint_id ON tickets(sprint_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tickets_team_id ON tickets(team_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tickets_assignee_id ON tickets(assignee_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tickets_jira_issue_id ON tickets(jira_issue_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS tickets")
    op.execute("DROP TYPE IF EXISTS ticketstatus")
    op.execute("DROP TABLE IF EXISTS team_members")
