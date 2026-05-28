"""ticket revisions audit table (Initiative B, SB-2)

Audit trail for every Scope-Cop-suggested ticket edit that the user actually
pushes to Jira via the new inline-refinement flow (Initiative B). One row per
ticket per commit. `suggested_revision` is what Scope Cop proposed,
`applied_revision` is what the user pushed (may differ if they edited the
suggestion in B8), and `original_jira_state` is a pre-edit snapshot of the
Jira fields we touch (title, description, AC, story points, assignee, sprint
id) so a future rollback feature can restore exactly what was there.

There is no `users` table in this codebase (auth is Clerk-driven, actors are
resolved to `developers.id` or left null) — `applied_by` is a bare UUID with
no FK, matching the precedent set by `sprint_plan_overrides.created_by`.

`ticket_id` is FK'd to `tickets` when we have an ingested ticket row, but is
nullable + ON DELETE SET NULL because the new flow can act on Jira keys we
have not yet ingested. `ticket_key` is always populated and is what indexes
target.

Revision ID: 0021
Revises: 0020
Create Date: 2026-05-27
"""
from alembic import op


revision = '0021'
down_revision = '0020'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS ticket_revisions (
            id                    UUID PRIMARY KEY,
            team_id               UUID NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
            ticket_id             UUID NULL REFERENCES tickets(id) ON DELETE SET NULL,
            ticket_key            VARCHAR(50) NOT NULL,
            suggested_revision    JSONB NOT NULL DEFAULT '{}'::jsonb,
            applied_revision      JSONB NOT NULL DEFAULT '{}'::jsonb,
            original_jira_state   JSONB NOT NULL DEFAULT '{}'::jsonb,
            applied_at            TIMESTAMP NOT NULL DEFAULT NOW(),
            applied_by            UUID NULL
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_ticket_revisions_team_key "
        "ON ticket_revisions(team_id, ticket_key)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_ticket_revisions_applied_at "
        "ON ticket_revisions(applied_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_ticket_revisions_applied_at")
    op.execute("DROP INDEX IF EXISTS ix_ticket_revisions_team_key")
    op.execute("DROP TABLE IF EXISTS ticket_revisions")
