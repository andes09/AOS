# apps/api/tests/services/velocity/test_confidence.py
import pytest
from src.services.velocity.confidence import ConfidenceEngine
from src.services.velocity.schemas import AdjustedBudget


def budget(dev, points):
    return AdjustedBudget(
        developer_id=dev,
        baseline_velocity=points,
        availability_ratio=1.0,
        adjusted_points=points,
    )


def sprint_of(*args):
    """Helper: list of budgets for one sprint."""
    return list(args)


def test_consistent_sprints_narrow_interval():
    engine = ConfidenceEngine()
    historical = [
        sprint_of(budget("alice", 10), budget("bob", 10)),  # team = 20
        sprint_of(budget("alice", 10), budget("bob", 10)),
        sprint_of(budget("alice", 10), budget("bob", 10)),
        sprint_of(budget("alice", 10), budget("bob", 10)),
        sprint_of(budget("alice", 10), budget("bob", 10)),
    ]
    result = engine.calculate(historical, confidence_level=0.90)
    assert result.lower_bound <= 20.0 <= result.upper_bound
    assert result.confidence_level == 0.90
    assert result.team_total_adjusted == 20.0
    # Perfect consistency → interval should be very narrow (near zero stdev)
    assert result.upper_bound - result.lower_bound < 1.0


def test_high_variance_wide_interval():
    engine = ConfidenceEngine()
    historical = [
        sprint_of(budget("alice", 5)),
        sprint_of(budget("alice", 25)),
        sprint_of(budget("alice", 3)),
        sprint_of(budget("alice", 22)),
        sprint_of(budget("alice", 8)),
    ]
    result = engine.calculate(historical, confidence_level=0.90)
    # High variance → wide interval
    assert result.upper_bound - result.lower_bound > 10.0


def test_single_sprint_degenerate_point_interval():
    engine = ConfidenceEngine()
    historical = [sprint_of(budget("alice", 15))]
    result = engine.calculate(historical, confidence_level=0.90)
    assert result.lower_bound == result.upper_bound == 15.0
    assert result.team_total_adjusted == 15.0


def test_lower_bound_never_negative():
    engine = ConfidenceEngine()
    historical = [
        sprint_of(budget("alice", 1)),
        sprint_of(budget("alice", 2)),
        sprint_of(budget("alice", 1)),
        sprint_of(budget("alice", 2)),
        sprint_of(budget("alice", 1)),
    ]
    result = engine.calculate(historical, confidence_level=0.99)
    assert result.lower_bound >= 0.0


def test_team_total_reflects_last_sprint():
    """team_total_adjusted should be the sum of the LAST sprint in historical."""
    engine = ConfidenceEngine()
    historical = [
        sprint_of(budget("alice", 10)),
        sprint_of(budget("alice", 5), budget("bob", 8)),  # last sprint total = 13
    ]
    result = engine.calculate(historical, confidence_level=0.90)
    assert result.team_total_adjusted == 13.0


def test_interval_widens_with_higher_confidence():
    engine = ConfidenceEngine()
    historical = [
        sprint_of(budget("alice", 8)),
        sprint_of(budget("alice", 12)),
        sprint_of(budget("alice", 7)),
        sprint_of(budget("alice", 13)),
        sprint_of(budget("alice", 10)),
    ]
    r90 = engine.calculate(historical, confidence_level=0.90)
    r99 = engine.calculate(historical, confidence_level=0.99)
    width_90 = r90.upper_bound - r90.lower_bound
    width_99 = r99.upper_bound - r99.lower_bound
    assert width_99 >= width_90


def test_unsupported_confidence_level_raises():
    engine = ConfidenceEngine()
    historical = [
        sprint_of(budget("alice", 10)),
        sprint_of(budget("alice", 10)),
    ]
    with pytest.raises(ValueError, match="confidence_level"):
        engine.calculate(historical, confidence_level=0.50)


def test_empty_historical_returns_zero_point_interval():
    """No sprint history at all → degenerate interval at 0.0, no crash."""
    engine = ConfidenceEngine()
    result = engine.calculate([], confidence_level=0.90)
    assert result.lower_bound == result.upper_bound == 0.0
    assert result.team_total_adjusted == 0.0
