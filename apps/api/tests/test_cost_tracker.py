"""Tests for the AI cost tracking module."""

from types import SimpleNamespace
from unittest.mock import patch

from src.services import cost_tracker
from src.services.cost_tracker import CostBreakdown, compute_cost, record_generation_cost


def _usage(input_tokens=0, output_tokens=0, cache_write=0, cache_read=0):
    return SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_input_tokens=cache_write,
        cache_read_input_tokens=cache_read,
    )


def test_compute_cost_sums_and_prices_multiple_calls():
    # 1M input + 1M output across two calls → $3 + $15 = $18.
    breakdown = compute_cost([_usage(input_tokens=1_000_000), _usage(output_tokens=1_000_000)])
    assert breakdown == CostBreakdown(
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cache_write_tokens=0,
        cache_read_tokens=0,
        call_count=2,
        cost_usd=18.0,
    )


def test_compute_cost_prices_cache_tokens():
    # 1M cache write ($3.75) + 1M cache read ($0.30) = $4.05.
    breakdown = compute_cost([_usage(cache_write=1_000_000, cache_read=1_000_000)])
    assert breakdown.cost_usd == 4.05


def test_compute_cost_ignores_none_usages():
    breakdown = compute_cost([None, _usage(input_tokens=1_000_000), None])
    assert breakdown.call_count == 1
    assert breakdown.cost_usd == 3.0


def test_record_is_noop_when_disabled():
    with patch.object(cost_tracker, "is_enabled", return_value=False):
        assert record_generation_cost("sprint_plan", _usage(input_tokens=1_000_000)) is None


def test_record_logs_when_enabled(caplog):
    with patch.object(cost_tracker, "is_enabled", return_value=True):
        with caplog.at_level("INFO"):
            breakdown = record_generation_cost(
                "sprint_plan",
                _usage(input_tokens=1_000_000),
                team_id="team-1",
            )
    assert breakdown is not None
    assert breakdown.cost_usd == 3.0
    assert "ai_cost operation=sprint_plan" in caplog.text
    assert "team_id=team-1" in caplog.text


def test_record_swallows_errors():
    # A usage object that raises on attribute access must not propagate.
    class Boom:
        def __getattr__(self, name):
            raise RuntimeError("boom")

    with patch.object(cost_tracker, "is_enabled", return_value=True):
        assert record_generation_cost("sprint_plan", Boom()) is None
