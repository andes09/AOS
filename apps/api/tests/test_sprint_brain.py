"""
Tests for Sprint Brain service and API endpoints.

Service tests mock the Anthropic client; API tests mock both auth and the
service layer so no real API calls or DB connections are required.
"""

import uuid

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
    _fetch_recent_overrides,
    _format_overrides_section,
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


# ---------------------------------------------------------------------------
# Override context injection tests (Initiative A Wave 5 — SA-16)
# ---------------------------------------------------------------------------


class TestOverrideContextInjection:
    """Coverage for last-sprint override patterns injected into Sprint Brain."""

    @pytest.mark.asyncio
    async def test_fetch_recent_overrides_returns_empty_when_none(self):
        """No completed sprints / no overrides → empty list."""
        # First call returns no sprint ids; helper must short-circuit.
        empty_sprint_ids = MagicMock()
        empty_sprint_ids.all = MagicMock(return_value=[])
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=empty_sprint_ids)

        team_id = str(uuid.uuid4())
        out = await _fetch_recent_overrides(team_id, mock_db, n_sprints=2)
        assert out == []
        # Only one query made (the sprint id lookup); no override query because no sprints.
        assert mock_db.execute.await_count == 1

    @pytest.mark.asyncio
    async def test_fetch_recent_overrides_returns_dicts_with_joined_names(self):
        """Joined rows are mapped into the expected dict shape."""
        # Step 1: sprint ids query
        sprint_ids = MagicMock()
        sprint_ids.all = MagicMock(return_value=[(uuid.uuid4(),), (uuid.uuid4(),)])

        # Step 2: override join rows.
        # Tuple order in select(): (action, reason_code, created_at, jira_issue_key, original_name, new_name)
        from datetime import datetime as _dt
        override_rows = MagicMock()
        override_rows.all = MagicMock(return_value=[
            ("reassign", "skill_fit", _dt(2026, 5, 20), "PROJ-123", "Alice", "Bob"),
            ("remove", "capacity", _dt(2026, 5, 19), "PROJ-456", "Carol", None),
            ("add", "mentorship", _dt(2026, 5, 18), "PROJ-789", None, "Dave"),
        ])

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(side_effect=[sprint_ids, override_rows])

        out = await _fetch_recent_overrides(str(uuid.uuid4()), mock_db, n_sprints=2)
        assert len(out) == 3
        assert out[0] == {
            "ticket_key": "PROJ-123",
            "action": "reassign",
            "from_dev": "Alice",
            "to_dev": "Bob",
            "reason_code": "skill_fit",
        }
        assert out[1]["action"] == "remove" and out[1]["to_dev"] is None
        assert out[2]["action"] == "add" and out[2]["from_dev"] is None

    @pytest.mark.asyncio
    async def test_fetch_recent_overrides_respects_n_sprints_limit(self):
        """The sprint id query is built with .limit(n_sprints) — verify by inspecting the executed stmt."""
        executed_stmts: list = []

        async def _capture(stmt):
            executed_stmts.append(stmt)
            res = MagicMock()
            res.all = MagicMock(return_value=[])
            return res

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(side_effect=_capture)

        await _fetch_recent_overrides(str(uuid.uuid4()), mock_db, n_sprints=2)
        # The first executed statement is the sprint-ids lookup; compiled SQL should contain a LIMIT 2.
        first_sql = str(executed_stmts[0])
        assert "LIMIT" in first_sql.upper()
        # Sanity: n_sprints value appears in the bound params of the compiled statement.
        compiled = executed_stmts[0].compile(compile_kwargs={"literal_binds": True})
        assert " 2" in str(compiled) or "LIMIT 2" in str(compiled).upper()

    def test_format_overrides_section_handles_all_actions(self):
        overrides = [
            {"ticket_key": "PROJ-1", "action": "reassign", "from_dev": "Alice", "to_dev": "Bob", "reason_code": "skill_fit"},
            {"ticket_key": "PROJ-2", "action": "remove", "from_dev": "Carol", "to_dev": None, "reason_code": "capacity"},
            {"ticket_key": "PROJ-3", "action": "add", "from_dev": None, "to_dev": "Dave", "reason_code": None},
        ]
        section = _format_overrides_section(overrides)
        assert "Previous Sprint Overrides" in section
        assert "PROJ-1 reassigned Alice → Bob (reason: skill_fit)" in section
        assert "PROJ-2 removed from Carol (reason: capacity)" in section
        # None reason_code falls back to "unspecified"
        assert "PROJ-3 added to Dave (reason: unspecified)" in section

    def test_format_overrides_section_returns_empty_string_on_empty_list(self):
        assert _format_overrides_section([]) == ""

    def test_format_overrides_section_truncates_above_cap(self):
        # 35 overrides → 30 lines + a truncation note for +5 omitted
        overrides = [
            {"ticket_key": f"PROJ-{i}", "action": "reassign", "from_dev": "A", "to_dev": "B", "reason_code": "skill_fit"}
            for i in range(35)
        ]
        section = _format_overrides_section(overrides)
        assert "(+5 more overrides omitted)" in section

    def test_build_assignment_message_includes_overrides_section(self):
        """When `overrides_section` is non-empty, the message must include the heading and lines."""
        override_text = (
            "## Previous Sprint Overrides (last 2 sprints)\n\n"
            "- PROJ-9 reassigned Alice → Bob (reason: skill_fit)\n"
        )
        msg = _build_assignment_message(
            NEW_SAMPLE_INPUT,
            COMPLEXITY_ANALYSIS,
            NEW_SAMPLE_PROFILES,
            overrides_section=override_text,
        )
        assert "Previous Sprint Overrides" in msg
        assert "PROJ-9 reassigned Alice → Bob" in msg
        # Section must appear before the candidate-tickets header (ordering guarantee)
        assert msg.index("Previous Sprint Overrides") < msg.index("Candidate Tickets")

    def test_build_assignment_message_omits_section_when_empty(self):
        """Empty overrides_section means the section heading must NOT appear."""
        msg = _build_assignment_message(
            NEW_SAMPLE_INPUT,
            COMPLEXITY_ANALYSIS,
            NEW_SAMPLE_PROFILES,
            overrides_section="",
        )
        assert "Previous Sprint Overrides" not in msg


# ---------------------------------------------------------------------------
# Initiative B / SB-5: Scope Cop auto-run between plan generation and enrichment
# ---------------------------------------------------------------------------


class TestScopeCopAutoRunOnPlan:
    """create_sprint_plan must run scope_cop.analyze_tickets against every
    assigned key *before* _build_enrichment, with failures swallowed so the
    plan response is never blocked."""

    _TEAM_UUID = "11111111-2222-3333-4444-555555555555"

    def _make_plan_output(self, ticket_ids):
        return SprintBrainOutput(
            assignments=[
                {
                    "ticket_id": tid,
                    "developer_id": "dev-1",
                    "reasoning": "n/a",
                    "confidence": 0.9,
                    "story_points": 3,
                }
                for tid in ticket_ids
            ],
            confidence_score=0.8,
            summary="ok",
            warnings=[],
            what_if_dropped={},
            insufficient_data_devs=[],
        )

    def _make_request(self):
        from src.routers.sprint_brain import PlanRequest
        return PlanRequest(
            team_id=self._TEAM_UUID,
            sprint_length_days=14,
            sprint_start_date="2026-03-17",
            pto_overrides={},
        )

    def _patch_collaborators(
        self,
        plan_output,
        analyze_side_effect=None,
    ):
        """Returns a list of patch context managers covering every collaborator
        the endpoint touches except `scope_cop.analyze_tickets` itself, which
        callers configure separately so they can assert on it.
        """
        mock_connection = MagicMock()
        mock_connection.is_active = True

        mock_team = MagicMock()
        import uuid as _uuid
        mock_team.id = _uuid.UUID(self._TEAM_UUID)
        mock_team.organization_id = _uuid.UUID("99999999-9999-9999-9999-999999999999")

        # db.scalar called twice in the new code path: once for Team, once for
        # JiraConnection. Provide both in order.
        scalar_returns = [mock_team, mock_connection]

        async def fake_scalar(_q):
            if scalar_returns:
                return scalar_returns.pop(0)
            return None

        patches = [
            patch(
                "src.routers.sprint_brain.get_anthropic_key",
                new=AsyncMock(return_value="sk-test"),
            ),
            patch(
                "src.routers.sprint_brain._resolve_team_id",
                new=AsyncMock(return_value=self._TEAM_UUID),
            ),
            patch(
                "src.routers.sprint_brain._build_brain_input",
                new=AsyncMock(
                    return_value=(
                        SAMPLE_INPUT,
                        "2026-03-17",
                        [],  # dev profiles
                        [],  # candidate tickets
                    )
                ),
            ),
            patch(
                "src.routers.sprint_brain.generate_sprint_plan",
                new=AsyncMock(return_value=plan_output),
            ),
            patch(
                "src.routers.sprint_brain._build_enrichment",
                new=AsyncMock(
                    return_value=(
                        [],  # scope_warnings
                        [],  # dep_warnings
                        None,  # enrichment_status
                        [],  # historical_warnings
                        [],  # pattern_descriptions (unused)
                    )
                ),
            ),
            patch(
                "src.routers.sprint_brain._get_fresh_client_async",
                new=AsyncMock(return_value=MagicMock(name="jira_client")),
            ),
        ]
        return patches, fake_scalar

    @pytest.mark.asyncio
    async def test_scope_cop_runs_against_assigned_keys_and_sets_timestamp(self):
        ticket_ids = ["PROJ-1", "PROJ-2", "PROJ-3"]
        plan_output = self._make_plan_output(ticket_ids)
        patches, fake_scalar = self._patch_collaborators(plan_output)

        mock_db = MagicMock()
        mock_db.scalar = AsyncMock(side_effect=fake_scalar)
        # No RetroPattern rows — make scalars return an iterable
        _empty = MagicMock()
        _empty.all = MagicMock(return_value=[])
        mock_db.scalars = AsyncMock(return_value=_empty)

        analyze_mock = AsyncMock(return_value=[])
        patches.append(
            patch(
                "src.routers.sprint_brain.scope_cop.analyze_tickets",
                new=analyze_mock,
            )
        )

        from src.routers.sprint_brain import create_sprint_plan

        # Enter all patches
        for p in patches:
            p.start()
        try:
            response = await create_sprint_plan(
                request=self._make_request(),
                clerk_org_id="org_test",
                db=mock_db,
            )
        finally:
            for p in patches:
                p.stop()

        analyze_mock.assert_awaited_once()
        call_args = analyze_mock.await_args
        # Positional: (team_id, ticket_keys, jira_client, db)
        assert call_args.args[0] == self._TEAM_UUID
        assert set(call_args.args[1]) == set(ticket_ids)

        assert response["scopeCopRanAt"] is not None
        # ISO-8601 format with timezone
        assert "T" in response["scopeCopRanAt"]
        # Response body still populated
        assert len(response["assignments"]) == len(ticket_ids)

    @pytest.mark.asyncio
    async def test_scope_cop_failure_does_not_block_plan(self):
        ticket_ids = ["PROJ-1", "PROJ-2"]
        plan_output = self._make_plan_output(ticket_ids)
        patches, fake_scalar = self._patch_collaborators(plan_output)

        mock_db = MagicMock()
        mock_db.scalar = AsyncMock(side_effect=fake_scalar)
        _empty = MagicMock()
        _empty.all = MagicMock(return_value=[])
        mock_db.scalars = AsyncMock(return_value=_empty)

        # Scope Cop blows up — endpoint must still return.
        analyze_mock = AsyncMock(side_effect=RuntimeError("claude went brrr"))
        patches.append(
            patch(
                "src.routers.sprint_brain.scope_cop.analyze_tickets",
                new=analyze_mock,
            )
        )

        from src.routers.sprint_brain import create_sprint_plan

        for p in patches:
            p.start()
        try:
            response = await create_sprint_plan(
                request=self._make_request(),
                clerk_org_id="org_test",
                db=mock_db,
            )
        finally:
            for p in patches:
                p.stop()

        analyze_mock.assert_awaited_once()
        assert response["scopeCopRanAt"] is None
        # Plan body still populated despite Scope Cop failure
        assert len(response["assignments"]) == len(ticket_ids)
        assert response["summary"] == "ok"


# ---------------------------------------------------------------------------
# SB-8: batched commit endpoint  POST /api/sprint-brain/plans/{plan_id}/commit
# ---------------------------------------------------------------------------
class TestBatchedCommit:
    """Tests for the batched plan-commit endpoint.

    Uses the MagicMock-session + dependency-override pattern from
    test_sprint_plan_overrides.py (no live DB). The Jira client and
    connection resolution are mocked.
    """

    ORG_CLERK_ID = "org_commit_test"
    ORG_ID = uuid.uuid4()
    TEAM_ID = uuid.uuid4()
    PLAN_ID = "plan-abc-123"
    SPRINT_ID = "999"
    LEAD_USER_ID = "user_lead_clerk"

    @staticmethod
    def _make_team(team_id, org_id):
        t = MagicMock()
        t.id = team_id
        t.organization_id = org_id
        return t

    @staticmethod
    def _make_connection():
        c = MagicMock()
        c.id = uuid.uuid4()
        return c

    def _setup_session(self, scalar_results, captured_adds):
        session = MagicMock()
        state = {"i": 0}

        async def fake_scalar(_q):
            i = state["i"]
            state["i"] += 1
            return scalar_results[i] if i < len(scalar_results) else None

        async def fake_commit():
            return None

        session.scalar = fake_scalar
        session.commit = fake_commit
        session.add = captured_adds.append
        return session

    def _make_jira_client(self, stale_keys=None):
        stale_keys = stale_keys or set()
        client = MagicMock()

        async def check_stale(key, fetched):
            return key in stale_keys

        async def get_issue(key):
            return {
                "key": key,
                "fields": {"summary": key, "updated": "2026-05-27T00:00:00.000+0000"},
            }

        client.check_stale = AsyncMock(side_effect=check_stale)
        client.get_issue = AsyncMock(side_effect=get_issue)
        client.update_issue = AsyncMock(return_value={})
        client.move_issues_to_sprint = AsyncMock(return_value=None)
        client.assign_issue = AsyncMock(return_value=None)
        return client

    def _install_overrides(self, app, session, role="lead"):
        from src.auth import get_current_org_id, get_current_user_id
        from src.auth_roles import get_current_app_role
        from src.database import get_db

        async def _db():
            yield session

        async def _user():
            return self.LEAD_USER_ID

        async def _org():
            return self.ORG_CLERK_ID

        async def _role_dep():
            return role

        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_current_user_id] = _user
        app.dependency_overrides[get_current_org_id] = _org
        app.dependency_overrides[get_current_app_role] = _role_dep

    @pytest.mark.asyncio
    async def test_happy_path_mixed_approvals(self):
        from httpx import ASGITransport, AsyncClient
        from src.main import app

        captured = []
        # scalar order: Team, JiraConnection, then one TicketAnalysis per committed ticket.
        session = self._setup_session(
            [
                self._make_team(self.TEAM_ID, self.ORG_ID),
                self._make_connection(),
                None,  # TicketAnalysis for edited ticket
                None,  # TicketAnalysis for unedited ticket
            ],
            captured,
        )
        client_mock = self._make_jira_client()

        self._install_overrides(app, session)
        try:
            with patch(
                "src.routers.sprint_brain._get_fresh_client_async",
                AsyncMock(return_value=client_mock),
            ):
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as ac:
                    resp = await ac.post(
                        f"/api/sprint-brain/plans/{self.PLAN_ID}/commit",
                        json={
                            "team_id": str(self.TEAM_ID),
                            "sprint_id": self.SPRINT_ID,
                            "approvals": [
                                {
                                    "ticket_key": "PROJ-1",
                                    "revision": {"title": "New title", "story_points": 5},
                                    "approved_at": "2026-05-27T10:00:00Z",
                                    "fetched_updated_at": "2026-05-27T00:00:00.000+0000",
                                    "assignee_account_id": "acct-1",
                                },
                                {
                                    "ticket_key": "PROJ-2",
                                    "revision": None,
                                    "approved_at": "2026-05-27T10:01:00Z",
                                    "assignee_account_id": "acct-2",
                                },
                            ],
                        },
                    )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert set(body["committed"]) == {"PROJ-1", "PROJ-2"}
        assert body["conflicts"] == []
        assert body["plan_id"] == self.PLAN_ID

        # update_issue called exactly once (only for the edited ticket).
        client_mock.update_issue.assert_awaited_once()
        edited_key, edited_fields = client_mock.update_issue.await_args.args
        assert edited_key == "PROJ-1"
        assert edited_fields["summary"] == "New title"
        assert edited_fields["customfield_10016"] == 5

        # Sprint move + assignee set for BOTH tickets.
        assert client_mock.move_issues_to_sprint.await_count == 2
        assert client_mock.assign_issue.await_count == 2

        # Two audit rows written.
        revisions = [r for r in captured if r.__class__.__name__ == "TicketRevision"]
        assert len(revisions) == 2

    @pytest.mark.asyncio
    async def test_partial_conflict_stale_ticket(self):
        from httpx import ASGITransport, AsyncClient
        from src.main import app

        captured = []
        session = self._setup_session(
            [
                self._make_team(self.TEAM_ID, self.ORG_ID),
                self._make_connection(),
                None,  # TicketAnalysis for the one committed ticket
            ],
            captured,
        )
        client_mock = self._make_jira_client(stale_keys={"PROJ-1"})

        self._install_overrides(app, session)
        try:
            with patch(
                "src.routers.sprint_brain._get_fresh_client_async",
                AsyncMock(return_value=client_mock),
            ):
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as ac:
                    resp = await ac.post(
                        f"/api/sprint-brain/plans/{self.PLAN_ID}/commit",
                        json={
                            "team_id": str(self.TEAM_ID),
                            "sprint_id": self.SPRINT_ID,
                            "approvals": [
                                {
                                    "ticket_key": "PROJ-1",
                                    "revision": {"title": "Edited"},
                                    "approved_at": "2026-05-27T10:00:00Z",
                                    "fetched_updated_at": "2026-05-27T00:00:00.000+0000",
                                },
                                {
                                    "ticket_key": "PROJ-2",
                                    "revision": None,
                                    "approved_at": "2026-05-27T10:01:00Z",
                                    "assignee_account_id": "acct-2",
                                },
                            ],
                        },
                    )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["committed"] == ["PROJ-2"]
        assert body["conflicts"] == [{"ticket_key": "PROJ-1", "reason": "stale"}]

        # Stale ticket's edit must NOT be pushed.
        client_mock.update_issue.assert_not_awaited()
        # Only the committed ticket got moved/assigned.
        assert client_mock.move_issues_to_sprint.await_count == 1
        revisions = [r for r in captured if r.__class__.__name__ == "TicketRevision"]
        assert len(revisions) == 1
        assert revisions[0].ticket_key == "PROJ-2"

    @pytest.mark.asyncio
    async def test_audit_rows_applied_revision_empty_for_unedited(self):
        from httpx import ASGITransport, AsyncClient
        from src.main import app

        captured = []
        session = self._setup_session(
            [
                self._make_team(self.TEAM_ID, self.ORG_ID),
                self._make_connection(),
                None,
                None,
            ],
            captured,
        )
        client_mock = self._make_jira_client()

        self._install_overrides(app, session)
        try:
            with patch(
                "src.routers.sprint_brain._get_fresh_client_async",
                AsyncMock(return_value=client_mock),
            ):
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as ac:
                    resp = await ac.post(
                        f"/api/sprint-brain/plans/{self.PLAN_ID}/commit",
                        json={
                            "team_id": str(self.TEAM_ID),
                            "sprint_id": self.SPRINT_ID,
                            "approvals": [
                                {
                                    "ticket_key": "PROJ-1",
                                    "revision": {"description": "edited desc"},
                                    "approved_at": "2026-05-27T10:00:00Z",
                                },
                                {
                                    "ticket_key": "PROJ-2",
                                    "approved_at": "2026-05-27T10:01:00Z",
                                },
                            ],
                        },
                    )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200, resp.text
        revisions = [r for r in captured if r.__class__.__name__ == "TicketRevision"]
        assert len(revisions) == 2
        by_key = {r.ticket_key: r for r in revisions}
        assert by_key["PROJ-1"].applied_revision == {"description": "edited desc"}
        # Unedited ticket → applied_revision is the empty {} default.
        assert by_key["PROJ-2"].applied_revision == {}

    @pytest.mark.asyncio
    async def test_non_lead_role_returns_403(self):
        from httpx import ASGITransport, AsyncClient
        from src.main import app

        captured = []
        session = self._setup_session([], captured)
        self._install_overrides(app, session, role="developer")
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as ac:
                resp = await ac.post(
                    f"/api/sprint-brain/plans/{self.PLAN_ID}/commit",
                    json={"team_id": str(self.TEAM_ID), "approvals": []},
                )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 403
