"""merge team_members into developers

Adds jira_account_id to developers, migrates all team_members rows in,
remaps tickets.assignee_id FK, and drops team_members.

NOTE: downgrade is best-effort (data cannot be fully unsplit after merge).

Revision ID: 0025
Revises: 0024
Create Date: 2026-06-17
"""
from alembic import op

revision = '0025'
down_revision = '0024'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Add jira_account_id to developers ────────────────────────────────
    op.execute("ALTER TABLE developers ADD COLUMN IF NOT EXISTS jira_account_id VARCHAR(255) NULL")
    op.execute("CREATE INDEX IF NOT EXISTS ix_developers_jira_account_id ON developers(jira_account_id)")
    # Partial unique index — NULLs are excluded, so existing developer rows
    # without a jira_account_id don't conflict with each other.
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_developers_team_jira
        ON developers(team_id, jira_account_id)
        WHERE jira_account_id IS NOT NULL
    """)

    # ── 2. Build a temp mapping of matched team_members → developers ─────────
    # A match is an email overlap within the same team (case-insensitive).
    op.execute("""
        CREATE TEMP TABLE _tm_match AS
        SELECT tm.id     AS tm_id,
               d.id      AS dev_id,
               tm.jira_account_id
        FROM   team_members tm
        JOIN   developers   d
               ON  d.team_id = tm.team_id
               AND LOWER(d.email) = LOWER(tm.email)
        WHERE  tm.email IS NOT NULL
    """)

    # ── 3. Stamp jira_account_id onto matched developers ────────────────────
    op.execute("""
        UPDATE developers d
        SET    jira_account_id = m.jira_account_id
        FROM   _tm_match m
        WHERE  d.id = m.dev_id
    """)

    # ── 4. Insert unmatched team_members as new developer rows ──────────────
    # Reuse the team_member UUID so that tickets.assignee_id values that
    # already point at these rows remain valid without any UPDATE.
    op.execute("""
        INSERT INTO developers
               (id, team_id, name, email, jira_account_id, is_active, app_role, created_at)
        SELECT tm.id,
               tm.team_id,
               tm.display_name,
               tm.email,
               tm.jira_account_id,
               TRUE,
               'developer',
               NOW()
        FROM   team_members tm
        WHERE  tm.id NOT IN (SELECT tm_id FROM _tm_match)
        ON CONFLICT DO NOTHING
    """)

    # ── 5. Remap tickets.assignee_id for matched team_members ───────────────
    # (Unmatched ones reused their UUID above, so no update needed for them.)
    op.execute("""
        UPDATE tickets
        SET    assignee_id = m.dev_id
        FROM   _tm_match m
        WHERE  tickets.assignee_id = m.tm_id
    """)

    # ── 6. Swap the FK on tickets.assignee_id ────────────────────────────────
    op.execute("ALTER TABLE tickets DROP CONSTRAINT IF EXISTS tickets_assignee_id_fkey")
    op.execute("""
        ALTER TABLE tickets
        ADD CONSTRAINT tickets_assignee_id_fkey
        FOREIGN KEY (assignee_id) REFERENCES developers(id) ON DELETE SET NULL
    """)

    # ── 7. Drop team_members (no longer referenced) ──────────────────────────
    op.execute("DROP TABLE IF EXISTS team_members")


def downgrade() -> None:
    # Recreate team_members with original structure
    op.execute("""
        CREATE TABLE IF NOT EXISTS team_members (
            id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            team_id          UUID NOT NULL REFERENCES teams(id),
            jira_account_id  VARCHAR(255) NOT NULL,
            display_name     VARCHAR(255) NOT NULL,
            email            VARCHAR(255) NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_team_members_team_id ON team_members(team_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_team_members_jira_account_id ON team_members(jira_account_id)")
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_team_members_team_jira
        ON team_members(team_id, jira_account_id)
    """)

    # Re-populate team_members from developers that have a jira_account_id
    op.execute("""
        INSERT INTO team_members (id, team_id, jira_account_id, display_name, email)
        SELECT id, team_id, jira_account_id, name, email
        FROM   developers
        WHERE  jira_account_id IS NOT NULL
        ON CONFLICT DO NOTHING
    """)

    # Restore tickets FK to team_members (best-effort — only works for rows that
    # were originally unmatched and kept their UUID)
    op.execute("ALTER TABLE tickets DROP CONSTRAINT IF EXISTS tickets_assignee_id_fkey")
    op.execute("""
        ALTER TABLE tickets
        ADD CONSTRAINT tickets_assignee_id_fkey
        FOREIGN KEY (assignee_id) REFERENCES team_members(id) ON DELETE SET NULL
    """)

    # Remove jira_account_id from developers
    op.execute("DROP INDEX IF EXISTS uq_developers_team_jira")
    op.execute("DROP INDEX IF EXISTS ix_developers_jira_account_id")
    op.execute("ALTER TABLE developers DROP COLUMN IF EXISTS jira_account_id")
