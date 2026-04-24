"""organizations.is_simulated and tickets.is_carryover

Revision ID: 0015
Revises: 0014
Create Date: 2026-04-19

Additive-only. Both columns default FALSE so existing rows are unaffected.

- organizations.is_simulated: marks orgs created by the TAWOS importer (or the
  simulator) so --reset can scope deletions without touching real customer data.
- tickets.is_carryover: TRUE for tickets that crossed sprint boundaries in the
  source data. Materialized as a column (not derived) so Sprint Brain /
  Velocity Mirror / retros can filter on it without re-computing.
"""
from alembic import op

revision = '0015'
down_revision = '0014'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE organizations
            ADD COLUMN IF NOT EXISTS is_simulated BOOLEAN NOT NULL DEFAULT FALSE
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_organizations_is_simulated
            ON organizations(is_simulated) WHERE is_simulated = TRUE
    """)

    op.execute("""
        ALTER TABLE tickets
            ADD COLUMN IF NOT EXISTS is_carryover BOOLEAN NOT NULL DEFAULT FALSE
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_tickets_is_carryover
            ON tickets(is_carryover) WHERE is_carryover = TRUE
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_tickets_is_carryover")
    op.execute("ALTER TABLE tickets DROP COLUMN IF EXISTS is_carryover")
    op.execute("DROP INDEX IF EXISTS ix_organizations_is_simulated")
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS is_simulated")
