"""Tests for the AI cost tracking module.

record_generation_cost is now async and provider-aware, and persists to the
ai_usage_events table via its OWN session (src.database.AsyncSessionLocal),
never the caller's — see cost_tracker.py's module docstring. Because that
session is a module-level import, tests that exercise real persistence patch
`cost_tracker.AsyncSessionLocal` to point at a dedicated in-memory sqlite DB
(the `cost_db` fixture below) rather than reusing conftest's `tmp_db`, which
only overrides the FastAPI `get_db` dependency — a different session than
the one cost_tracker actually uses.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.database import Base
from src.models.ai_usage_event import AIUsageEvent
from src.models.organization import Organization
from src.models.team import Team
from src.services import cost_tracker
from src.services.cost_tracker import CostBreakdown, compute_cost, record_generation_cost


def _usage(input_tokens=0, output_tokens=0, cache_write=0, cache_read=0):
    return SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_input_tokens=cache_write,
        cache_read_input_tokens=cache_read,
    )


def _groq_usage(prompt_tokens=0, completion_tokens=0):
    return SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)


# ─── compute_cost ─────────────────────────────────────────────────────────────
def test_compute_cost_sums_and_prices_multiple_calls():
    # 1M input + 1M output across two calls, Anthropic pricing → $3 + $15 = $18.
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


def test_compute_cost_groq_uses_groq_pricing_not_anthropic():
    # Groq (Llama 3.3 70B Versatile): $0.59/MTok in + $0.79/MTok out = $1.38.
    # Anthropic pricing on the same tokens would be $3 + $15 = $18 — this is
    # the "wrong pricing table" bug (not a literal $0, see plan doc's
    # Implementation Notes) that the provider-aware rewrite fixes.
    breakdown = compute_cost(
        [_groq_usage(prompt_tokens=1_000_000, completion_tokens=1_000_000)], provider="groq"
    )
    assert breakdown.cost_usd == 1.38


def test_compute_cost_groq_usage_has_no_cache_tokens():
    breakdown = compute_cost([_groq_usage(prompt_tokens=1_000_000)], provider="groq")
    assert breakdown.cache_write_tokens == 0
    assert breakdown.cache_read_tokens == 0


def test_compute_cost_unknown_provider_falls_back_to_anthropic_pricing():
    breakdown = compute_cost([_usage(input_tokens=1_000_000)], provider="unknown")
    assert breakdown.cost_usd == 3.0


# ─── record_generation_cost: disabled flag / error-swallowing ─────────────────
async def test_record_is_noop_when_disabled():
    with patch.object(cost_tracker, "is_enabled", return_value=False):
        assert await record_generation_cost("sprint_plan", _usage(input_tokens=1_000_000)) is None


async def test_record_logs_when_enabled(caplog):
    with patch.object(cost_tracker, "is_enabled", return_value=True):
        with caplog.at_level("INFO"):
            breakdown = await record_generation_cost(
                "sprint_plan", _usage(input_tokens=1_000_000), session_id="sess-1",
            )
    assert breakdown is not None
    assert breakdown.cost_usd == 3.0
    assert "ai_cost operation=sprint_plan" in caplog.text
    assert "session_id=sess-1" in caplog.text


async def test_record_swallows_compute_errors():
    # A usage object that raises on attribute access must not propagate.
    class Boom:
        def __getattr__(self, name):
            raise RuntimeError("boom")

    with patch.object(cost_tracker, "is_enabled", return_value=True):
        assert await record_generation_cost("sprint_plan", Boom()) is None


async def test_record_without_org_id_still_returns_breakdown_but_skips_persistence(caplog):
    with patch.object(cost_tracker, "is_enabled", return_value=True):
        with caplog.at_level("WARNING"):
            breakdown = await record_generation_cost("sprint_plan", _usage(input_tokens=1_000_000))
    assert breakdown is not None
    assert breakdown.cost_usd == 3.0
    assert "skipping persistence" in caplog.text


# ─── DB persistence + the isolation guarantee ──────────────────────────────────
@pytest_asyncio.fixture
async def cost_db():
    """A dedicated in-memory sqlite DB, patched in as cost_tracker's own
    AsyncSessionLocal. Separate from conftest's `tmp_db` (which only
    overrides the FastAPI `get_db` dependency) because cost_tracker
    deliberately never uses the caller's session — see the module docstring's
    isolation contract."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    with patch.object(cost_tracker, "AsyncSessionLocal", Session):
        yield Session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


async def _seed_org(Session) -> tuple[uuid.UUID, uuid.UUID]:
    async with Session() as db:
        org = Organization(
            id=uuid.uuid4(), clerk_org_id="org_cost_test", name="Org", slug="org-cost-test", use_managed_key=True
        )
        db.add(org)
        await db.flush()
        team = Team(id=uuid.uuid4(), organization_id=org.id, name="Team")
        db.add(team)
        await db.commit()
        return org.id, team.id


async def test_anthropic_operation_lands_correctly_priced_row(cost_db):
    org_id, team_id = await _seed_org(cost_db)
    with patch.object(cost_tracker, "is_enabled", return_value=True):
        breakdown = await record_generation_cost(
            "roadmap_generate",
            _usage(input_tokens=1_000_000, output_tokens=1_000_000),
            provider="anthropic",
            org_id=org_id,
            team_id=team_id,
            model="claude-sonnet-4-6",
        )
    assert breakdown.cost_usd == 18.0

    async with cost_db() as db:
        row = (await db.execute(select(AIUsageEvent))).scalar_one()
    assert row.provider == "anthropic"
    assert row.operation == "roadmap_generate"
    assert float(row.cost_usd) == 18.0
    assert row.organization_id == org_id
    assert row.team_id == team_id
    assert row.model == "claude-sonnet-4-6"


async def test_groq_operation_lands_correctly_priced_row(cost_db):
    org_id, _team_id = await _seed_org(cost_db)
    with patch.object(cost_tracker, "is_enabled", return_value=True):
        breakdown = await record_generation_cost(
            "idea_interview",
            _groq_usage(prompt_tokens=1_000_000, completion_tokens=1_000_000),
            provider="groq",
            org_id=org_id,
            model="llama-3.3-70b-versatile",
        )
    assert breakdown.cost_usd == 1.38  # Groq pricing, not Anthropic's $18.

    async with cost_db() as db:
        row = (await db.execute(select(AIUsageEvent))).scalar_one()
    assert row.provider == "groq"
    assert float(row.cost_usd) == 1.38
    assert row.team_id is None  # idea_interview has no team yet at onboarding time


async def test_broken_persistence_does_not_raise_or_lose_the_breakdown(cost_db, caplog):
    """The isolation guarantee: a broken cost-tracking DB write must not roll
    back or fail the underlying generation. Simulated by making the internal
    _persist() raise — record_generation_cost must still return the computed
    breakdown and must not propagate the exception."""
    org_id, _team_id = await _seed_org(cost_db)

    async def _boom_persist(**kwargs):
        raise RuntimeError("DB is down")

    with patch.object(cost_tracker, "is_enabled", return_value=True), \
         patch.object(cost_tracker, "_persist", _boom_persist):
        with caplog.at_level("WARNING"):
            breakdown = await record_generation_cost(
                "roadmap_generate",
                _usage(input_tokens=1_000_000),
                provider="anthropic",
                org_id=org_id,
            )

    assert breakdown is not None
    assert breakdown.cost_usd == 3.0
    assert "failed to persist ai_usage_event" in caplog.text

    async with cost_db() as db:
        rows = (await db.execute(select(AIUsageEvent))).scalars().all()
    assert rows == []
