from datetime import date
from typing import Literal

HealthTrend = Literal["improving", "stable", "declining"]


def compute_health_score(
    committed: float,
    remaining: float,
    start: date,
    end: date,
    today: date,
    ticket_count: int,
    completed_count: int,
) -> tuple[int, str, list[str]]:
    """
    Extracted from routers/velocity.py._compute_health_score.
    Returns (score 0–100, trend, explanation_bullets).
    Keep the signature identical to the original — velocity.py imports this.
    """
    reasons: list[str] = []
    total_days = max((end - start).days, 1)
    elapsed = max((today - start).days, 0)
    ideal_burned = committed * (elapsed / total_days) if committed > 0 else 0
    actual_burned = committed - remaining

    if committed <= 0:
        pace_score = 20
        reasons.append("No committed points recorded — pace cannot be measured.")
    else:
        ratio = actual_burned / ideal_burned if ideal_burned > 0 else (1.0 if actual_burned > 0 else 0.0)
        pace_score = int(min(40, max(0, ratio * 40)))
        if ratio >= 0.9:
            reasons.append(f"Burn pace is on track ({actual_burned:.0f} of {ideal_burned:.0f} ideal points burned).")
        elif ratio >= 0.6:
            reasons.append(f"Burn pace is slightly behind ({actual_burned:.0f} burned vs {ideal_burned:.0f} ideal).")
        else:
            reasons.append(f"Burn pace is significantly behind — only {actual_burned:.0f} of {ideal_burned:.0f} ideal points burned.")

    completion_ratio = completed_count / ticket_count if ticket_count > 0 else 0.0
    completion_score = int(completion_ratio * 40)
    if completion_ratio >= 0.7:
        reasons.append(f"{completed_count} of {ticket_count} tickets completed ({int(completion_ratio*100)}%).")
    elif completion_ratio >= 0.4:
        reasons.append(f"Moderate progress: {completed_count} of {ticket_count} tickets done ({int(completion_ratio*100)}%).")
    else:
        reasons.append(f"Low ticket completion: only {completed_count} of {ticket_count} tickets done.")

    scope_score = 20 if committed > 0 else 0
    if committed > 0:
        reasons.append(f"Sprint has {committed:.0f} committed points with clear scope.")
    else:
        reasons.append("Sprint has no committed points — consider grooming the backlog.")

    score = pace_score + completion_score + scope_score
    trend = "up" if score >= 60 else ("down" if score <= 40 else "stable")
    return score, trend, reasons
