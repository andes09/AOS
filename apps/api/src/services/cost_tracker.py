"""
AI cost tracking — computes the USD cost of a generation from token usage,
emits a structured log line, and persists one row per generation to the
`ai_usage_events` table (see src/models/ai_usage_event.py) for the platform
admin dashboard.

Disable via the `cost_tracking` feature flag (config/features/{env}.yaml).
When the flag is off, record_generation_cost() is a no-op and nothing is
logged or persisted.

Pricing is provider-aware: Anthropic calls (input_tokens/output_tokens,
cache_creation_input_tokens/cache_read_input_tokens) are priced against
_PER_MTOK (Claude Sonnet 4.6 list prices); Groq calls (prompt_tokens/
completion_tokens, no cache fields) are priced against _GROQ_PER_MTOK
(Llama 3.3 70B Versatile list prices, verified at https://groq.com/pricing
on 2026-07-28 — $0.59 / $0.79 per MTok in/out). If either model changes,
update the relevant table and re-verify.

The recorder is exception-safe in two independent ways:
1. The whole function never raises — any failure (bad usage object, DB down,
   etc.) is swallowed with a warning. Cost tracking must never break the
   generation it's attached to.
2. DB persistence runs in its OWN short-lived AsyncSession (never the
   caller's), so a failed insert can't poison or roll back the caller's own
   transaction — it can only fail to log a cost row.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

from src.config import settings
from src.database import AsyncSessionLocal
from src.models.ai_usage_event import AIUsageEvent

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

# USD per 1,000,000 tokens — Llama 3.3 70B Versatile (Groq). No cache
# pricing: Groq's OpenAI-compatible usage objects don't expose cache fields.
_GROQ_PER_MTOK = {
    "input": 0.59,
    "output": 0.79,
    "cache_write": 0.0,
    "cache_read": 0.0,
}

_PRICING_BY_PROVIDER = {
    "anthropic": _PER_MTOK,
    "groq": _GROQ_PER_MTOK,
}


@dataclass(frozen=True)
class CostBreakdown:
    input_tokens: int
    output_tokens: int
    cache_write_tokens: int
    cache_read_tokens: int
    call_count: int
    cost_usd: float


def _as_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def compute_cost(usages: Iterable, provider: str = "anthropic") -> CostBreakdown:
    """Sum token counts across one or more `usage` objects and price them.

    Accepts both Anthropic's shape (`input_tokens`/`output_tokens`) and
    OpenAI/Groq's (`prompt_tokens`/`completion_tokens`). `provider` selects
    the pricing table — Anthropic and Groq have different rates, and Groq
    calls have no cache tokens.
    """
    per_mtok = _PRICING_BY_PROVIDER.get(provider, _PER_MTOK)

    input_t = output_t = cache_w = cache_r = 0
    calls = 0
    for u in usages:
        if u is None:
            continue
        calls += 1
        input_t += _as_int(getattr(u, "input_tokens", None) or getattr(u, "prompt_tokens", 0))
        output_t += _as_int(getattr(u, "output_tokens", None) or getattr(u, "completion_tokens", 0))
        cache_w += _as_int(getattr(u, "cache_creation_input_tokens", 0))
        cache_r += _as_int(getattr(u, "cache_read_input_tokens", 0))

    cost = (
        input_t * per_mtok["input"]
        + output_t * per_mtok["output"]
        + cache_w * per_mtok["cache_write"]
        + cache_r * per_mtok["cache_read"]
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


async def _persist(
    *,
    operation: str,
    provider: str,
    org_id,
    team_id,
    breakdown: CostBreakdown,
    model: str | None,
    context: dict,
) -> None:
    """Insert one ai_usage_events row on its own session/transaction — never
    the caller's. Allowed to raise; `record_generation_cost` is what
    guarantees the swallow, so this stays independently testable."""
    async with AsyncSessionLocal() as db:
        db.add(
            AIUsageEvent(
                organization_id=org_id,
                team_id=team_id,
                provider=provider,
                operation=operation,
                model=model,
                input_tokens=breakdown.input_tokens,
                output_tokens=breakdown.output_tokens,
                cache_write_tokens=breakdown.cache_write_tokens,
                cache_read_tokens=breakdown.cache_read_tokens,
                call_count=breakdown.call_count,
                cost_usd=breakdown.cost_usd,
                context=context or None,
            )
        )
        await db.commit()


async def record_generation_cost(
    operation: str,
    *usages,
    provider: str = "anthropic",
    org_id=None,
    team_id=None,
    **context,
) -> CostBreakdown | None:
    """
    Compute, log, and persist the cost of a single generation.

    `usages` are the `.usage` objects from each response that made up the
    generation (e.g. the complexity call + the assignment call). `context` is
    extra structured metadata to attach (session_id, milestone_id, ...).
    `org_id`/`team_id` identify the ai_usage_events row for the dashboard's
    per-org rollups.

    Returns the CostBreakdown, or None when tracking is disabled or the cost
    computation itself fails. A failed *persistence* step does NOT affect the
    return value — only a warning is logged, per this module's isolation
    contract (see module docstring).
    """
    if not is_enabled():
        return None
    try:
        breakdown = compute_cost(usages, provider=provider)
    except Exception:
        logger.warning("cost_tracker.record_generation_cost failed", exc_info=True)
        return None

    logger.info(
        "ai_cost operation=%s provider=%s cost_usd=%.6f input_tokens=%d output_tokens=%d "
        "cache_read_tokens=%d cache_write_tokens=%d calls=%d%s",
        operation,
        provider,
        breakdown.cost_usd,
        breakdown.input_tokens,
        breakdown.output_tokens,
        breakdown.cache_read_tokens,
        breakdown.cache_write_tokens,
        breakdown.call_count,
        "".join(f" {k}={v}" for k, v in context.items()),
    )

    if org_id is not None:
        try:
            await _persist(
                operation=operation,
                provider=provider,
                org_id=org_id,
                team_id=team_id,
                breakdown=breakdown,
                model=context.get("model"),
                context=context,
            )
        except Exception:
            logger.warning("cost_tracker: failed to persist ai_usage_event", exc_info=True)
    else:
        logger.warning("cost_tracker: no org_id given for operation=%s, skipping persistence", operation)

    return breakdown
