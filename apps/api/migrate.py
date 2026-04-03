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


HEAD = "0009"

MIGRATIONS = [
    # (revision_id, sql_statements)
    ("init001", []),   # handled by initial schema; presence checked below
    ("init002", [
        """ALTER TABLE sprints ADD COLUMN IF NOT EXISTS alert_sent BOOLEAN NOT NULL DEFAULT FALSE""",
    ]),
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
