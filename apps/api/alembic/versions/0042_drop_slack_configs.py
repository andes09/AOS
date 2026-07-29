"""drop slack_configs table (slack alerts feature removed)

Revision ID: 0042
Revises: 0041
Create Date: 2026-07-29
"""
from alembic import op

revision = '0042'
down_revision = '0041'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS slack_configs")


def downgrade() -> None:
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
