"""End-to-end pipeline checks for Initiative A.

These tests stitch the milestone seams together using mocks (no real DB / Jira /
Anthropic). They prove the contracts between stages hold, not that the system
runs end-to-end in production.

Pipeline covered (post skill-based-assignment teardown B5, Scope Cop
backend teardown B6):
  SprintPlanOverride captures reassignments
  → override_analyzer → recalibration proposals

Note: the identifier_extraction → identifier_classifier → compute_intensity
stages this file used to cover were deleted in B5 (skill-based-assignment
ticket-matching teardown, Sprint Brain's only consumer). The Scope Cop
stage's test was removed in B6 (Scope Cop backend teardown). Those steps'
tests were removed here rather than dropping the whole file, since the
remaining step below still exercises live code (override_analyzer).
"""
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.services.override_analyzer import detect_patterns


SAMPLE_TICKET_TEXT = (
    "Optimize dbo.tile_metrics rollup query and update ms-service "
    "to read from the new schema. Refactor OrderService to call the new endpoint."
)


@pytest.mark.asyncio
async def test_step6_override_analyzer_skips_when_below_threshold():
    """detect_patterns emits no proposal when fewer than 3 same-direction overrides exist."""
    # Mock DB to return 2 overrides (below threshold of 3)
    mock_db = MagicMock()
    mock_db.execute = AsyncMock()
    # No overrides → no analyses queried → empty list
    mock_db.execute.return_value.all = MagicMock(return_value=[])
    mock_db.execute.return_value.scalars = MagicMock(
        return_value=MagicMock(all=MagicMock(return_value=[]))
    )
    proposals = await detect_patterns(team_id=str(uuid.uuid4()), db=mock_db, lookback_days=90, threshold=3)
    assert proposals == []
