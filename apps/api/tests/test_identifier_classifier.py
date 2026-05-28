"""Tests for :mod:`src.services.identifier_classifier`.

We mock ``anthropic.AsyncAnthropic`` — no live API traffic. The mock pattern
mirrors ``tests/test_sprint_brain.py``:

  with patch("src.services.identifier_classifier.anthropic.AsyncAnthropic") as MockClient:
      instance = MockClient.return_value
      instance.messages.create = AsyncMock(...)

Coverage targets the locked decisions in the SA-4 spec:
- single batch happy path
- batching boundary (75 tokens, batch_size=50 → 2 Claude calls)
- partial responses default missing tokens to unknown / 0.0
- hallucinated skill labels are coerced to "unknown"
- raw_token + occurrence_count pass through verbatim
- empty input short-circuits with zero Claude calls
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.identifier_classifier import (
    ClassifiedIdentifier,
    classify_identifiers,
)


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _mock_tool_response(classifications: list[dict]):
    """Build a mock anthropic.Message whose content is one tool_use block."""
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.name = "classify_identifiers"
    tool_block.input = {"classifications": classifications}

    response = MagicMock()
    response.content = [tool_block]
    return response


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_batch_returns_one_result_per_token() -> None:
    tokens = [
        ("dbo.tile_metrics", "dbo.tile_metrics", 12),
        ("OrderController", "ordercontroller", 5),
        ("ms-billing", "ms-billing", 3),
    ]
    team_stack = ["SQL", "Java/Spring Boot"]
    classifications = [
        {
            "normalized_token": "dbo.tile_metrics",
            "skill": "SQL",
            "domain": "data",
            "confidence": 0.95,
        },
        {
            "normalized_token": "ordercontroller",
            "skill": "Java/Spring Boot",
            "domain": "backend",
            "confidence": 0.9,
        },
        {
            "normalized_token": "ms-billing",
            "skill": "Java/Spring Boot",
            "domain": "backend",
            "confidence": 0.55,
        },
    ]

    with patch(
        "src.services.identifier_classifier.anthropic.AsyncAnthropic"
    ) as MockClient:
        instance = MockClient.return_value
        instance.messages.create = AsyncMock(
            return_value=_mock_tool_response(classifications)
        )

        results = await classify_identifiers(tokens, team_stack, "sk-ant-test")

    assert instance.messages.create.await_count == 1
    assert len(results) == 3
    assert all(isinstance(r, ClassifiedIdentifier) for r in results)

    by_norm = {r.normalized_token: r for r in results}
    assert by_norm["dbo.tile_metrics"].skill == "SQL"
    assert by_norm["dbo.tile_metrics"].domain == "data"
    assert by_norm["dbo.tile_metrics"].confidence == pytest.approx(0.95)
    assert by_norm["ordercontroller"].skill == "Java/Spring Boot"
    assert by_norm["ordercontroller"].domain == "backend"
    assert by_norm["ms-billing"].confidence == pytest.approx(0.55)


@pytest.mark.asyncio
async def test_batching_splits_into_multiple_claude_calls() -> None:
    # 75 tokens, batch_size=50 → 2 Claude calls (50 + 25).
    tokens = [(f"tok{i}", f"tok{i}", 1) for i in range(75)]
    team_stack = ["Python"]

    first_batch = [
        {
            "normalized_token": f"tok{i}",
            "skill": "Python",
            "domain": "backend",
            "confidence": 0.8,
        }
        for i in range(50)
    ]
    second_batch = [
        {
            "normalized_token": f"tok{i}",
            "skill": "Python",
            "domain": "backend",
            "confidence": 0.8,
        }
        for i in range(50, 75)
    ]

    with patch(
        "src.services.identifier_classifier.anthropic.AsyncAnthropic"
    ) as MockClient:
        instance = MockClient.return_value
        instance.messages.create = AsyncMock(
            side_effect=[
                _mock_tool_response(first_batch),
                _mock_tool_response(second_batch),
            ]
        )

        results = await classify_identifiers(
            tokens, team_stack, "sk-ant-test", batch_size=50
        )

    assert instance.messages.create.await_count == 2
    assert len(results) == 75
    assert {r.skill for r in results} == {"Python"}
    # Order preserved
    assert [r.normalized_token for r in results] == [f"tok{i}" for i in range(75)]


@pytest.mark.asyncio
async def test_missing_classifications_default_to_unknown() -> None:
    tokens = [
        ("alpha", "alpha", 4),
        ("beta", "beta", 3),
        ("gamma", "gamma", 2),
    ]
    team_stack = ["Python"]
    # Claude only returns one of the three
    classifications = [
        {
            "normalized_token": "alpha",
            "skill": "Python",
            "domain": "backend",
            "confidence": 0.9,
        },
    ]

    with patch(
        "src.services.identifier_classifier.anthropic.AsyncAnthropic"
    ) as MockClient:
        instance = MockClient.return_value
        instance.messages.create = AsyncMock(
            return_value=_mock_tool_response(classifications)
        )

        results = await classify_identifiers(tokens, team_stack, "sk-ant-test")

    assert len(results) == 3
    by_norm = {r.normalized_token: r for r in results}
    assert by_norm["alpha"].skill == "Python"
    assert by_norm["beta"].skill == "unknown"
    assert by_norm["beta"].domain is None
    assert by_norm["beta"].confidence == 0.0
    assert by_norm["gamma"].skill == "unknown"
    assert by_norm["gamma"].confidence == 0.0


@pytest.mark.asyncio
async def test_hallucinated_skill_is_coerced_to_unknown() -> None:
    """Decision: skills not in team_stack are coerced to 'unknown' server-side.

    This keeps the downstream contract clean — intensity service (SA-6) can
    trust that ``skill`` is either a team_stack label or the literal string
    ``"unknown"``.
    """
    tokens = [
        ("alpha", "alpha", 1),
        ("beta", "beta", 1),
    ]
    team_stack = ["Python"]
    classifications = [
        {
            "normalized_token": "alpha",
            "skill": "Rust",  # hallucinated — not in team_stack
            "domain": "backend",
            "confidence": 0.9,
        },
        {
            "normalized_token": "beta",
            "skill": "Python",
            "domain": "frontend",
            "confidence": 0.7,
        },
    ]

    with patch(
        "src.services.identifier_classifier.anthropic.AsyncAnthropic"
    ) as MockClient:
        instance = MockClient.return_value
        instance.messages.create = AsyncMock(
            return_value=_mock_tool_response(classifications)
        )

        results = await classify_identifiers(tokens, team_stack, "sk-ant-test")

    by_norm = {r.normalized_token: r for r in results}
    assert by_norm["alpha"].skill == "unknown"
    # confidence is still preserved — caller decides whether to use it
    assert by_norm["alpha"].confidence == pytest.approx(0.9)
    assert by_norm["beta"].skill == "Python"
    assert by_norm["beta"].domain == "frontend"


@pytest.mark.asyncio
async def test_raw_token_and_occurrence_count_preserved() -> None:
    """``token`` and ``occurrence_count`` round-trip verbatim regardless of normalization."""
    tokens = [
        # raw differs from normalized (mixed case + trailing punctuation stripped upstream)
        ("dbo.Tile_Metrics", "dbo.tile_metrics", 42),
        ("MS-Billing", "ms-billing", 17),
    ]
    team_stack = ["SQL", "Java/Spring Boot"]
    classifications = [
        {
            "normalized_token": "dbo.tile_metrics",
            "skill": "SQL",
            "domain": "data",
            "confidence": 0.95,
        },
        {
            "normalized_token": "ms-billing",
            "skill": "Java/Spring Boot",
            "domain": "backend",
            "confidence": 0.85,
        },
    ]

    with patch(
        "src.services.identifier_classifier.anthropic.AsyncAnthropic"
    ) as MockClient:
        instance = MockClient.return_value
        instance.messages.create = AsyncMock(
            return_value=_mock_tool_response(classifications)
        )

        results = await classify_identifiers(tokens, team_stack, "sk-ant-test")

    by_norm = {r.normalized_token: r for r in results}
    assert by_norm["dbo.tile_metrics"].token == "dbo.Tile_Metrics"
    assert by_norm["dbo.tile_metrics"].occurrence_count == 42
    assert by_norm["ms-billing"].token == "MS-Billing"
    assert by_norm["ms-billing"].occurrence_count == 17


@pytest.mark.asyncio
async def test_unknown_domain_normalizes_to_none() -> None:
    """``domain="unknown"`` from Claude is stored as ``None`` so DB columns stay clean."""
    tokens = [("alpha", "alpha", 1)]
    team_stack = ["Python"]
    classifications = [
        {
            "normalized_token": "alpha",
            "skill": "unknown",
            "domain": "unknown",
            "confidence": 0.2,
        },
    ]

    with patch(
        "src.services.identifier_classifier.anthropic.AsyncAnthropic"
    ) as MockClient:
        instance = MockClient.return_value
        instance.messages.create = AsyncMock(
            return_value=_mock_tool_response(classifications)
        )

        results = await classify_identifiers(tokens, team_stack, "sk-ant-test")

    assert len(results) == 1
    assert results[0].skill == "unknown"
    assert results[0].domain is None
    assert results[0].confidence == pytest.approx(0.2)


@pytest.mark.asyncio
async def test_empty_input_short_circuits() -> None:
    """No tokens → no Claude calls, empty result."""
    with patch(
        "src.services.identifier_classifier.anthropic.AsyncAnthropic"
    ) as MockClient:
        instance = MockClient.return_value
        instance.messages.create = AsyncMock()

        results = await classify_identifiers([], ["Python"], "sk-ant-test")

    assert results == []
    instance.messages.create.assert_not_awaited()
