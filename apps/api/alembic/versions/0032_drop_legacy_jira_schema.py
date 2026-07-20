"""drop legacy Jira schema — dead tables and columns

B2-B7 (merged: PR #29, "chore/legacy-teardown-b2-b7") deleted every
router/service that read or wrote the Jira sync integration, Scope Cop,
and dependency-radar features, but deliberately left the tables and
model files in place ("models-stay" rule, schema removal deferred to
this step). This migration is that deferred step.

Scope was verified against the actually-merged code, not the original
ask: `tickets`, `sprints`, `sprint_tickets`, and `developer_velocity_profiles`
are still live (sprints/alerts/capacity/teams/developers/users routers)
and are intentionally NOT touched here. Only tables/columns with zero
remaining Python references are dropped.

Production data destroyed by this migration, and why that's acceptable:
  - `dependencies`      — dependency-radar rows. Derived analysis of Jira
                           issue links; reproducible from Jira if ever
                           needed again, not a system of record.
  - `ticket_analyses`   — Scope Cop readiness-check output. Derived LLM
                           analysis, regenerable, not a system of record.
  - `jira_connections`  — Jira OAuth tokens/connection state. The OAuth
                           app itself is gone (B7); these rows are inert
                           credentials with nothing left to authenticate.
  - `sync_status`       — Jira sync-run bookkeeping (one row per team).
                           Meaningless without the sync job that wrote it.
  - `teams.jira_board_id`, `teams.jira_project_key`,
    `teams.jira_import_status`, `teams.jira_import_sprints_imported` —
    Jira board/project linkage and one-time import progress counters.
  - `developers.jira_account_id` — Jira user linkage, used only by the
    now-deleted sync/matching code.
  - `developers.capacity_hours_per_week` — declared on the model since
    migration 0015 but never read anywhere; the live capacity feature
    (`services/capacity.py`) computes effective capacity from
    `team.meeting_overhead_pct` and `DeveloperCapacityOverride` instead.

`developers.skill_ratings` and `developers.domain_strengths` are kept —
despite sounding Jira-adjacent, they back the live, non-Jira
recalibration feature (`routers/recalibration.py`,
`services/override_analyzer.py`).

downgrade() recreates empty structures matching the schema as of this
migration. It does not and cannot restore dropped data.

Revision ID: 0032
Revises: 0031
Create Date: 2026-07-20
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0032'
down_revision = '0031'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── dead tables, in FK-safe order (no cross-references among these four) ──
    op.drop_table('sync_status')
    op.drop_table('ticket_analyses')
    op.drop_table('dependencies')
    op.drop_table('jira_connections')

    # ── teams: Jira board/project linkage + import progress counters ──────────
    op.drop_column('teams', 'jira_board_id')
    op.drop_column('teams', 'jira_project_key')
    op.drop_column('teams', 'jira_import_status')
    op.drop_column('teams', 'jira_import_sprints_imported')

    # ── developers: Jira account linkage + dead capacity column ───────────────
    # Both indexes were created via raw op.execute in migration 0025, not
    # SQLAlchemy index=True, so they don't cascade-drop with the column.
    op.drop_index('uq_developers_team_jira', table_name='developers')
    op.drop_index('ix_developers_jira_account_id', table_name='developers')
    op.drop_column('developers', 'jira_account_id')
    op.drop_column('developers', 'capacity_hours_per_week')


def downgrade() -> None:
    # ── developers: recreate columns + indexes (exact inverse order) ──────────
    op.add_column('developers', sa.Column('capacity_hours_per_week', sa.Integer(), nullable=True))
    op.add_column('developers', sa.Column('jira_account_id', sa.String(length=255), nullable=True))
    op.create_index('ix_developers_jira_account_id', 'developers', ['jira_account_id'])
    op.execute("""
        CREATE UNIQUE INDEX uq_developers_team_jira
        ON developers(team_id, jira_account_id)
        WHERE jira_account_id IS NOT NULL
    """)

    # ── teams: recreate columns ────────────────────────────────────────────────
    op.add_column('teams', sa.Column('jira_import_sprints_imported', sa.Integer(), nullable=True))
    op.add_column('teams', sa.Column('jira_import_status', sa.String(length=20), nullable=False, server_default='pending'))
    op.add_column('teams', sa.Column('jira_project_key', sa.String(length=100), nullable=True))
    op.add_column('teams', sa.Column('jira_board_id', sa.String(length=100), nullable=True))

    # ── dead tables: recreate empty (no data restore) ──────────────────────────
    op.create_table(
        'jira_connections',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id'), nullable=False),
        sa.Column('jira_cloud_id', sa.String(length=255), nullable=False),
        sa.Column('jira_cloud_url', sa.String(length=500), nullable=False),
        sa.Column('encrypted_access_token', sa.Text(), nullable=False),
        sa.Column('encrypted_refresh_token', sa.Text(), nullable=False),
        sa.Column('token_expires_at', sa.DateTime(), nullable=True),
        sa.Column('scopes', sa.JSON(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('last_synced_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_jira_connections_organization_id', 'jira_connections', ['organization_id'])

    op.create_table(
        'dependencies',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('team_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('teams.id'), nullable=False),
        sa.Column('ticket_key', sa.String(length=50), nullable=False),
        sa.Column('ticket_title', sa.Text(), nullable=True),
        sa.Column('blocked_by_key', sa.String(length=50), nullable=True),
        sa.Column('dependency_type', sa.String(), nullable=False),
        sa.Column('risk_level', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('source', sa.String(length=10), nullable=False),
        sa.Column('resolved_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('idx_dep_team_resolved', 'dependencies', ['team_id', 'resolved_at'])

    op.create_table(
        'ticket_analyses',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('team_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('teams.id'), nullable=False),
        sa.Column('ticket_key', sa.String(length=50), nullable=False),
        sa.Column('ticket_title', sa.Text(), nullable=True),
        sa.Column('readiness_score', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('issues', sa.JSON(), nullable=True),
        sa.Column('suggestions', sa.JSON(), nullable=True),
        sa.Column('suggested_revision', sa.JSON(), nullable=True),
        sa.Column('analyzed_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('team_id', 'ticket_key', name='uq_ticket_analysis'),
    )

    op.create_table(
        'sync_status',
        sa.Column('team_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('teams.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('state', sa.String(length=20), nullable=False, server_default='queued'),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('error_code', sa.String(length=50), nullable=True),
        sa.Column('error_message', sa.String(length=500), nullable=True),
        sa.Column('tickets_synced', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('members_synced', sa.Integer(), nullable=False, server_default='0'),
    )
