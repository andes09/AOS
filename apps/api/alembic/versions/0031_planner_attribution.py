"""planner — task attribution (assignee) + time blocking, developer lane colors

Adds the three things the revamped planner needs and the roadmap schema lacks:
who owns a task, when in the day it happens, and how long it takes. Plus a
stable per-developer color slot for the sidebar lanes.

Revision ID: 0031
Revises: 0030
Create Date: 2026-07-19
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0031'
down_revision = '0030'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── tasks: attribution + time ────────────────────────────────────────────
    # ON DELETE SET NULL, not CASCADE: removing a person must never delete their
    # work. Their tasks fall back to the neutral "unassigned" lane instead.
    op.add_column('tasks', sa.Column('assignee_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        'fk_tasks_assignee_id_developers', 'tasks', 'developers',
        ['assignee_id'], ['id'], ondelete='SET NULL',
    )
    op.create_index('ix_tasks_assignee_id', 'tasks', ['assignee_id'])

    # Naive TIME, never TIMETZ. "The 9:30am standup" is a wall-clock fact, not a
    # point on a timeline — attaching a zone here would make the same task read
    # as a different hour for teammates in other regions.
    op.add_column('tasks', sa.Column('scheduled_time', sa.Time(), nullable=True))

    # Nullable on purpose. NULL means "no explicit duration" and renders as a
    # compact chip; a server_default would make every pre-existing task silently
    # claim an hour of grid space it never asked for.
    op.add_column('tasks', sa.Column('duration_minutes', sa.Integer(), nullable=True))

    # Composite index matching the planner's dominant query: a day's tasks in
    # chronological order.
    op.create_index('ix_tasks_scheduled_date_time', 'tasks', ['scheduled_date', 'scheduled_time'])

    # ── developers: lane color + avatar ──────────────────────────────────────
    # server_default is required, not cosmetic: developers are created in four
    # places (services/invitation.py, routers/onboarding_v2.py, routers/
    # onboarding.py, routers/teams.py) and a bare NOT NULL would break them all.
    op.add_column(
        'developers',
        sa.Column('color_index', sa.SmallInteger(), nullable=False, server_default='0'),
    )
    op.add_column('developers', sa.Column('avatar_url', sa.String(length=500), nullable=True))

    # Backfill distinct colors per team so existing teams don't open the planner
    # to a wall of identical swatches. Sequential by creation order, wrapping at
    # the palette size (10 hues defined in apps/web/src/styles/tokens.css).
    op.execute("""
        WITH ranked AS (
            SELECT id,
                   ROW_NUMBER() OVER (PARTITION BY team_id ORDER BY created_at, id) - 1 AS rn
            FROM developers
        )
        UPDATE developers d
        SET color_index = ranked.rn % 10
        FROM ranked
        WHERE d.id = ranked.id
    """)

    # Existing tasks need no backfill — NULL is the correct value for all three
    # new task columns (unassigned, untimed, no duration).


def downgrade() -> None:
    op.drop_column('developers', 'avatar_url')
    op.drop_column('developers', 'color_index')

    op.drop_index('ix_tasks_scheduled_date_time', table_name='tasks')
    op.drop_column('tasks', 'duration_minutes')
    op.drop_column('tasks', 'scheduled_time')
    op.drop_index('ix_tasks_assignee_id', table_name='tasks')
    op.drop_constraint('fk_tasks_assignee_id_developers', 'tasks', type_='foreignkey')
    op.drop_column('tasks', 'assignee_id')
