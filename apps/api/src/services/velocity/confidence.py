# apps/api/src/services/velocity/confidence.py
import math
import statistics
from .schemas import AdjustedBudget, ConfidenceInterval

# z-scores for two-tailed normal confidence intervals
# NOTE: Normal approximation. For n < 30, a t-distribution is more accurate.
#       Replace with scipy.stats.t.ppf when scipy is added to dependencies.
_Z_SCORES: dict[float, float] = {
    0.80: 1.282,
    0.90: 1.645,
    0.95: 1.960,
    0.99: 2.576,
}


class ConfidenceEngine:
    """
    Wraps historical sprint point totals in a probability interval.

    Input:  historical_sprints — list of sprints, each sprint is a list of AdjustedBudget.
            The LAST sprint is treated as the current sprint for team_total_adjusted.
    Output: ConfidenceInterval with lower/upper bounds at the given confidence level.
    """

    def calculate(
        self,
        historical_sprints: list[list[AdjustedBudget]],
        confidence_level: float = 0.90,
    ) -> ConfidenceInterval:
        if confidence_level not in _Z_SCORES:
            raise ValueError(
                f"confidence_level must be one of {sorted(_Z_SCORES)}; got {confidence_level}"
            )

        # Sum team points per sprint
        totals = [
            sum(b.adjusted_points for b in sprint)
            for sprint in historical_sprints
        ]
        current_total = totals[-1] if totals else 0.0

        # Degenerate: not enough data to compute a spread
        if len(totals) < 2:
            val = totals[0] if totals else 0.0
            return ConfidenceInterval(
                lower_bound=val,
                upper_bound=val,
                confidence_level=confidence_level,
                team_total_adjusted=val,
            )

        mean = statistics.mean(totals)
        stdev = statistics.stdev(totals)
        n = len(totals)
        z = _Z_SCORES[confidence_level]
        margin = z * stdev / math.sqrt(n)

        return ConfidenceInterval(
            # Clamp lower to 0 — points cannot be negative. Note: this makes the
            # interval asymmetric when clamping fires; coverage exceeds confidence_level.
            lower_bound=round(max(0.0, mean - margin), 2),
            upper_bound=round(mean + margin, 2),
            confidence_level=confidence_level,
            team_total_adjusted=current_total,
        )
