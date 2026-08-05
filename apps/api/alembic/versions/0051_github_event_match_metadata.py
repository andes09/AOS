"""github_activity_events match provenance — how a commit/PR got linked to a task

Until now `matched_task_id` was the whole story, and it could only ever be set
one way: the developer typed a task's `short_id` (e.g. "AOS-142") into the
branch name, commit message, or PR title. That is a strong signal but a rare
one — a founder driving an AI coding agent essentially never does it — so in
practice almost every row lands with a NULL match. Any "how much of the work
we shipped was actually on the roadmap?" question asked of this table today
answers "none of it", regardless of the truth.

Fixing that means adding weaker-but-common matching paths (token/path
heuristics, and an LLM pass over what those miss). Once more than one path can
set `matched_task_id`, *which* path set it stops being an implementation
detail and becomes load-bearing:

  - `match_method` distinguishes an exact short_id hit from a guess, so
    consumers can hold the two to different standards. Only `short_id` is ever
    allowed to mutate `Task.status` / `completed_at` (see
    integrations/github/events.py) — a heuristic or LLM match is evidence for
    drift reporting and nothing more, so a wrong guess can never silently tick
    a task off a founder's plan.
  - `match_confidence` (0.0–1.0) lets the drift service weight or threshold
    fuzzy matches. NULL for `short_id` rows: an exact identifier match has no
    meaningful confidence score, and storing a fake 1.0 would invite averaging
    it in with real scores.
  - `classified_at` records when the LLM pass last looked at a row, so the
    classifier can skip what it has already seen rather than re-billing for it
    every sweep.

Backfill is exact, not a guess: existing rows have a matched_task_id if and
only if the short_id path matched them, since it was the only path that
existed. `'unmatched'` rather than NULL for the rest so the column reads as a
closed set and the drift queries don't need an `IS NULL` special case.

Revision ID: 0051
Revises: 0050
Create Date: 2026-08-05
"""
from alembic import op
import sqlalchemy as sa

revision = '0051'
down_revision = '0050'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('github_activity_events', sa.Column('match_method', sa.String(20), nullable=True))
    op.add_column('github_activity_events', sa.Column('match_confidence', sa.Float(), nullable=True))
    op.add_column('github_activity_events', sa.Column('classified_at', sa.DateTime(), nullable=True))

    op.execute(
        """
        UPDATE github_activity_events
           SET match_method = CASE
                                WHEN matched_task_id IS NOT NULL THEN 'short_id'
                                ELSE 'unmatched'
                              END
        """
    )

    # Partial-scan index for the classifier's "what still needs looking at?"
    # query and the drift service's unplanned-work share, both of which filter
    # on (org, method) over a recent time window.
    op.create_index(
        'ix_github_activity_events_org_method_occurred_at',
        'github_activity_events',
        ['organization_id', 'match_method', 'occurred_at'],
    )


def downgrade() -> None:
    op.drop_index('ix_github_activity_events_org_method_occurred_at', table_name='github_activity_events')
    op.drop_column('github_activity_events', 'classified_at')
    op.drop_column('github_activity_events', 'match_confidence')
    op.drop_column('github_activity_events', 'match_method')
