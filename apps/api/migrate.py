"""
Startup migration script that bypasses Alembic's file-discovery to handle
the case where alembic_version records a revision the container can't find.

Runs the actual SQL for each migration idempotently (IF NOT EXISTS / ADD COLUMN
with existence check), then stamps alembic_version to the correct head.
"""
print("=== MIGRATE.PY RUNNING (commit 2026-03-28) ===", flush=True)

import asyncio
import sys
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text


HEAD = "0015"

MIGRATIONS = [
    # (revision_id, sql_statements)
    ("init001", [
        """
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'sprintstatus') THEN
                CREATE TYPE sprintstatus AS ENUM ('PLANNING','ACTIVE','COMPLETED','CANCELLED');
            END IF;
        END $$
        """,
        """
        CREATE TABLE IF NOT EXISTS organizations (
            id                       UUID PRIMARY KEY,
            clerk_org_id             VARCHAR(255) NOT NULL UNIQUE,
            name                     VARCHAR(255) NOT NULL,
            slug                     VARCHAR(100) NOT NULL UNIQUE,
            encrypted_anthropic_key  TEXT,
            use_managed_key          BOOLEAN   NOT NULL DEFAULT FALSE,
            created_at               TIMESTAMP NOT NULL DEFAULT NOW(),
            updated_at               TIMESTAMP NOT NULL DEFAULT NOW()
        )
        """,
        """CREATE INDEX IF NOT EXISTS ix_organizations_clerk_org_id ON organizations(clerk_org_id)""",
        """CREATE INDEX IF NOT EXISTS ix_organizations_slug ON organizations(slug)""",
        """
        CREATE TABLE IF NOT EXISTS teams (
            id                  UUID PRIMARY KEY,
            organization_id     UUID NOT NULL REFERENCES organizations(id),
            name                VARCHAR(255) NOT NULL,
            jira_board_id       VARCHAR(100),
            sprint_length_days  INTEGER   NOT NULL DEFAULT 14,
            created_at          TIMESTAMP NOT NULL DEFAULT NOW()
        )
        """,
        """CREATE INDEX IF NOT EXISTS ix_teams_organization_id ON teams(organization_id)""",
        """
        CREATE TABLE IF NOT EXISTS developers (
            id              UUID PRIMARY KEY,
            team_id         UUID NOT NULL REFERENCES teams(id),
            clerk_user_id   VARCHAR(255),
            name            VARCHAR(255) NOT NULL,
            email           VARCHAR(255),
            role            VARCHAR(100),
            is_active       BOOLEAN   NOT NULL DEFAULT TRUE,
            created_at      TIMESTAMP NOT NULL DEFAULT NOW()
        )
        """,
        """CREATE INDEX IF NOT EXISTS ix_developers_team_id ON developers(team_id)""",
        """CREATE INDEX IF NOT EXISTS ix_developers_clerk_user_id ON developers(clerk_user_id)""",
        """
        CREATE TABLE IF NOT EXISTS jira_connections (
            id                        UUID PRIMARY KEY,
            organization_id           UUID NOT NULL REFERENCES organizations(id),
            jira_cloud_id             VARCHAR(255) NOT NULL,
            jira_cloud_url            VARCHAR(500) NOT NULL,
            encrypted_access_token    TEXT NOT NULL,
            encrypted_refresh_token   TEXT NOT NULL,
            token_expires_at          TIMESTAMP,
            scopes                    JSON,
            is_active                 BOOLEAN   NOT NULL DEFAULT TRUE,
            last_synced_at            TIMESTAMP,
            created_at                TIMESTAMP NOT NULL DEFAULT NOW()
        )
        """,
        """CREATE INDEX IF NOT EXISTS ix_jira_connections_organization_id ON jira_connections(organization_id)""",
        """
        CREATE TABLE IF NOT EXISTS sprints (
            id                 UUID PRIMARY KEY,
            team_id            UUID NOT NULL REFERENCES teams(id),
            jira_sprint_id     VARCHAR(100),
            name               VARCHAR(255) NOT NULL,
            start_date         DATE,
            end_date           DATE,
            committed_points   FLOAT,
            delivered_points   FLOAT,
            status             sprintstatus NOT NULL DEFAULT 'PLANNING',
            created_at         TIMESTAMP    NOT NULL DEFAULT NOW()
        )
        """,
        """CREATE INDEX IF NOT EXISTS ix_sprints_team_id ON sprints(team_id)""",
        """CREATE INDEX IF NOT EXISTS ix_sprints_jira_sprint_id ON sprints(jira_sprint_id)""",
        """
        CREATE TABLE IF NOT EXISTS sprint_tickets (
            id                UUID PRIMARY KEY,
            sprint_id         UUID NOT NULL REFERENCES sprints(id),
            ticket_id         VARCHAR(100) NOT NULL,
            assignee_id       UUID REFERENCES developers(id),
            estimated_points  FLOAT,
            actual_points     FLOAT,
            completed         BOOLEAN   NOT NULL DEFAULT FALSE,
            slip_cause        VARCHAR(100),
            created_at        TIMESTAMP NOT NULL DEFAULT NOW()
        )
        """,
        """CREATE INDEX IF NOT EXISTS ix_sprint_tickets_sprint_id ON sprint_tickets(sprint_id)""",
        """CREATE INDEX IF NOT EXISTS ix_sprint_tickets_ticket_id ON sprint_tickets(ticket_id)""",
        """CREATE INDEX IF NOT EXISTS ix_sprint_tickets_assignee_id ON sprint_tickets(assignee_id)""",
        """
        CREATE TABLE IF NOT EXISTS developer_velocity_profiles (
            id                     UUID PRIMARY KEY,
            developer_id           UUID NOT NULL REFERENCES developers(id),
            team_id                UUID NOT NULL REFERENCES teams(id),
            ticket_type            VARCHAR(100),
            domain                 VARCHAR(255),
            mean_completion_days   FLOAT,
            std_dev                FLOAT,
            sample_size            INTEGER   NOT NULL DEFAULT 0,
            sprint_count           INTEGER   NOT NULL DEFAULT 0,
            created_at             TIMESTAMP NOT NULL DEFAULT NOW(),
            updated_at             TIMESTAMP NOT NULL DEFAULT NOW()
        )
        """,
        """CREATE INDEX IF NOT EXISTS ix_dev_velocity_developer_id ON developer_velocity_profiles(developer_id)""",
        """CREATE INDEX IF NOT EXISTS ix_dev_velocity_team_id ON developer_velocity_profiles(team_id)""",
    ]),
    # init002 historically attempted `ALTER TABLE sprints ADD COLUMN alert_sent`,
    # but no such column exists on the Sprint model — sprint_alerts is a separate
    # table created in revision 0015 below.
    ("init002", []),
    ("init003", [
        """ALTER TABLE teams ADD COLUMN IF NOT EXISTS jira_project_key VARCHAR(100)""",
    ]),
    ("init004", [
        """
        CREATE TABLE IF NOT EXISTS team_members (
            id UUID PRIMARY KEY,
            team_id UUID NOT NULL REFERENCES teams(id),
            jira_account_id VARCHAR(255) NOT NULL,
            display_name VARCHAR(255) NOT NULL,
            email VARCHAR(255)
        )
        """,
        """CREATE INDEX IF NOT EXISTS ix_team_members_team_id ON team_members(team_id)""",
        """CREATE INDEX IF NOT EXISTS ix_team_members_jira_account_id ON team_members(jira_account_id)""",
        """
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'ticketstatus') THEN
                CREATE TYPE ticketstatus AS ENUM ('TODO','IN_PROGRESS','IN_REVIEW','DONE','CANCELLED');
            END IF;
        END $$
        """,
        """
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
            components JSON,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            completed_at TIMESTAMP,
            jira_updated_at TIMESTAMP
        )
        """,
        """CREATE INDEX IF NOT EXISTS ix_tickets_sprint_id ON tickets(sprint_id)""",
        """CREATE INDEX IF NOT EXISTS ix_tickets_team_id ON tickets(team_id)""",
        """CREATE INDEX IF NOT EXISTS ix_tickets_assignee_id ON tickets(assignee_id)""",
        """CREATE INDEX IF NOT EXISTS ix_tickets_jira_issue_id ON tickets(jira_issue_id)""",
    ]),
    ("init005", [
        """ALTER TABLE tickets ALTER COLUMN sprint_id DROP NOT NULL""",
    ]),
    ("0005", [
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
        """,
    ]),
    ("0006", [
    "ALTER TABLE developers ADD COLUMN IF NOT EXISTS app_role VARCHAR(20) NOT NULL DEFAULT 'developer'"
    ]),
    ("0007", [
        """
        CREATE TABLE IF NOT EXISTS ticket_analyses (
          id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          team_id         UUID NOT NULL REFERENCES teams(id),
          ticket_key      VARCHAR(50) NOT NULL,
          ticket_title    TEXT,
          readiness_score INT,
          status          VARCHAR(20) NOT NULL,
          issues          JSONB,
          suggestions     JSONB,
          analyzed_at     TIMESTAMP NOT NULL DEFAULT now(),
          CONSTRAINT uq_ticket_analysis UNIQUE (team_id, ticket_key)
        )
        """,
    ]),
    ("0008", [
        """
        CREATE TABLE IF NOT EXISTS dependencies (
          id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          team_id         UUID NOT NULL REFERENCES teams(id),
          ticket_key      VARCHAR(50) NOT NULL,
          ticket_title    TEXT,
          blocked_by_key  VARCHAR(50),
          dependency_type VARCHAR(30) NOT NULL,
          risk_level      VARCHAR(10) NOT NULL,
          description     TEXT,
          source          VARCHAR(10) NOT NULL DEFAULT 'manual',
          resolved_at     TIMESTAMP,
          created_at      TIMESTAMP NOT NULL DEFAULT now()
        )
        """,
        """CREATE INDEX IF NOT EXISTS idx_dep_team_resolved ON dependencies(team_id, resolved_at)""",
    ]),
    ("0009", [
        """
        CREATE TABLE IF NOT EXISTS retrospectives (
          id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          sprint_id        UUID NOT NULL UNIQUE REFERENCES sprints(id),
          team_id          UUID NOT NULL REFERENCES teams(id),
          generated_at     TIMESTAMP NOT NULL DEFAULT now(),
          went_well        JSONB,
          went_poorly      JSONB,
          action_items     JSONB,
          velocity_summary JSONB
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS retro_patterns (
          id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          team_id               UUID NOT NULL REFERENCES teams(id),
          pattern_type          VARCHAR(30) NOT NULL,
          description           TEXT,
          occurrence_count      INT NOT NULL DEFAULT 1,
          first_seen_sprint_id  UUID REFERENCES sprints(id),
          last_seen_sprint_id   UUID REFERENCES sprints(id),
          status                VARCHAR(10) NOT NULL DEFAULT 'active',
          affected_sprint_names JSONB
        )
        """,
        """CREATE INDEX IF NOT EXISTS idx_retro_patterns_team_status ON retro_patterns(team_id, status)""",
    ]),
    ("0010", [
        """ALTER TABLE tickets ADD COLUMN IF NOT EXISTS components JSON""",
    ]),
    ("0011", [
        """ALTER TABLE organizations ADD COLUMN IF NOT EXISTS onboarding_completed_at TIMESTAMP""",
        """ALTER TABLE teams ADD COLUMN IF NOT EXISTS jira_import_status VARCHAR(20) NOT NULL DEFAULT 'pending'""",
        """ALTER TABLE teams ADD COLUMN IF NOT EXISTS jira_import_sprints_imported INTEGER""",
        """
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
        """,
        """CREATE UNIQUE INDEX IF NOT EXISTS uq_invitation_token ON invitations(token)""",
        """CREATE INDEX IF NOT EXISTS ix_invitations_org_id ON invitations(organization_id)""",
        """CREATE INDEX IF NOT EXISTS ix_invitations_email ON invitations(email)""",
    ]),
    ("0012", [
        """ALTER TABLE teams ADD COLUMN IF NOT EXISTS meeting_overhead_pct FLOAT NOT NULL DEFAULT 0.0""",
        """
        CREATE TABLE IF NOT EXISTS developer_capacity_overrides (
            id           UUID PRIMARY KEY,
            developer_id UUID NOT NULL REFERENCES developers(id) ON DELETE CASCADE,
            sprint_id    UUID REFERENCES sprints(id) ON DELETE CASCADE,
            capacity_pct FLOAT,
            pto_days     FLOAT,
            notes        TEXT,
            created_by   VARCHAR(255) NOT NULL,
            created_at   TIMESTAMP NOT NULL DEFAULT NOW()
        )
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_dev_capacity_sprint
            ON developer_capacity_overrides(developer_id, sprint_id)
            WHERE sprint_id IS NOT NULL
        """,
        """CREATE INDEX IF NOT EXISTS ix_dev_capacity_dev_id ON developer_capacity_overrides(developer_id)""",
    ]),
    ("0014", [
        """
        CREATE TABLE IF NOT EXISTS team_access_grants (
            id           UUID PRIMARY KEY,
            developer_id UUID NOT NULL REFERENCES developers(id) ON DELETE CASCADE,
            team_id      UUID NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
            granted_by   VARCHAR(255) NOT NULL,
            granted_at   TIMESTAMP NOT NULL DEFAULT NOW()
        )
        """,
        """CREATE UNIQUE INDEX IF NOT EXISTS uq_team_access_grant ON team_access_grants(developer_id, team_id)""",
        """CREATE INDEX IF NOT EXISTS ix_team_access_dev_id ON team_access_grants(developer_id)""",
        """
        CREATE TABLE IF NOT EXISTS slack_configs (
            id          UUID PRIMARY KEY,
            team_id     UUID NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
            webhook_url TEXT NOT NULL,
            channel     VARCHAR(100),
            alert_types JSONB NOT NULL DEFAULT '["high_risk_dependency","sprint_at_risk","retro_action_overdue"]',
            is_active   BOOLEAN NOT NULL DEFAULT TRUE,
            created_at  TIMESTAMP NOT NULL DEFAULT NOW()
        )
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_slack_config_team
            ON slack_configs(team_id) WHERE is_active = TRUE
        """,
    ]),
    ("0015", [
        """
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'alerttype') THEN
                CREATE TYPE alerttype AS ENUM (
                    'stalled_ticket','over_capacity','dependency_risk','spillover_prediction'
                );
            END IF;
        END $$
        """,
        """
        CREATE TABLE IF NOT EXISTS sprint_alerts (
            id                  UUID PRIMARY KEY,
            sprint_id           UUID NOT NULL REFERENCES sprints(id),
            team_id             UUID NOT NULL REFERENCES teams(id),
            type                alerttype NOT NULL,
            description         TEXT NOT NULL,
            recommended_action  TEXT NOT NULL,
            dismissed           BOOLEAN   NOT NULL DEFAULT FALSE,
            created_at          TIMESTAMP NOT NULL DEFAULT NOW()
        )
        """,
        """CREATE INDEX IF NOT EXISTS ix_sprint_alerts_sprint_id ON sprint_alerts(sprint_id)""",
        """CREATE INDEX IF NOT EXISTS ix_sprint_alerts_team_id ON sprint_alerts(team_id)""",
    ]),
]


async def run():
    from src.config import settings
    engine = create_async_engine(settings.database_url)

    async with engine.begin() as conn:
        # Ensure alembic_version table exists
        await conn.execute(text(
            "CREATE TABLE IF NOT EXISTS alembic_version "
            "(version_num VARCHAR(32) NOT NULL, CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
        ))

        result = await conn.execute(text("SELECT version_num FROM alembic_version"))
        applied = {row[0] for row in result.fetchall()}
        print(f"[migrate] Applied revisions in DB: {applied}")

        for revision_id, stmts in MIGRATIONS:
            if revision_id in applied:
                print(f"[migrate] {revision_id} already applied — skipping")
                continue
            print(f"[migrate] Applying {revision_id}...")
            for stmt in stmts:
                stmt = stmt.strip()
                if stmt:
                    await conn.execute(text(stmt))
            await conn.execute(
                text("INSERT INTO alembic_version (version_num) VALUES (:v) ON CONFLICT DO NOTHING"),
                {"v": revision_id},
            )
            print(f"[migrate] {revision_id} done")

        # Ensure DB is stamped at HEAD even if it was already there
        await conn.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:v) ON CONFLICT DO NOTHING"),
            {"v": HEAD},
        )
        print(f"[migrate] DB is at head ({HEAD})")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run())
