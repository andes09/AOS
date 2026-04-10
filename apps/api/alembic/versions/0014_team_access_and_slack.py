"""team access grants and slack configs tables

Revision ID: 0014
Revises: 0012
Create Date: 2026-04-09
"""
from alembic import op

revision = '0014'
down_revision = '0012'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS team_access_grants (
            id           UUID PRIMARY KEY,
            developer_id UUID NOT NULL REFERENCES developers(id) ON DELETE CASCADE,
            team_id      UUID NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
            granted_by   VARCHAR(255) NOT NULL,
            granted_at   TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_team_access_grant
            ON team_access_grants(developer_id, team_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_team_access_dev_id
            ON team_access_grants(developer_id)
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS slack_configs (
            id          UUID PRIMARY KEY,
            team_id     UUID NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
            webhook_url TEXT NOT NULL,
            channel     VARCHAR(100),
            alert_types JSONB NOT NULL DEFAULT '["high_risk_dependency","sprint_at_risk","retro_action_overdue"]',
            is_active   BOOLEAN NOT NULL DEFAULT TRUE,
            created_at  TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_slack_config_team
            ON slack_configs(team_id) WHERE is_active = TRUE
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS slack_configs")
    op.execute("DROP TABLE IF EXISTS team_access_grants")
