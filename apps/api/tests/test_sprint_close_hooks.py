"""Tests for the sprint-close hook wiring in jira/sync.py.

Initiative A Wave 6: when a Jira sync transitions a sprint to COMPLETED,
fire `refresh_after_sprint_close` (identifier refresh) and `persist_plan_quality`
(override-rate telemetry). Failures are logged and swallowed.
"""
import uuid
from unittest.mock import MagicMock

import pytest

from src.integrations.jira.sync import _upsert_sprint
from src.models.sprint import SprintStatus


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = None
    return db


@pytest.fixture
def mock_team():
    team = MagicMock()
    team.id = uuid.uuid4()
    return team


def _jira_sprint(state: str, name: str = "Sprint X", sprint_id: str = "1"):
    return {"id": sprint_id, "name": name, "state": state}


def test_upsert_sprint_new_completed_returns_transition_true(mock_db, mock_team):
    """A brand-new sprint observed as 'closed' counts as a transition."""
    sprint, transitioned = _upsert_sprint(mock_db, mock_team, _jira_sprint("closed"))
    assert transitioned is True
    assert sprint.status == SprintStatus.COMPLETED


def test_upsert_sprint_new_active_returns_transition_false(mock_db, mock_team):
    sprint, transitioned = _upsert_sprint(mock_db, mock_team, _jira_sprint("active"))
    assert transitioned is False
    assert sprint.status == SprintStatus.ACTIVE


def test_upsert_sprint_active_to_completed_returns_transition_true(mock_db, mock_team):
    """The interesting case: existing active sprint flips to closed."""
    existing = MagicMock()
    existing.status = SprintStatus.ACTIVE
    existing.name = "Sprint 5"
    mock_db.execute.return_value.scalar_one_or_none.return_value = existing

    sprint, transitioned = _upsert_sprint(mock_db, mock_team, _jira_sprint("closed", "Sprint 5"))
    assert transitioned is True
    assert sprint.status == SprintStatus.COMPLETED


def test_upsert_sprint_completed_to_completed_returns_transition_false(mock_db, mock_team):
    """Subsequent syncs of an already-closed sprint must not re-fire hooks."""
    existing = MagicMock()
    existing.status = SprintStatus.COMPLETED
    existing.name = "Sprint 5"
    mock_db.execute.return_value.scalar_one_or_none.return_value = existing

    sprint, transitioned = _upsert_sprint(mock_db, mock_team, _jira_sprint("closed", "Sprint 5"))
    assert transitioned is False
    assert sprint.status == SprintStatus.COMPLETED


def test_upsert_sprint_planning_to_active_returns_transition_false(mock_db, mock_team):
    """Other transitions (e.g. planning → active) must NOT count as a sprint close."""
    existing = MagicMock()
    existing.status = SprintStatus.PLANNING
    existing.name = "Sprint 5"
    mock_db.execute.return_value.scalar_one_or_none.return_value = existing

    sprint, transitioned = _upsert_sprint(mock_db, mock_team, _jira_sprint("active", "Sprint 5"))
    assert transitioned is False
    assert sprint.status == SprintStatus.ACTIVE
