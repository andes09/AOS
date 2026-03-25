"""Pure statistical velocity calculations. No database coupling."""
from dataclasses import dataclass
import math
import numpy as np


@dataclass
class VelocityStats:
    rolling_avg: float
    weighted_avg: float
    std_dev: float
    trend: float
    ci_lower: float       # 90% CI lower bound around rolling_avg
    ci_upper: float       # 90% CI upper bound around rolling_avg
    outlier_sprint_indices: list[int]   # indices into the window slice
    forecast_point: float
    forecast_lower: float
    forecast_upper: float


def compute_velocity_stats(
    velocities: list[float],
    window: int = 6,
    lambda_: float = 0.3,
) -> VelocityStats:
    """
    Compute statistical velocity metrics over the last `window` sprints.

    Gracefully handles short input — variance-dependent fields (std_dev, trend,
    CI) default to 0.0 when only one data point is available. The caller is
    responsible for enforcing a minimum sprint count before calling this.

    Args:
        velocities: Sprint delivered_points ordered oldest → newest.
        window:     Number of recent sprints to analyze (3–12).
        lambda_:    Exponential decay factor (0 < λ < 1).
                    Higher = more weight on recent sprints.

    Returns:
        VelocityStats with all computed metrics.
    """
    if not velocities:
        return VelocityStats(
            rolling_avg=0.0, weighted_avg=0.0, std_dev=0.0, trend=0.0,
            ci_lower=0.0, ci_upper=0.0, outlier_sprint_indices=[],
            forecast_point=0.0, forecast_lower=0.0, forecast_upper=0.0,
        )

    window_vals = np.array(velocities[-window:], dtype=float)
    n = len(window_vals)

    rolling_avg = float(np.mean(window_vals))

    # Exponential weights: w_i = (1 - λ)^(n-1-i), normalized so sum == 1
    weights = np.array([(1 - lambda_) ** (n - 1 - i) for i in range(n)])
    weights /= weights.sum()
    weighted_avg = float(np.dot(weights, window_vals))

    std_dev = float(np.std(window_vals, ddof=1)) if n > 1 else 0.0

    # Linear trend: slope of OLS regression over the window (points/sprint)
    trend = float(np.polyfit(np.arange(n), window_vals, 1)[0]) if n > 1 else 0.0

    # 90% CI around rolling_avg (z = 1.645 for two-sided 90%)
    margin = 1.645 * std_dev / math.sqrt(n) if n > 0 else 0.0
    ci_lower = round(max(0.0, rolling_avg - margin), 2)
    ci_upper = round(rolling_avg + margin, 2)

    # Outliers: |v - mean| > 1.5 * std_dev within the window
    outlier_sprint_indices = [
        i for i, v in enumerate(window_vals)
        if std_dev > 0 and abs(v - rolling_avg) > 1.5 * std_dev
    ]

    # Forecast: one sprint ahead = rolling_avg + trend, same CI margin
    forecast_point = round(max(0.0, rolling_avg + trend), 2)
    forecast_lower = round(max(0.0, forecast_point - margin), 2)
    forecast_upper = round(forecast_point + margin, 2)

    return VelocityStats(
        rolling_avg=round(rolling_avg, 2),
        weighted_avg=round(weighted_avg, 2),
        std_dev=round(std_dev, 2),
        trend=round(trend, 2),
        ci_lower=ci_lower,
        ci_upper=ci_upper,
        outlier_sprint_indices=outlier_sprint_indices,
        forecast_point=forecast_point,
        forecast_lower=forecast_lower,
        forecast_upper=forecast_upper,
    )
