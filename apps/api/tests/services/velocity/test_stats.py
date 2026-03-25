"""Unit tests for velocity stats calculation logic."""
import pytest
from src.services.velocity.stats import compute_velocity_stats


def test_rolling_avg_known_value():
    """Rolling avg of [30, 40, 50] == 40.0 exactly."""
    velocities = [10.0, 20.0, 30.0, 40.0, 50.0]
    result = compute_velocity_stats(velocities, window=3)
    assert result.rolling_avg == pytest.approx(40.0)


def test_weighted_avg_weights_recent_more():
    """For an increasing sequence, weighted avg should exceed simple rolling avg."""
    velocities = [20.0, 30.0, 40.0, 50.0, 60.0]
    result = compute_velocity_stats(velocities, window=3, lambda_=0.5)
    assert result.weighted_avg > result.rolling_avg


def test_trend_positive_for_increasing_sequence():
    velocities = [10.0, 20.0, 30.0, 40.0, 50.0]
    result = compute_velocity_stats(velocities, window=5)
    assert result.trend > 0


def test_trend_negative_for_decreasing_sequence():
    velocities = [50.0, 40.0, 30.0, 20.0, 10.0]
    result = compute_velocity_stats(velocities, window=5)
    assert result.trend < 0


def test_outlier_detection_flags_extreme_values():
    """A sprint far above the mean should be flagged as an outlier."""
    velocities = [20.0, 22.0, 21.0, 23.0, 100.0]
    result = compute_velocity_stats(velocities, window=5)
    assert 4 in result.outlier_sprint_indices


def test_no_outliers_for_uniform_data():
    velocities = [30.0, 30.0, 30.0, 30.0, 30.0]
    result = compute_velocity_stats(velocities, window=5)
    assert result.outlier_sprint_indices == []


def test_confidence_interval_contains_rolling_avg():
    velocities = [30.0, 35.0, 28.0, 32.0, 31.0]
    result = compute_velocity_stats(velocities, window=5)
    assert result.ci_lower <= result.rolling_avg <= result.ci_upper


def test_single_data_point_does_not_crash():
    """Service should return gracefully with std_dev=0 and trend=0."""
    result = compute_velocity_stats([42.0], window=3)
    assert result.rolling_avg == pytest.approx(42.0)
    assert result.std_dev == 0.0
    assert result.trend == 0.0
    assert result.outlier_sprint_indices == []


def test_empty_velocities_returns_zeros():
    result = compute_velocity_stats([], window=3)
    assert result.rolling_avg == 0.0


def test_window_larger_than_data_uses_all_available():
    """Window should clamp to available data, not crash."""
    velocities = [20.0, 30.0, 40.0]
    result = compute_velocity_stats(velocities, window=10)
    assert result.rolling_avg == pytest.approx(30.0)


def test_forecast_point_equals_rolling_avg_plus_trend():
    velocities = [10.0, 20.0, 30.0, 40.0, 50.0]
    result = compute_velocity_stats(velocities, window=5)
    expected = max(0.0, round(result.rolling_avg + result.trend, 2))
    assert result.forecast_point == pytest.approx(expected)


def test_forecast_ci_is_wider_than_zero():
    velocities = [28.0, 32.0, 30.0, 35.0, 27.0]
    result = compute_velocity_stats(velocities, window=5)
    assert result.forecast_upper > result.forecast_lower
