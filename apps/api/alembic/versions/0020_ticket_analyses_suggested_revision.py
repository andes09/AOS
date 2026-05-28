"""ticket_analyses.suggested_revision (Initiative B / Wave 0 SB-1)

Adds a nullable JSON column to ``ticket_analyses`` so Scope Cop can persist
its proposed revision payload (title / description / acceptance_criteria /
story_points) alongside the readiness scoring. SB-4 will start writing to
this column; SB-7 reads it back when serving revision previews.

Shape (all fields optional; omit when no suggestion):
    {
        "title": str | None,
        "description": str | None,
        "acceptance_criteria": list[str] | None,
        "story_points": int | None,
    }

Revision ID: 0020
Revises: 0019
Create Date: 2026-05-27
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = '0020'
down_revision = '0019'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ticket_analyses",
        sa.Column(
            "suggested_revision",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("ticket_analyses", "suggested_revision")
