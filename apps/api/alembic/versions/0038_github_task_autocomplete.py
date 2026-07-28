"""github task autocomplete — tasks.short_id/completed_at, organizations.next_task_seq, github_activity_events

Revision ID: 0038
Revises: 0037
Create Date: 2026-07-28

GitHub-App-native redesign of docs/plans/2026-07-20-github-task-autocomplete.md
(see that file's "Implementation Notes" header for the full rationale): no
per-repo webhook registration, no github_repo_sync_state table/sync_mode
split, no poll-fallback beat job. One app-level webhook covers every
installed repo; github_activity_events' own MAX(occurred_at) per
(organization_id, repo_full_name) serves as the reconciliation sweep's
cursor, so there's no separate sync-state table to keep consistent.
"""
import re

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0038'
down_revision = '0037'
branch_labels = None
depends_on = None


def _prefix_for(slug: str | None) -> str:
    """Mirrors src/services/task_ids.py's `_short_id_prefix` exactly — kept
    duplicated here (rather than imported) since migrations must not depend
    on application code that can change shape after this migration is
    written and applied."""
    alnum = re.sub(r"[^A-Za-z0-9]", "", slug or "").upper()
    return alnum[:8] or "TASK"


def _backfill_short_ids(bind) -> None:
    """Assign short_id to every existing task, in creation order, per org —
    and bring each org's next_task_seq up to match so new tasks continue the
    same sequence rather than colliding with backfilled ones."""
    orgs = bind.execute(sa.text("SELECT id, slug FROM organizations")).fetchall()
    for org_id, slug in orgs:
        prefix = _prefix_for(slug)
        rows = bind.execute(
            sa.text(
                """
                SELECT t.id FROM tasks t
                JOIN milestones m ON t.milestone_id = m.id
                JOIN projects p ON m.project_id = p.id
                JOIN teams tm ON p.team_id = tm.id
                WHERE tm.organization_id = :org_id
                ORDER BY t.created_at, t.id
                """
            ),
            {"org_id": org_id},
        ).fetchall()
        seq = 0
        for (task_id,) in rows:
            seq += 1
            bind.execute(
                sa.text("UPDATE tasks SET short_id = :sid WHERE id = :tid"),
                {"sid": f"{prefix}-{seq}", "tid": task_id},
            )
        if seq:
            bind.execute(
                sa.text("UPDATE organizations SET next_task_seq = :seq WHERE id = :org_id"),
                {"seq": seq, "org_id": org_id},
            )


def upgrade() -> None:
    op.add_column('tasks', sa.Column('short_id', sa.String(length=20), nullable=True))
    # Plain (non-unique) index: short_id is only *practically* unique per org
    # via the atomic Organization.next_task_seq counter — see the column's
    # docstring in src/models/task.py for why a global unique constraint
    # would be the wrong invariant here.
    op.create_index('ix_tasks_short_id', 'tasks', ['short_id'], unique=False)
    op.add_column('tasks', sa.Column('completed_at', sa.DateTime(), nullable=True))

    op.add_column(
        'organizations',
        sa.Column('next_task_seq', sa.Integer(), nullable=False, server_default='0'),
    )

    op.create_table(
        'github_activity_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('repo_full_name', sa.String(length=255), nullable=False),
        sa.Column('event_type', sa.String(length=20), nullable=False),
        sa.Column('external_id', sa.String(length=255), nullable=False),
        sa.Column('branch', sa.String(length=255), nullable=True),
        sa.Column('title_or_message', sa.Text(), nullable=True),
        sa.Column('author_login', sa.String(length=255), nullable=True),
        sa.Column('url', sa.String(length=500), nullable=True),
        sa.Column('matched_task_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('occurred_at', sa.DateTime(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['matched_task_id'], ['tasks.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'organization_id', 'repo_full_name', 'event_type', 'external_id',
            name='uq_github_activity_events_org_repo_type_external_id',
        ),
    )
    op.create_index('ix_github_activity_events_organization_id', 'github_activity_events', ['organization_id'])
    op.create_index('ix_github_activity_events_matched_task_id', 'github_activity_events', ['matched_task_id'])
    op.create_index('ix_github_activity_events_occurred_at', 'github_activity_events', ['occurred_at'])
    op.create_index(
        'ix_github_activity_events_org_repo_occurred_at',
        'github_activity_events',
        ['organization_id', 'repo_full_name', 'occurred_at'],
    )

    _backfill_short_ids(op.get_bind())


def downgrade() -> None:
    op.drop_table('github_activity_events')
    op.drop_column('organizations', 'next_task_seq')
    op.drop_column('tasks', 'completed_at')
    op.drop_index('ix_tasks_short_id', table_name='tasks')
    op.drop_column('tasks', 'short_id')
