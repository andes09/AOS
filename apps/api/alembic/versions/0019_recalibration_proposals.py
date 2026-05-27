"""recalibration proposals pipeline (M8c)

Revision ID: 0019
Revises: 0018
Create Date: 2026-05-27
"""
from alembic import op


revision = '0019'
down_revision = '0018'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # recalibration_proposals: pending suggestions emitted by the override
    # analyzer (M8c). Each row is its own audit record — when a lead approves
    # or dismisses, decided_at + decided_by capture who/when, and evidence
    # JSONB stores the SprintPlanOverride ids that triggered the proposal.
    op.execute("""
        CREATE TABLE IF NOT EXISTS recalibration_proposals (
            id               UUID PRIMARY KEY,
            team_id          UUID NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
            kind             VARCHAR(20) NOT NULL,
            developer_id     UUID NULL REFERENCES developers(id) ON DELETE CASCADE,
            identifier_id    UUID NULL REFERENCES team_identifiers(id) ON DELETE CASCADE,
            skill            VARCHAR(100) NULL,
            current_value    FLOAT NULL,
            suggested_value  FLOAT NULL,
            suggested_skill  VARCHAR(100) NULL,
            evidence         JSONB NOT NULL DEFAULT '[]'::jsonb,
            status           VARCHAR(15) NOT NULL DEFAULT 'pending',
            decided_at       TIMESTAMP NULL,
            decided_by       UUID NULL,
            created_at       TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_recalibration_proposals_team_status "
        "ON recalibration_proposals(team_id, status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_recalibration_proposals_target "
        "ON recalibration_proposals(developer_id, identifier_id, skill)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_recalibration_proposals_target")
    op.execute("DROP INDEX IF EXISTS ix_recalibration_proposals_team_status")
    op.execute("DROP TABLE IF EXISTS recalibration_proposals")
