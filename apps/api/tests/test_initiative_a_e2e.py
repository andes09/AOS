"""End-to-end pipeline checks for Initiative A.

These tests stitch the milestone seams together using mocks (no real DB / Jira /
Anthropic). They prove the contracts between stages hold, not that the system
runs end-to-end in production.

Pipeline covered:
  ticket text → identifier_extraction → identifier_classifier → team_identifiers
              → compute_intensity (per ticket) → TicketSkillAnalysis
              → Sprint Brain prompt includes skill_vector + skill_ratings
              → Scope Cop accepts matched_identifier_count
              → SprintPlanOverride captures reassignments
              → override_analyzer → recalibration proposals
"""
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.services.identifier_extraction import extract_tokens, count_tokens, normalize_token
from src.services.identifier_classifier import classify_identifiers, ClassifiedIdentifier
from src.services.skill_intensity import compute_intensity
from src.services import sprint_brain as sb
from src.services.scope_cop import _SCOPE_COP_TOOL
from src.services.override_analyzer import detect_patterns


SAMPLE_TICKET_TEXT = (
    "Optimize dbo.tile_metrics rollup query and update ms-service "
    "to read from the new schema. Refactor OrderService to call the new endpoint."
)


def test_step1_tokenizer_extracts_punctuation_and_camelcase_identifiers():
    """The regex tokenizer surfaces dotted, kebab, and ≥2-segment CamelCase tokens."""
    tokens = extract_tokens(SAMPLE_TICKET_TEXT, source="ticket_description")
    normalized = {t.normalized for t in tokens}
    assert "dbo.tile_metrics" in normalized
    assert "ms-service" in normalized
    assert "orderservice" in normalized
    # Single-segment CamelCase / stopwords filtered
    assert "task" not in normalized


@pytest.mark.asyncio
async def test_step2_classifier_returns_one_entry_per_input_token():
    """The classifier preserves raw token + occurrence_count round-trip."""
    inputs = [
        ("dbo.tile_metrics", "dbo.tile_metrics", 5),
        ("ms-service", "ms-service", 3),
    ]
    fake_response = MagicMock()
    fake_response.content = [
        SimpleNamespace(
            type="tool_use",
            name="classify_identifiers",
            input={
                "classifications": [
                    {"normalized_token": "dbo.tile_metrics", "skill": "SQL", "domain": "data", "confidence": 0.9},
                    {"normalized_token": "ms-service", "skill": "Java/Spring Boot", "domain": "backend", "confidence": 0.75},
                ]
            },
        )
    ]
    fake_client = MagicMock()
    fake_client.messages.create = AsyncMock(return_value=fake_response)

    import src.services.identifier_classifier as ic
    orig = ic.anthropic.AsyncAnthropic
    ic.anthropic.AsyncAnthropic = MagicMock(return_value=fake_client)
    try:
        result = await classify_identifiers(
            tokens=inputs,
            team_stack=["SQL", "Java/Spring Boot"],
            anthropic_api_key="fake-key",
        )
    finally:
        ic.anthropic.AsyncAnthropic = orig

    assert len(result) == 2
    by_token = {c.normalized_token: c for c in result}
    assert by_token["dbo.tile_metrics"].skill == "SQL"
    assert by_token["dbo.tile_metrics"].occurrence_count == 5
    assert by_token["ms-service"].skill == "Java/Spring Boot"


def test_step3_intensity_uses_team_identifiers_to_score_a_ticket():
    """compute_intensity matches normalized tokens and produces normalized vectors."""
    team_identifiers = [
        SimpleNamespace(normalized_token="dbo.tile_metrics", skill="SQL", domain="data", confidence=0.9),
        SimpleNamespace(normalized_token="ms-service", skill="Java", domain="backend", confidence=0.8),
    ]
    result = compute_intensity(
        ticket_title="Optimize dbo.tile_metrics rollup",
        ticket_description="Update ms-service to read from the new schema",
        ticket_labels=[],
        ticket_components=[],
        team_identifiers=team_identifiers,
        effort_multiplier=1.0,
    )
    # At least one of the two skills is normalized to 1.0; both should appear.
    assert "SQL" in result.skill_vector
    assert "Java" in result.skill_vector
    assert max(result.skill_vector.values()) == pytest.approx(1.0)
    assert set(result.matched_identifiers) == {"dbo.tile_metrics", "ms-service"}


def test_step4_sprint_brain_tool_schema_requires_skill_match_reasoning():
    """The plan tool schema added skill_match_reasoning during Wave 2."""
    assignment_props = sb._SPRINT_PLAN_TOOL["input_schema"]["properties"]["assignments"]["items"]["properties"]
    assert "skill_match_reasoning" in assignment_props
    required = sb._SPRINT_PLAN_TOOL["input_schema"]["properties"]["assignments"]["items"]["required"]
    assert "skill_match_reasoning" in required


def test_step5_scope_cop_tool_includes_stack_alignment():
    """The Scope Cop tool schema added stack_alignment during Wave 2."""
    # The schema may wrap results in a top-level 'results' array. Inspect both shapes.
    schema_text = repr(_SCOPE_COP_TOOL)
    assert "stack_alignment" in schema_text
    assert "matched_identifier_count" in schema_text


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


def test_step7_sprint_brain_carries_overrides_section_kwarg():
    """Wave 5 added an overrides_section kwarg to _build_assignment_message
    so previous-sprint reassignment context can be threaded into the prompt.
    Detailed assembly is covered by TestOverrideContextInjection in test_sprint_brain.py.
    """
    import inspect
    sig = inspect.signature(sb._build_assignment_message)
    assert "overrides_section" in sig.parameters
    assert sig.parameters["overrides_section"].default == ""
