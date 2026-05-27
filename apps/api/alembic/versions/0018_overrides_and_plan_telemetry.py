"""sprint plan overrides and plan-quality telemetry columns

Revision ID: 0018
Revises: 0017
Create Date: 2026-05-27
"""
from alembic import op

revision = '0018'
down_revision = '0017'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # sprint_plan_overrides: captures every lead-driven assignment edit so Sprint
    # Brain can learn from overrides and so M8d can compute plan-quality telemetry.
    op.execute("""
        CREATE TABLE IF NOT EXISTS sprint_plan_overrides (
            id                       UUID PRIMARY KEY,
            sprint_id                UUID NOT NULL REFERENCES sprints(id) ON DELETE CASCADE,
            ticket_id                UUID NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
            action                   VARCHAR(20) NOT NULL,
            original_developer_id    UUID NULL REFERENCES developers(id) ON DELETE SET NULL,
            new_developer_id         UUID NULL REFERENCES developers(id) ON DELETE SET NULL,
            reason_code              VARCHAR(30) NULL,
            reason_text              TEXT NULL,
            created_by               UUID NULL,
            created_at               TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_sprint_plan_overrides_sprint_id ON sprint_plan_overrides(sprint_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_sprint_plan_overrides_ticket_new ON sprint_plan_overrides(ticket_id, new_developer_id)")

    # Sprint plan-quality telemetry columns consumed by M8d (SA-15).
    op.execute("ALTER TABLE sprints ADD COLUMN IF NOT EXISTS plan_override_rate FLOAT NULL")
    op.execute("ALTER TABLE sprints ADD COLUMN IF NOT EXISTS plan_overrides_by_reason JSONB NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE sprints DROP COLUMN IF EXISTS plan_overrides_by_reason")
    op.execute("ALTER TABLE sprints DROP COLUMN IF EXISTS plan_override_rate")
    op.execute("DROP INDEX IF EXISTS ix_sprint_plan_overrides_ticket_new")
    op.execute("DROP INDEX IF EXISTS ix_sprint_plan_overrides_sprint_id")
    op.execute("DROP TABLE IF EXISTS sprint_plan_overrides")
