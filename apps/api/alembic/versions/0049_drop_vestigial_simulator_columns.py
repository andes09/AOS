"""drop vestigial simulator columns left on pre-squash databases

`organizations.is_simulated`, `tickets.is_carryover`, and `sprints.alert_sent`
are TAWOS-simulator/alert experiment columns that no longer exist in any model
and are referenced nowhere in the codebase. They are also created by no
migration in the current chain — a database built from `0000` forward never has
them. They survive only on databases provisioned from the pre-squash history
(the local dev DB is one), which is why `alembic.autogenerate.compare_metadata`
reports them as drift there and not on a fresh build.

`is_simulated`/`is_carryover` are the columns behind the May 2026 production
outage (see tasks/lessons.md): they were declared on the models while prod
Postgres lacked them, so every SELECT expanded to include a column that didn't
exist. The fix then was to drop them from the models, which left exactly this
situation — live columns on older databases that nothing references.

DROP COLUMN IF EXISTS, not op.drop_column: on a database that never had these
columns (fresh dev, CI, and production, all of which are built from this chain)
a bare drop raises UndefinedColumn and breaks `upgrade head`. The point of this
revision is convergence — every database ends up with the same shape regardless
of vintage — so it must be a no-op wherever the columns are already absent.

Deliberately irreversible. `downgrade` is a no-op rather than re-adding the
columns: which databases originally had them is not recoverable here, so
re-creating them everywhere would manufacture the very drift this removes, and
the columns are dead weight in any case.

Revision ID: 0049
Revises: 0048
Create Date: 2026-08-04
"""
from alembic import op

revision = '0049'
down_revision = '0048'
branch_labels = None
depends_on = None

# (table, column) pairs. All three were NOT NULL DEFAULT false where present,
# so nothing read or wrote them meaningfully.
_VESTIGIAL = (
    ('organizations', 'is_simulated'),
    ('tickets', 'is_carryover'),
    ('sprints', 'alert_sent'),
)


def upgrade() -> None:
    for table, column in _VESTIGIAL:
        op.execute(f'ALTER TABLE {table} DROP COLUMN IF EXISTS {column}')


def downgrade() -> None:
    """No-op — see the module docstring."""
