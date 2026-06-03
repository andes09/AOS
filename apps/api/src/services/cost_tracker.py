"""
AI cost tracking — computes the USD cost of a Claude generation from token
usage and emits a single structured log line per generation.

Disable via the `cost_tracking` feature flag (config/features/{env}.yaml).
When the flag is off, record_generation_cost() is a no-op and nothing is logged.
The recorder is also exception-safe: cost tracking must never break a
generation, so any failure is swallowed with a warning.

Pricing reflects Claude Sonnet 4.6 list prices (USD per million tokens).
If the model in sprint_brain changes, update _PER_MTOK and verify against
https://www.anthropic.com/pricing.
"""

from __future__ import annotations

import csv
import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from src.config import settings

_CSV_PATH = Path(__file__).resolve().parent.parent.parent / "sprint_cost_log.csv"

logger = logging.getLogger(__name__)

_FLAG = "cost_tracking"

# USD per 1,000,000 tokens — Claude Sonnet 4.6.
# cache_write = 1.25x input, cache_read = 0.1x input.
_PER_MTOK = {
    "input": 3.00,
    "output": 15.00,
    "cache_write": 3.75,
    "cache_read": 0.30,
}


@dataclass(frozen=True)
class CostBreakdown:
    input_tokens: int
    output_tokens: int
    cache_write_tokens: int
    cache_read_tokens: int
    call_count: int
    cost_usd: float


def compute_cost(usages: Iterable) -> CostBreakdown:
    """Sum token counts across one or more Anthropic `usage` objects and price them."""
    input_t = output_t = cache_w = cache_r = 0
    calls = 0
    for u in usages:
        if u is None:
            continue
        calls += 1
        input_t += getattr(u, "input_tokens", 0) or 0
        output_t += getattr(u, "output_tokens", 0) or 0
        cache_w += getattr(u, "cache_creation_input_tokens", 0) or 0
        cache_r += getattr(u, "cache_read_input_tokens", 0) or 0

    cost = (
        input_t * _PER_MTOK["input"]
        + output_t * _PER_MTOK["output"]
        + cache_w * _PER_MTOK["cache_write"]
        + cache_r * _PER_MTOK["cache_read"]
    ) / 1_000_000

    return CostBreakdown(
        input_tokens=input_t,
        output_tokens=output_t,
        cache_write_tokens=cache_w,
        cache_read_tokens=cache_r,
        call_count=calls,
        cost_usd=round(cost, 6),
    )


def is_enabled() -> bool:
    """True when the cost_tracking feature flag is on. Defaults to False on any error."""
    try:
        return settings.is_feature_enabled(_FLAG)
    except Exception:
        return False


_CSV_HEADERS = [
    "date", "model", "total_tokens", "input_tokens", "output_tokens",
    "total_price_usd", "price_per_ticket_usd",
]


def _append_csv_row(breakdown: CostBreakdown, model: str, assigned_count: int) -> None:
    total_tokens = breakdown.input_tokens + breakdown.output_tokens
    price_per_ticket = breakdown.cost_usd / assigned_count if assigned_count else 0.0
    row = {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "model": model,
        "total_tokens": total_tokens,
        "input_tokens": breakdown.input_tokens,
        "output_tokens": breakdown.output_tokens,
        "total_price_usd": f"${breakdown.cost_usd:.2f}",
        "price_per_ticket_usd": f"${price_per_ticket:.2f}",
    }
    write_header = not _CSV_PATH.exists() or os.path.getsize(_CSV_PATH) == 0
    with open(_CSV_PATH, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_HEADERS)
        if write_header:
            writer.writeheader()
        writer.writerow(row)


def record_generation_cost(
    operation: str,
    *usages,
    **context,
) -> CostBreakdown | None:
    """
    Compute and log the cost of a single generation.

    `usages` are the `.usage` objects from each Claude response that made up the
    generation (e.g. the complexity call + the assignment call). `context` is
    extra structured metadata to attach (team_id, ticket_count, ...).

    Returns the CostBreakdown, or None when tracking is disabled or fails.
    """
    if not is_enabled():
        return None
    try:
        breakdown = compute_cost(usages)
        logger.info(
            "ai_cost operation=%s cost_usd=%.6f input_tokens=%d output_tokens=%d "
            "cache_read_tokens=%d cache_write_tokens=%d calls=%d%s",
            operation,
            breakdown.cost_usd,
            breakdown.input_tokens,
            breakdown.output_tokens,
            breakdown.cache_read_tokens,
            breakdown.cache_write_tokens,
            breakdown.call_count,
            "".join(f" {k}={v}" for k, v in context.items()),
            extra={"ai_cost": {"operation": operation, **asdict(breakdown), **context}},
        )
        if operation in ("sprint_plan", "scope_cop"):
            try:
                _append_csv_row(
                    breakdown,
                    model=context.get("model", "unknown"),
                    assigned_count=context.get("assigned_count", 0),
                )
            except Exception:
                logger.warning("cost_tracker._append_csv_row failed", exc_info=True)
        return breakdown
    except Exception:
        logger.warning("cost_tracker.record_generation_cost failed", exc_info=True)
        return None
