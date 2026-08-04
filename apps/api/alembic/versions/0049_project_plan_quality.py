"""project plan_quality — DAG generation-fidelity telemetry

`resolve_task_dependencies` (services/roadmap_shapes.py) already detects the two
ways an LLM-drafted dependency graph goes wrong — edges referencing a task
that isn't in the batch, and cycles — and drops both. Until now it only logged
them, so there was no way to ask "how good are the plans we're generating?"
after the fact. This column stores the raw per-build counts; rates and
DAG-shape metrics are derived on read by services/plan_quality.py.

JSON().with_variant(JSONB(), "postgresql") rather than a bare JSONB, matching
onboarding_sessions/developers: the test suite builds its schema on SQLite
(tests/conftest.py), which cannot render JSONB.

Nullable with no backfill — a project whose roadmap was generated before this
column simply has no telemetry, and the numbers are only recoverable at
generation time, so there is nothing to backfill from.

Revision ID: 0049
Revises: 0048
Create Date: 2026-08-04
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0049'
down_revision = '0048'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'projects',
        sa.Column('plan_quality', sa.JSON().with_variant(JSONB(), 'postgresql'), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('projects', 'plan_quality')
