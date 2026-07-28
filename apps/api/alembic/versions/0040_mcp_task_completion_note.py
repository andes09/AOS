"""tasks.completion_note — free-text note set by the MCP complete_task tool

Revision ID: 0040
Revises: 0039
Create Date: 2026-07-28

Omada MCP Server build (docs/plans/2026-07-20-omada-mcp-server.md). Adds ONLY
`completion_note` — `Task.completed_at` (and `short_id`/`organizations.
next_task_seq`) already exist as of migration 0038 (Stage 3, GitHub Task
Auto-Complete). The original plan doc's §2 assumed a pre-Stage-3 schema and
would have re-added `completed_at`; that column already exists on `main`, so
re-adding it here would be a duplicate-column error.
"""
from alembic import op
import sqlalchemy as sa

revision = '0040'
down_revision = '0039'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('tasks', sa.Column('completion_note', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('tasks', 'completion_note')
