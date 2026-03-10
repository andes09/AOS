"""
Tests for Sprint Brain service and API endpoints.

Service tests mock the Anthropic client; API tests mock both auth and the
service layer so no real API calls or DB connections are required.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.sprint_brain import (
    SprintBrainInput,
    SprintBrainOutput,
    _build_user_message,
    generate_sprint_plan,
    simulate_what_if,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_PROFILES = [
    {
        "developer_id": "dev-1",
        "display_name": "Alice",
        "velocity": {
            "has_sufficient_data": True,
            "mean_velocity": 10.0,
            "std_dev": 1.5,
            "confidence_capacity": 9.25,
            "sprint_count": 5,
        },
    },
    {
        "developer_id": "dev-2",
        "display_name": "Bob",
        "velocity": {
            "has_sufficient_data": False,
            "sprints_needed": 2,
        },
    },
]

SAMPLE_TICKETS = [
    {"id": "PROJ-1", "summary": "Build login page", "story_points": 3, "priority": "high"},
    {"id": "PROJ-2", "summary": "Fix null pointer bug", "story_points": 2, "priority": "critical"},
    {"id": "PROJ-3", "summary": "Add CSV export", "story_points": 5, "priority": "medium"},
]

SAMPLE_INPUT = SprintBrainInput(
    team_id="team-abc",
    candidate_tickets=SAMPLE_TICKETS,
    developer_profiles=SAMPLE_PROFILES,
    sprint_length_days=14,
    sprint_start_date="2026-03-17",
    pto_overrides={"dev-1": 1.0},
)

SAMPLE_OUTPUT = SprintBrainOutput(
    assignments=[
        {
            "ticket_id": "PROJ-1",
            "developer_id": "dev-1",
            "reasoning": "Alice has relevant frontend experience.",
            "confidence": 0.9,
            "story_points": 3,
        },
        {
            "ticket_id": "PROJ-2",
            "developer_id": "dev-1",
            "reasoning": "Critical bug; Alice is most experienced.",
            "confidence": 0.85,
            "story_points": 2,
        },
    ],
    confidence_score=0.82,
    summary="Solid sprint with two high-priority items assigned to Alice.",
    warnings=["Bob has insufficient velocity data — treat his capacity as unknown."],
    what_if_dropped={"PROJ-1": 0.91, "PROJ-2": 0.78},
)


# ---------------------------------------------------------------------------
# _build_user_message unit tests
# ---------------------------------------------------------------------------


def test_build_user_message_includes_team_id():
    msg = _build_user_message(SAMPLE_INPUT)
    assert "team-abc" in msg


def test_build_user_message_includes_tickets():
    msg = _build_user_message(SAMPLE_INPUT)
    assert "PROJ-1" in msg
    assert "PROJ-2" in msg
    assert "Build login page" in msg


def test_build_user_message_includes_developer_profiles():
    msg = _build_user_message(SAMPLE_INPUT)
    assert "Alice" in msg
    assert "Bob" in msg


def test_build_user_message_shows_pto():
    msg = _build_user_message(SAMPLE_INPUT)
    assert "PTO" in msg
    assert "1.0" in msg


def test_build_user_message_marks_insufficient_data():
    msg = _build_user_message(SAMPLE_INPUT)
    assert "insufficient" in msg.lower()


def test_build_user_message_shows_velocity_stats():
    msg = _build_user_message(SAMPLE_INPUT)
    assert "9.25" in msg  # confidence_capacity for Alice


# ---------------------------------------------------------------------------
# generate_sprint_plan — mocked Anthropic client
# ---------------------------------------------------------------------------


def _make_mock_response(plan_input: dict):
    """Build a mock anthropic.Message with a tool_use block."""
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.name = "create_sprint_plan"
    tool_block.input = plan_input

    response = MagicMock()
    response.content = [tool_block]
    return response


@pytest.mark.asyncio
async def test_generate_sprint_plan_returns_output():
    plan_dict = {
        "assignments": SAMPLE_OUTPUT.assignments,
        "confidence_score": SAMPLE_OUTPUT.confidence_score,
        "summary": SAMPLE_OUTPUT.summary,
        "warnings": SAMPLE_OUTPUT.warnings,
        "what_if_dropped": SAMPLE_OUTPUT.what_if_dropped,
    }
    mock_response = _make_mock_response(plan_dict)

    with patch("src.services.sprint_brain.anthropic.AsyncAnthropic") as MockClient:
        instance = MockClient.return_value
        instance.messages.create = AsyncMock(return_value=mock_response)

        result = await generate_sprint_plan(SAMPLE_INPUT, "sk-ant-test")

    assert isinstance(result, SprintBrainOutput)
    assert result.confidence_score == pytest.approx(0.82)
    assert len(result.assignments) == 2
    assert result.what_if_dropped["PROJ-1"] == pytest.approx(0.91)


@pytest.mark.asyncio
async def test_generate_sprint_plan_raises_on_auth_error():
    import anthropic as ant

    with patch("src.services.sprint_brain.anthropic.AsyncAnthropic") as MockClient:
        instance = MockClient.return_value
        instance.messages.create = AsyncMock(
            side_effect=ant.AuthenticationError(
                message="invalid key",
                response=MagicMock(status_code=401),
                body={},
            )
        )
        with pytest.raises(ValueError, match="Invalid Anthropic API key"):
            await generate_sprint_plan(SAMPLE_INPUT, "bad-key")


@pytest.mark.asyncio
async def test_generate_sprint_plan_raises_on_rate_limit():
    import anthropic as ant

    with patch("src.services.sprint_brain.anthropic.AsyncAnthropic") as MockClient:
        instance = MockClient.return_value
        instance.messages.create = AsyncMock(
            side_effect=ant.RateLimitError(
                message="rate limit",
                response=MagicMock(status_code=429),
                body={},
            )
        )
        with pytest.raises(RuntimeError, match="rate limit"):
            await generate_sprint_plan(SAMPLE_INPUT, "sk-ant-test")


@pytest.mark.asyncio
async def test_generate_sprint_plan_raises_when_no_tool_call():
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = "Here is a plan..."

    mock_response = MagicMock()
    mock_response.content = [text_block]

    with patch("src.services.sprint_brain.anthropic.AsyncAnthropic") as MockClient:
        instance = MockClient.return_value
        instance.messages.create = AsyncMock(return_value=mock_response)

        with pytest.raises(RuntimeError, match="did not return a sprint plan"):
            await generate_sprint_plan(SAMPLE_INPUT, "sk-ant-test")


# ---------------------------------------------------------------------------
# simulate_what_if
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_simulate_what_if_removes_dropped_tickets():
    """Verify the dropped ticket is excluded from the modified input."""
    captured_input: list[SprintBrainInput] = []

    async def fake_generate(inp: SprintBrainInput, key: str) -> SprintBrainOutput:
        captured_input.append(inp)
        return SAMPLE_OUTPUT

    with patch("src.services.sprint_brain.generate_sprint_plan", side_effect=fake_generate):
        await simulate_what_if(SAMPLE_INPUT, ["PROJ-1"], "sk-ant-test")

    assert len(captured_input) == 1
    ticket_ids = [t["id"] for t in captured_input[0].candidate_tickets]
    assert "PROJ-1" not in ticket_ids
    assert "PROJ-2" in ticket_ids
    assert "PROJ-3" in ticket_ids


@pytest.mark.asyncio
async def test_simulate_what_if_preserves_other_fields():
    """sprint_length, profiles, and pto_overrides must pass through unchanged."""
    captured_input: list[SprintBrainInput] = []

    async def fake_generate(inp: SprintBrainInput, key: str) -> SprintBrainOutput:
        captured_input.append(inp)
        return SAMPLE_OUTPUT

    with patch("src.services.sprint_brain.generate_sprint_plan", side_effect=fake_generate):
        await simulate_what_if(SAMPLE_INPUT, ["PROJ-3"], "sk-ant-test")

    modified = captured_input[0]
    assert modified.sprint_length_days == SAMPLE_INPUT.sprint_length_days
    assert modified.sprint_start_date == SAMPLE_INPUT.sprint_start_date
    assert modified.pto_overrides == SAMPLE_INPUT.pto_overrides
    assert modified.developer_profiles == SAMPLE_INPUT.developer_profiles


# ---------------------------------------------------------------------------
# API endpoint smoke tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plan_endpoint_requires_auth():
    from httpx import AsyncClient, ASGITransport
    from src.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/sprint-brain/plan",
            json={"team_id": "team-abc"},
        )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_what_if_endpoint_requires_auth():
    from httpx import AsyncClient, ASGITransport
    from src.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/sprint-brain/what-if",
            json={"team_id": "team-abc", "dropped_ticket_ids": []},
        )
    assert response.status_code == 401
