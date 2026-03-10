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
    _apply_sprint_gate,
    _build_user_message,
    _build_complexity_message,
    _extract_complexity,
    _analyse_ticket_complexity,
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
    insufficient_data_devs=[],
)


def test_sprint_brain_output_insufficient_data_devs_defaults_to_empty():
    output = SprintBrainOutput(
        assignments=[],
        confidence_score=0.9,
        summary="test",
        warnings=[],
        what_if_dropped={},
    )
    assert output.insufficient_data_devs == []


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
# Complexity analysis unit tests
# ---------------------------------------------------------------------------


class TestComplexityAnalysis:
    def test_build_complexity_message_includes_all_ticket_ids(self):
        msg = _build_complexity_message(SAMPLE_TICKETS)
        assert "PROJ-1" in msg
        assert "PROJ-2" in msg
        assert "PROJ-3" in msg

    def test_build_complexity_message_includes_summaries(self):
        msg = _build_complexity_message(SAMPLE_TICKETS)
        assert "Build login page" in msg
        assert "Fix null pointer bug" in msg

    def test_build_complexity_message_includes_story_points(self):
        msg = _build_complexity_message(SAMPLE_TICKETS)
        assert "3" in msg

    def test_extract_complexity_parses_tool_response(self):
        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.name = "analyse_tickets"
        tool_block.input = {
            "ticket_analyses": [
                {
                    "ticket_id": "PROJ-1",
                    "effort": "medium",
                    "required_skills": ["frontend", "auth"],
                    "complexity_notes": "Requires auth integration.",
                    "estimated_days": 2.0,
                }
            ]
        }
        response = MagicMock()
        response.content = [tool_block]

        result = _extract_complexity(response)

        assert len(result) == 1
        assert result[0]["ticket_id"] == "PROJ-1"
        assert result[0]["effort"] == "medium"
        assert result[0]["estimated_days"] == 2.0

    def test_extract_complexity_raises_when_tool_missing(self):
        text_block = MagicMock()
        text_block.type = "text"
        response = MagicMock()
        response.content = [text_block]

        with pytest.raises(RuntimeError, match="complexity analysis"):
            _extract_complexity(response)


@pytest.mark.asyncio
async def test_analyse_ticket_complexity_calls_claude():
    """_analyse_ticket_complexity must call Claude exactly once with the right tool."""
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.name = "analyse_tickets"
    tool_block.input = {
        "ticket_analyses": [
            {
                "ticket_id": "PROJ-1",
                "effort": "low",
                "required_skills": ["frontend"],
                "complexity_notes": "Simple UI.",
                "estimated_days": 0.5,
            }
        ]
    }
    mock_response = MagicMock()
    mock_response.content = [tool_block]

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    result = await _analyse_ticket_complexity(SAMPLE_TICKETS[:1], mock_client)

    mock_client.messages.create.assert_called_once()
    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert call_kwargs["tool_choice"] == {"type": "tool", "name": "analyse_tickets"}
    assert len(result) == 1
    assert result[0]["ticket_id"] == "PROJ-1"


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


# ---------------------------------------------------------------------------
# _apply_sprint_gate unit tests  (Track F profile shape)
# ---------------------------------------------------------------------------

# New profile shape used in Track F tests
PROFILE_ALICE = {
    "developer_id": "dev-1",
    "display_name": "Alice",
    "sprint_count": 5,
    "velocity_breakdown": [
        {"ticket_type": "bug", "domain": "backend", "avg_pts": 8.2, "sample_count": 4},
        {"ticket_type": "story", "domain": "frontend", "avg_pts": 5.0, "sample_count": 2},
    ],
    "safe_capacity_pts": 24.0,
}

PROFILE_BOB = {
    "developer_id": "dev-2",
    "display_name": "Bob",
    "sprint_count": 1,
    "velocity_breakdown": [
        {"ticket_type": "story", "domain": "backend", "avg_pts": 3.0, "sample_count": 1},
    ],
    "safe_capacity_pts": 8.0,
}

PROFILE_CHARLIE = {
    "developer_id": "dev-3",
    "display_name": "Charlie",
    "sprint_count": 3,
    "velocity_breakdown": [
        {"ticket_type": "task", "domain": "infra", "avg_pts": 6.0, "sample_count": 3},
    ],
    "safe_capacity_pts": 18.0,
}


class TestApplySprintGate:
    def test_eligible_developer_passes(self):
        eligible, insufficient = _apply_sprint_gate([PROFILE_ALICE])
        assert len(eligible) == 1
        assert len(insufficient) == 0

    def test_insufficient_developer_fails(self):
        eligible, insufficient = _apply_sprint_gate([PROFILE_BOB])
        assert len(eligible) == 0
        assert len(insufficient) == 1

    def test_exactly_three_sprints_passes(self):
        eligible, insufficient = _apply_sprint_gate([PROFILE_CHARLIE])
        assert len(eligible) == 1
        assert len(insufficient) == 0

    def test_mixed_profiles_split_correctly(self):
        eligible, insufficient = _apply_sprint_gate([PROFILE_ALICE, PROFILE_BOB, PROFILE_CHARLIE])
        assert len(eligible) == 2
        assert len(insufficient) == 1
        assert insufficient[0]["developer_id"] == "dev-2"

    def test_insufficient_entry_has_required_fields(self):
        _, insufficient = _apply_sprint_gate([PROFILE_BOB])
        entry = insufficient[0]
        assert entry["developer_id"] == "dev-2"
        assert entry["display_name"] == "Bob"
        assert entry["sprints_recorded"] == 1
        assert entry["sprints_needed"] == 2  # 3 - 1

    def test_missing_sprint_count_treated_as_zero(self):
        profile_no_count = {"developer_id": "dev-x", "display_name": "X"}
        eligible, insufficient = _apply_sprint_gate([profile_no_count])
        assert len(eligible) == 0
        assert insufficient[0]["sprints_recorded"] == 0
        assert insufficient[0]["sprints_needed"] == 3

    def test_empty_profiles_returns_empty_buckets(self):
        eligible, insufficient = _apply_sprint_gate([])
        assert eligible == []
        assert insufficient == []
