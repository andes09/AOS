"""Unit tests for :mod:`src.services.skill_intensity`.

All tests are pure-Python: ``team_identifiers`` are built as simple stub
objects exposing the attrs the service reads (``normalized_token``, ``skill``,
``domain``, ``confidence``). No DB session is required for ``compute_intensity``;
``persist_intensity`` / ``compute_and_persist`` are exercised with a mocked
``AsyncSession``.
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest

from src.services.skill_intensity import (
    SkillIntensityResult,
    compute_and_persist,
    compute_intensity,
)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


@dataclass
class FakeIdentifier:
    """Stand-in for a ``TeamIdentifier`` ORM row."""
    normalized_token: str
    skill: str
    domain: str | None = None
    confidence: float = 1.0


def _ids(*items: FakeIdentifier) -> list[FakeIdentifier]:
    return list(items)


# ---------------------------------------------------------------------------
# compute_intensity
# ---------------------------------------------------------------------------


def test_no_matches_returns_empty_vectors() -> None:
    result = compute_intensity(
        ticket_title="A boring sentence with no identifiers",
        ticket_description="Nothing of interest here",
        ticket_labels=[],
        ticket_components=[],
        team_identifiers=_ids(
            FakeIdentifier(normalized_token="orderservice", skill="Java"),
        ),
    )
    assert result.skill_vector == {}
    assert result.domain_vector == {}
    assert result.matched_identifiers == []


def test_single_match_normalizes_to_one() -> None:
    result = compute_intensity(
        ticket_title="OrderService is down",
        ticket_description="",
        ticket_labels=[],
        ticket_components=[],
        team_identifiers=_ids(
            FakeIdentifier(normalized_token="orderservice", skill="Java", confidence=0.8),
        ),
    )
    assert result.skill_vector == {"Java": 1.0}
    assert "OrderService" in result.matched_identifiers


def test_multi_skill_normalized_against_top() -> None:
    # Two hits on Java (orderservice + ms-service), one hit on SQL (dbo.tile_metrics).
    # Verbs are deliberately neutral so weight=1.0 across the board.
    result = compute_intensity(
        ticket_title="OrderService talks to ms-service",
        ticket_description="See dbo.tile_metrics for data",
        ticket_labels=[],
        ticket_components=[],
        team_identifiers=_ids(
            FakeIdentifier(normalized_token="orderservice", skill="Java", confidence=1.0),
            FakeIdentifier(normalized_token="ms-service", skill="Java", confidence=1.0),
            FakeIdentifier(normalized_token="dbo.tile_metrics", skill="SQL", confidence=1.0),
        ),
    )
    assert set(result.skill_vector.keys()) == {"Java", "SQL"}
    assert result.skill_vector["Java"] == 1.0
    # SQL = 1 hit / Java = 2 hits → SQL normalized to 0.5
    assert result.skill_vector["SQL"] == 0.5


def test_high_intensity_verb_boosts_score() -> None:
    boosted = compute_intensity(
        ticket_title="Rewrite OrderService for performance",
        ticket_description="",
        ticket_labels=[],
        ticket_components=[],
        team_identifiers=_ids(
            FakeIdentifier(normalized_token="orderservice", skill="Java", confidence=1.0),
            FakeIdentifier(normalized_token="ms-service", skill="Go", confidence=1.0),
        ),
    )
    neutral = compute_intensity(
        ticket_title="Investigate OrderService timing",
        ticket_description="",
        ticket_labels=[],
        ticket_components=[],
        team_identifiers=_ids(
            FakeIdentifier(normalized_token="orderservice", skill="Java", confidence=1.0),
            FakeIdentifier(normalized_token="ms-service", skill="Go", confidence=1.0),
        ),
    )
    # In the boosted case only Java gets the 1.5x; with no other skill present
    # the normalization makes Java=1.0 either way. Sanity check: it still hits.
    assert boosted.skill_vector["Java"] == 1.0
    assert neutral.skill_vector["Java"] == 1.0
    # Compare raw weighting by including a competing token of equal confidence,
    # using a description that hits ms-service without any verb context.
    mixed = compute_intensity(
        ticket_title="Rewrite OrderService",
        ticket_description="ms-service is mentioned",
        ticket_labels=[],
        ticket_components=[],
        team_identifiers=_ids(
            FakeIdentifier(normalized_token="orderservice", skill="Java", confidence=1.0),
            FakeIdentifier(normalized_token="ms-service", skill="Go", confidence=1.0),
        ),
    )
    # Java got 1.5x boost from "Rewrite", Go got 1.0 → Go normalized to 1/1.5 ≈ 0.667
    assert mixed.skill_vector["Java"] == 1.0
    assert mixed.skill_vector["Go"] == pytest.approx(0.667, abs=0.001)


def test_low_intensity_verb_dampens_score() -> None:
    result = compute_intensity(
        ticket_title="Query dbo.tile_metrics",
        ticket_description="OrderService is referenced",
        ticket_labels=[],
        ticket_components=[],
        team_identifiers=_ids(
            FakeIdentifier(normalized_token="dbo.tile_metrics", skill="SQL", confidence=1.0),
            FakeIdentifier(normalized_token="orderservice", skill="Java", confidence=1.0),
        ),
    )
    # SQL dampened to 0.5, Java neutral 1.0 → Java=1.0, SQL=0.5
    assert result.skill_vector["Java"] == 1.0
    assert result.skill_vector["SQL"] == 0.5


def test_verb_only_counts_within_three_tokens() -> None:
    # "Rewrite" is 5 word-positions before "OrderService" — must NOT boost.
    far = compute_intensity(
        ticket_title="Rewrite the whole legacy crufty OrderService now",
        ticket_description="ms-service mentioned",
        ticket_labels=[],
        ticket_components=[],
        team_identifiers=_ids(
            FakeIdentifier(normalized_token="orderservice", skill="Java", confidence=1.0),
            FakeIdentifier(normalized_token="ms-service", skill="Go", confidence=1.0),
        ),
    )
    # Java did NOT get 1.5x → both skills receive 1.0 each → both normalize to 1.0.
    assert far.skill_vector["Java"] == 1.0
    assert far.skill_vector["Go"] == 1.0


def test_effort_multiplier_scales_proportionally() -> None:
    base = compute_intensity(
        ticket_title="OrderService is failing",
        ticket_description="",
        ticket_labels=[],
        ticket_components=[],
        team_identifiers=_ids(
            FakeIdentifier(normalized_token="orderservice", skill="Java", confidence=0.6),
        ),
        effort_multiplier=1.0,
    )
    scaled = compute_intensity(
        ticket_title="OrderService is failing",
        ticket_description="",
        ticket_labels=[],
        ticket_components=[],
        team_identifiers=_ids(
            FakeIdentifier(normalized_token="orderservice", skill="Java", confidence=0.6),
        ),
        effort_multiplier=1.5,
    )
    # Because normalization is max=1, a single-skill ticket is invariant — but the
    # raw multiplier should propagate proportionally before normalization, so for
    # multi-skill tickets the *relative* ordering should not change with effort.
    assert base.skill_vector == {"Java": 1.0}
    assert scaled.skill_vector == {"Java": 1.0}

    # Now with two skills, scaling everything by the same multiplier must
    # preserve relative proportions (a property worth pinning down explicitly):
    two_a = compute_intensity(
        ticket_title="OrderService meets ms-service",
        ticket_description="See dbo.tile_metrics for data",
        ticket_labels=[],
        ticket_components=[],
        team_identifiers=_ids(
            FakeIdentifier(normalized_token="orderservice", skill="Java", confidence=1.0),
            FakeIdentifier(normalized_token="ms-service", skill="Java", confidence=1.0),
            FakeIdentifier(normalized_token="dbo.tile_metrics", skill="SQL", confidence=1.0),
        ),
        effort_multiplier=0.5,
    )
    two_b = compute_intensity(
        ticket_title="OrderService meets ms-service",
        ticket_description="See dbo.tile_metrics for data",
        ticket_labels=[],
        ticket_components=[],
        team_identifiers=_ids(
            FakeIdentifier(normalized_token="orderservice", skill="Java", confidence=1.0),
            FakeIdentifier(normalized_token="ms-service", skill="Java", confidence=1.0),
            FakeIdentifier(normalized_token="dbo.tile_metrics", skill="SQL", confidence=1.0),
        ),
        effort_multiplier=1.5,
    )
    assert two_a.skill_vector == two_b.skill_vector  # invariant under uniform scaling


def test_matched_identifiers_preserved_in_order_and_deduped() -> None:
    result = compute_intensity(
        ticket_title="OrderService and ms-service",
        ticket_description="OrderService again, plus dbo.tile_metrics",
        ticket_labels=["ms-service"],
        ticket_components=[],
        team_identifiers=_ids(
            FakeIdentifier(normalized_token="orderservice", skill="Java"),
            FakeIdentifier(normalized_token="ms-service", skill="Java"),
            FakeIdentifier(normalized_token="dbo.tile_metrics", skill="SQL"),
        ),
    )
    # First appearance order: OrderService (title), ms-service (title),
    # dbo.tile_metrics (description). The label hit on ms-service is deduped.
    assert result.matched_identifiers == ["OrderService", "ms-service", "dbo.tile_metrics"]


def test_domain_vector_computed_in_parallel() -> None:
    result = compute_intensity(
        ticket_title="OrderService meets ms-service",
        ticket_description="See dbo.tile_metrics for data",
        ticket_labels=[],
        ticket_components=[],
        team_identifiers=_ids(
            FakeIdentifier(normalized_token="orderservice", skill="Java", domain="backend", confidence=1.0),
            FakeIdentifier(normalized_token="ms-service", skill="Java", domain="backend", confidence=1.0),
            FakeIdentifier(normalized_token="dbo.tile_metrics", skill="SQL", domain="data", confidence=1.0),
        ),
    )
    assert set(result.domain_vector.keys()) == {"backend", "data"}
    assert result.domain_vector["backend"] == 1.0
    assert result.domain_vector["data"] == 0.5


def test_labels_and_components_are_scanned() -> None:
    result = compute_intensity(
        ticket_title="ticket",
        ticket_description="",
        ticket_labels=["ms-service"],
        ticket_components=["dbo.tile_metrics"],
        team_identifiers=_ids(
            FakeIdentifier(normalized_token="ms-service", skill="Go", confidence=1.0),
            FakeIdentifier(normalized_token="dbo.tile_metrics", skill="SQL", confidence=1.0),
        ),
    )
    assert set(result.skill_vector.keys()) == {"Go", "SQL"}
    # Both contribute equally with weight 1.0 → both normalize to 1.0.
    assert result.skill_vector["Go"] == 1.0
    assert result.skill_vector["SQL"] == 1.0
    assert "ms-service" in result.matched_identifiers
    assert "dbo.tile_metrics" in result.matched_identifiers


# ---------------------------------------------------------------------------
# Integration-style: compute_and_persist with a mocked AsyncSession
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compute_and_persist_executes_upsert() -> None:
    db = AsyncMock()
    db.execute = AsyncMock()

    @dataclass
    class FakeTicket:
        id: str
        title: str
        labels: list[str]
        components: list[str]

    ticket = FakeTicket(
        id="11111111-1111-1111-1111-111111111111",
        title="Rewrite OrderService",
        labels=[],
        components=[],
    )

    result = await compute_and_persist(
        ticket=ticket,
        team_identifiers=_ids(
            FakeIdentifier(normalized_token="orderservice", skill="Java", confidence=1.0),
        ),
        db=db,
        effort_multiplier=1.0,
        ticket_description="",
    )

    assert isinstance(result, SkillIntensityResult)
    assert result.skill_vector == {"Java": 1.0}
    db.execute.assert_awaited_once()
