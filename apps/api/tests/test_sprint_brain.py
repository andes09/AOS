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
    _build_assignment_message,
    _build_complexity_message,
    _extract_complexity,
    _analyse_ticket_complexity,
    _CITATION_INSTRUCTION,
    _SPRINT_PLAN_TOOL,
    _compute_skill_velocity_breakdown,
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


def _make_complexity_response(analyses: list[dict]):
    """Build a mock response for the complexity analysis Claude call."""
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.name = "analyse_tickets"
    tool_block.input = {"ticket_analyses": analyses}
    response = MagicMock()
    response.content = [tool_block]
    return response


SAMPLE_COMPLEXITY = [
    {"ticket_id": "PROJ-1", "effort": "low", "required_skills": ["frontend"], "complexity_notes": "Simple.", "estimated_days": 1.0},
    {"ticket_id": "PROJ-2", "effort": "medium", "required_skills": ["backend"], "complexity_notes": "Auth.", "estimated_days": 2.0},
    {"ticket_id": "PROJ-3", "effort": "high", "required_skills": ["backend", "infra"], "complexity_notes": "Perf.", "estimated_days": 4.0},
]

PLAN_DICT = {
    "assignments": [
        {"ticket_id": "PROJ-1", "developer_id": "dev-1", "reasoning": "Based on 4 backend/bug sprints averaging 8.2 pts.", "confidence": 0.88, "story_points": 3},
    ],
    "confidence_score": 0.85,
    "summary": "One ticket assigned to Alice based on her backend history.",
    "warnings": [],
    "what_if_dropped": {"PROJ-1": 1.0},
}


@pytest.mark.asyncio
async def test_generate_sprint_plan_returns_output():
    complexity_response = _make_complexity_response(SAMPLE_COMPLEXITY)
    plan_dict = {
        "assignments": SAMPLE_OUTPUT.assignments,
        "confidence_score": SAMPLE_OUTPUT.confidence_score,
        "summary": SAMPLE_OUTPUT.summary,
        "warnings": SAMPLE_OUTPUT.warnings,
        "what_if_dropped": SAMPLE_OUTPUT.what_if_dropped,
    }
    plan_response = _make_mock_response(plan_dict)

    with patch("src.services.sprint_brain.anthropic.AsyncAnthropic") as MockClient:
        instance = MockClient.return_value
        instance.messages.create = AsyncMock(side_effect=[complexity_response, plan_response])

        result = await generate_sprint_plan(NEW_SAMPLE_INPUT, "sk-ant-test")

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
            await generate_sprint_plan(NEW_SAMPLE_INPUT, "bad-key")


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
            await generate_sprint_plan(NEW_SAMPLE_INPUT, "sk-ant-test")


@pytest.mark.asyncio
async def test_generate_sprint_plan_raises_when_no_tool_call():
    complexity_response = _make_complexity_response(SAMPLE_COMPLEXITY)
    text_block = MagicMock()
    text_block.type = "text"
    bad_response = MagicMock()
    bad_response.content = [text_block]

    with patch("src.services.sprint_brain.anthropic.AsyncAnthropic") as MockClient:
        instance = MockClient.return_value
        instance.messages.create = AsyncMock(side_effect=[complexity_response, bad_response])

        with pytest.raises(RuntimeError, match="did not return a sprint plan"):
            await generate_sprint_plan(NEW_SAMPLE_INPUT, "sk-ant-test")


@pytest.mark.asyncio
async def test_generate_sprint_plan_raises_when_complexity_call_returns_no_tool_call():
    """Call 1 returns only a text block → RuntimeError with 'complexity analysis'."""
    import anthropic as ant

    text_only_response = MagicMock()
    text_only_response.content = [MagicMock(type="text", text="I can't help with that.")]

    with patch("src.services.sprint_brain.anthropic.AsyncAnthropic") as MockClient:
        instance = MockClient.return_value
        instance.messages.create = AsyncMock(return_value=text_only_response)

        with pytest.raises(RuntimeError, match="complexity analysis"):
            await generate_sprint_plan(NEW_SAMPLE_INPUT, "test-key")


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


# ---------------------------------------------------------------------------
# _build_assignment_message unit tests
# ---------------------------------------------------------------------------

COMPLEXITY_ANALYSIS = [
    {"ticket_id": "PROJ-1", "effort": "low", "required_skills": ["frontend"], "complexity_notes": "Simple UI.", "estimated_days": 1.0},
    {"ticket_id": "PROJ-2", "effort": "medium", "required_skills": ["backend"], "complexity_notes": "Auth layer.", "estimated_days": 2.0},
]

# PROFILE_ALICE and PROFILE_CHARLIE are already defined in this file
NEW_SAMPLE_PROFILES = [PROFILE_ALICE, PROFILE_CHARLIE]

NEW_SAMPLE_INPUT = SprintBrainInput(
    team_id="team-abc",
    candidate_tickets=SAMPLE_TICKETS[:2],
    developer_profiles=NEW_SAMPLE_PROFILES,
    sprint_length_days=14,
    sprint_start_date="2026-03-17",
    pto_overrides={"dev-1": 1.0},
)


class TestBuildAssignmentMessage:
    def test_includes_team_id(self):
        msg = _build_assignment_message(NEW_SAMPLE_INPUT, COMPLEXITY_ANALYSIS, NEW_SAMPLE_PROFILES)
        assert "team-abc" in msg

    def test_includes_ticket_ids(self):
        msg = _build_assignment_message(NEW_SAMPLE_INPUT, COMPLEXITY_ANALYSIS, NEW_SAMPLE_PROFILES)
        assert "PROJ-1" in msg
        assert "PROJ-2" in msg

    def test_includes_complexity_effort(self):
        msg = _build_assignment_message(NEW_SAMPLE_INPUT, COMPLEXITY_ANALYSIS, NEW_SAMPLE_PROFILES)
        assert "Effort    : low" in msg or "Effort    : medium" in msg

    def test_includes_developer_names(self):
        msg = _build_assignment_message(NEW_SAMPLE_INPUT, COMPLEXITY_ANALYSIS, NEW_SAMPLE_PROFILES)
        assert "Alice" in msg
        assert "Charlie" in msg

    def test_includes_velocity_breakdown(self):
        msg = _build_assignment_message(NEW_SAMPLE_INPUT, COMPLEXITY_ANALYSIS, NEW_SAMPLE_PROFILES)
        assert "8.2" in msg   # Alice's backend/bug avg

    def test_includes_safe_capacity(self):
        msg = _build_assignment_message(NEW_SAMPLE_INPUT, COMPLEXITY_ANALYSIS, NEW_SAMPLE_PROFILES)
        assert "24.0 pts" in msg    # Alice's safe_capacity_pts

    def test_includes_pto(self):
        msg = _build_assignment_message(NEW_SAMPLE_INPUT, COMPLEXITY_ANALYSIS, NEW_SAMPLE_PROFILES)
        assert "PTO" in msg
        assert "1.0" in msg

    def test_includes_citation_instruction(self):
        msg = _build_assignment_message(NEW_SAMPLE_INPUT, COMPLEXITY_ANALYSIS, NEW_SAMPLE_PROFILES)
        assert _CITATION_INSTRUCTION in msg

    def test_excludes_insufficient_developers(self):
        # If only Alice is eligible, Bob should not appear
        msg = _build_assignment_message(NEW_SAMPLE_INPUT, COMPLEXITY_ANALYSIS, [PROFILE_ALICE])
        assert "Alice" in msg
        assert "Bob" not in msg


# ---------------------------------------------------------------------------
# Two-step generate_sprint_plan tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_sprint_plan_makes_two_claude_calls():
    """generate_sprint_plan must call the Anthropic API exactly twice."""
    complexity_response = _make_complexity_response(SAMPLE_COMPLEXITY)
    plan_response = _make_mock_response(PLAN_DICT)

    with patch("src.services.sprint_brain.anthropic.AsyncAnthropic") as MockClient:
        instance = MockClient.return_value
        instance.messages.create = AsyncMock(side_effect=[complexity_response, plan_response])

        result = await generate_sprint_plan(NEW_SAMPLE_INPUT, "sk-ant-test")

    assert instance.messages.create.call_count == 2


@pytest.mark.asyncio
async def test_generate_sprint_plan_attaches_insufficient_data_devs():
    """Developers who fail the gate appear in insufficient_data_devs."""
    mixed_input = SprintBrainInput(
        team_id="team-abc",
        candidate_tickets=SAMPLE_TICKETS,
        developer_profiles=[PROFILE_ALICE, PROFILE_BOB],  # Bob fails gate
        sprint_length_days=14,
        sprint_start_date="2026-03-17",
    )
    complexity_response = _make_complexity_response(SAMPLE_COMPLEXITY)
    plan_response = _make_mock_response(PLAN_DICT)

    with patch("src.services.sprint_brain.anthropic.AsyncAnthropic") as MockClient:
        instance = MockClient.return_value
        instance.messages.create = AsyncMock(side_effect=[complexity_response, plan_response])

        result = await generate_sprint_plan(mixed_input, "sk-ant-test")

    assert len(result.insufficient_data_devs) == 1
    assert result.insufficient_data_devs[0]["developer_id"] == "dev-2"


@pytest.mark.asyncio
async def test_generate_sprint_plan_raises_when_all_devs_insufficient():
    """If all developers fail the gate, raise RuntimeError before calling Claude."""
    all_insufficient_input = SprintBrainInput(
        team_id="team-abc",
        candidate_tickets=SAMPLE_TICKETS,
        developer_profiles=[PROFILE_BOB],  # only Bob — fails gate
        sprint_length_days=14,
        sprint_start_date="2026-03-17",
    )

    with patch("src.services.sprint_brain.anthropic.AsyncAnthropic") as MockClient:
        instance = MockClient.return_value
        instance.messages.create = AsyncMock()

        with pytest.raises(RuntimeError, match="no eligible developers"):
            await generate_sprint_plan(all_insufficient_input, "sk-ant-test")

    instance.messages.create.assert_not_called()


@pytest.mark.asyncio
async def test_generate_sprint_plan_second_call_uses_assignment_tool():
    """The second Claude call must use create_sprint_plan tool, not analyse_tickets."""
    complexity_response = _make_complexity_response(SAMPLE_COMPLEXITY)
    plan_response = _make_mock_response(PLAN_DICT)

    with patch("src.services.sprint_brain.anthropic.AsyncAnthropic") as MockClient:
        instance = MockClient.return_value
        instance.messages.create = AsyncMock(side_effect=[complexity_response, plan_response])

        await generate_sprint_plan(NEW_SAMPLE_INPUT, "sk-ant-test")

    second_call_kwargs = instance.messages.create.call_args_list[1].kwargs
    assert second_call_kwargs["tool_choice"] == {"type": "tool", "name": "create_sprint_plan"}


# ---------------------------------------------------------------------------
# Skill vector / skill ratings integration tests (Initiative A Wave 2)
# ---------------------------------------------------------------------------


class TestSkillVectorIntegration:
    """Coverage for skill_vector + skill_ratings wiring in Sprint Brain."""

    @pytest.mark.asyncio
    async def test_compute_skill_velocity_breakdown_empty_when_no_analyses(self):
        """No completed tickets with analyses → empty list (graceful default)."""
        import uuid as _uuid

        mock_result = MagicMock()
        mock_result.all = MagicMock(return_value=[])
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        out = await _compute_skill_velocity_breakdown(_uuid.uuid4(), _uuid.uuid4(), mock_db)
        assert out == []

    @pytest.mark.asyncio
    async def test_compute_skill_velocity_breakdown_aggregates_correctly(self):
        """Verify weighted aggregation across multiple tickets per skill."""
        import uuid as _uuid

        # Two tickets: t1 has SQL=0.8 (5 pts), t2 has SQL=0.4 (3 pts)
        # Expected SQL avg = (5*0.8 + 3*0.4) / (0.8 + 0.4) = (4.0 + 1.2) / 1.2 = 4.333
        t1 = MagicMock(story_points_estimated=5.0)
        a1 = MagicMock(skill_vector={"SQL": 0.8, "Python": 0.05})  # Python below threshold
        t2 = MagicMock(story_points_estimated=3.0)
        a2 = MagicMock(skill_vector={"SQL": 0.4})

        mock_result = MagicMock()
        mock_result.all = MagicMock(return_value=[(t1, a1), (t2, a2)])
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        out = await _compute_skill_velocity_breakdown(_uuid.uuid4(), _uuid.uuid4(), mock_db)
        skills = {row["skill"]: row for row in out}

        # Python should be filtered out (weight 0.05 < 0.1 threshold)
        assert "Python" not in skills
        assert "SQL" in skills
        assert skills["SQL"]["avg_pts"] == pytest.approx(4.33, rel=0.01)
        assert skills["SQL"]["sample_count"] == 2

    def test_assignment_message_includes_required_skills_when_present(self):
        """A candidate ticket with skill_vector should add a 'Required skills:' line."""
        tickets = [
            {
                "id": "PROJ-1",
                "summary": "Build SQL view",
                "story_points": 3,
                "priority": "high",
                "skill_vector": {"SQL": 0.8, "Java": 0.3, "CSS": 0.1},  # CSS below threshold
            }
        ]
        inp = SprintBrainInput(
            team_id="team-abc",
            candidate_tickets=tickets,
            developer_profiles=[PROFILE_ALICE],
            sprint_length_days=14,
            sprint_start_date="2026-03-17",
        )
        msg = _build_assignment_message(inp, COMPLEXITY_ANALYSIS, [PROFILE_ALICE])
        assert "Required skills:" in msg
        assert "SQL=0.8" in msg
        assert "Java=0.3" in msg
        # CSS below 0.2 threshold should NOT appear in the inline list
        assert "CSS=0.1" not in msg

    def test_assignment_message_omits_required_skills_when_empty(self):
        """A ticket with no skill_vector / empty dict should NOT emit a 'Required skills:' line."""
        tickets = [
            {"id": "PROJ-1", "summary": "Build login page", "story_points": 3, "priority": "high"},
            {"id": "PROJ-2", "summary": "Fix bug", "story_points": 2, "priority": "high", "skill_vector": {}},
        ]
        inp = SprintBrainInput(
            team_id="team-abc",
            candidate_tickets=tickets,
            developer_profiles=[PROFILE_ALICE],
            sprint_length_days=14,
            sprint_start_date="2026-03-17",
        )
        msg = _build_assignment_message(inp, COMPLEXITY_ANALYSIS, [PROFILE_ALICE])
        assert "Required skills:" not in msg

    def test_assignment_message_includes_skill_ratings_for_dev(self):
        """A developer profile with skill_ratings should produce a 'Skill ratings:' line."""
        alice_with_ratings = {**PROFILE_ALICE, "skill_ratings": {"SQL": 0.9, "Java": 0.6, "CSS": 0.1}}
        inp = SprintBrainInput(
            team_id="team-abc",
            candidate_tickets=SAMPLE_TICKETS[:1],
            developer_profiles=[alice_with_ratings],
            sprint_length_days=14,
            sprint_start_date="2026-03-17",
        )
        msg = _build_assignment_message(inp, COMPLEXITY_ANALYSIS, [alice_with_ratings])
        assert "Skill ratings:" in msg
        assert "SQL=0.9" in msg
        assert "Java=0.6" in msg
        assert "CSS=0.1" not in msg

    def test_sprint_plan_tool_schema_includes_skill_match_reasoning(self):
        """Tool schema must expose skill_match_reasoning on each assignment."""
        assignment_schema = _SPRINT_PLAN_TOOL["input_schema"]["properties"]["assignments"]["items"]
        assert "skill_match_reasoning" in assignment_schema["properties"]
        assert assignment_schema["properties"]["skill_match_reasoning"]["type"] == "string"
        assert "skill_match_reasoning" in assignment_schema["required"]

    @pytest.mark.asyncio
    async def test_extract_plan_defaults_skill_match_reasoning_when_missing(self):
        """Backward-compat: assignments lacking skill_match_reasoning must NOT crash."""
        legacy_plan = {
            "assignments": [
                {
                    "ticket_id": "PROJ-1",
                    "developer_id": "dev-1",
                    "reasoning": "Legacy reason",
                    "confidence": 0.8,
                    # NOTE: no skill_match_reasoning — older shape
                }
            ],
            "confidence_score": 0.8,
            "summary": "Legacy plan",
            "warnings": [],
            "what_if_dropped": {"PROJ-1": 0.7},
        }
        complexity_response = _make_complexity_response(SAMPLE_COMPLEXITY)
        legacy_response = _make_mock_response(legacy_plan)

        with patch("src.services.sprint_brain.anthropic.AsyncAnthropic") as MockClient:
            instance = MockClient.return_value
            instance.messages.create = AsyncMock(side_effect=[complexity_response, legacy_response])

            out = await generate_sprint_plan(NEW_SAMPLE_INPUT, "sk-ant-test")

        # Should default to None instead of raising
        assert out.assignments[0]["skill_match_reasoning"] is None
