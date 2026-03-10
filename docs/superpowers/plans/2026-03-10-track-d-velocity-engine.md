# Track D — Statistical Velocity Engine Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a pure-Python statistical velocity engine that profiles developer speed, models sprint capacity, and produces confidence intervals — all decoupled from any database.

**Architecture:** Three focused service classes (`VelocityProfiler`, `CapacityModel`, `ConfidenceEngine`) operate on Pydantic schemas with zero SQLAlchemy coupling. A thin `__init__.py` exports all three. Tests use in-memory Pydantic objects — no DB, no mocks.

**Tech Stack:** Python 3.12, Pydantic v2, NumPy (already installed), `statistics` stdlib, `math` stdlib.

---

## Chunk 1: Schemas & Package Scaffold

### Task 1: Create the velocity service package

**Files:**
- Create: `apps/api/src/services/__init__.py`
- Create: `apps/api/src/services/velocity/__init__.py`
- Create: `apps/api/tests/services/__init__.py`
- Create: `apps/api/tests/services/velocity/__init__.py`

- [ ] **Step 1: Create directory structure**

```bash
cd apps/api
mkdir -p src/services/velocity
mkdir -p tests/services/velocity
```

- [ ] **Step 2: Create empty `__init__.py` files**

> **⚠️ Check first:** `src/services/__init__.py` may already exist. If it does, do NOT overwrite it — only create it if it is absent.

`src/services/__init__.py` — empty file (only if it doesn't already exist)
`src/services/velocity/__init__.py` — empty for now (populated in Task 6)
`tests/services/__init__.py` — empty file
`tests/services/velocity/__init__.py` — empty file

- [ ] **Step 3: Verify pytest still runs cleanly**

```bash
cd apps/api
.venv/Scripts/python -m pytest tests/ -v
```

Expected: all existing tests pass, no import errors.

- [ ] **Step 4: Commit**

```bash
git add apps/api/src/services/ apps/api/tests/services/
git commit -m "feat: scaffold velocity service package"
```

---

### Task 2: Define Pydantic schemas

**Files:**
- Create: `apps/api/src/services/velocity/schemas.py`

These are the shared data contracts for the three services. No DB dependency — pure Pydantic.

- [ ] **Step 1: Write `schemas.py`**

```python
from enum import Enum
from pydantic import BaseModel, field_validator


class TicketType(str, Enum):
    STORY = "story"
    BUG = "bug"
    TASK = "task"


class Domain(str, Enum):
    FRONTEND = "frontend"
    BACKEND = "backend"
    INFRA = "infra"


# --- Inputs ---

class TicketRecord(BaseModel):
    """One completed ticket. sprint_id groups tickets into sprints."""
    developer_id: str
    ticket_type: TicketType
    domain: Domain
    story_points: float
    sprint_id: str

    @field_validator("story_points")
    @classmethod
    def points_positive(cls, v: float) -> float:
        if v < 0:
            raise ValueError("story_points must be non-negative")
        return v


class SprintMeta(BaseModel):
    """Calendar facts about a sprint."""
    total_working_days: int
    team_members: list[str]

    @field_validator("total_working_days")
    @classmethod
    def days_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("total_working_days must be positive")
        return v


class PtoEntry(BaseModel):
    """Days off for one developer in the sprint."""
    developer_id: str
    days_off: float

    @field_validator("days_off")
    @classmethod
    def days_non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("days_off must be non-negative")
        return v


class MeetingOverhead(BaseModel):
    """Recurring meeting hours per day for one developer (manual input, MVP)."""
    developer_id: str
    hours_per_day: float

    @field_validator("hours_per_day")
    @classmethod
    def hours_non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("hours_per_day must be non-negative")
        return v


# --- Outputs ---

class VelocityProfile(BaseModel):
    """Historical average for one developer/type/domain combination."""
    developer_id: str
    ticket_type: TicketType
    domain: Domain
    avg_points_per_sprint: float
    sample_count: int  # number of sprints in the average; low = less reliable


class DeveloperCapacity(BaseModel):
    """Availability of one developer for a sprint."""
    developer_id: str
    available_days: float
    availability_ratio: float  # 0.0–1.0; multiply by baseline velocity to get budget


class AdjustedBudget(BaseModel):
    """Point budget for one developer after applying availability."""
    developer_id: str
    baseline_velocity: float
    availability_ratio: float
    adjusted_points: float


class ConfidenceInterval(BaseModel):
    """Probability range for team point delivery."""
    lower_bound: float
    upper_bound: float
    confidence_level: float  # e.g. 0.90 for 90%
    team_total_adjusted: float  # sum of adjusted_points in the current sprint
```

- [ ] **Step 2: Verify schemas import cleanly**

```bash
cd apps/api
.venv/Scripts/python -c "from src.services.velocity.schemas import TicketRecord, TicketType, Domain; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add apps/api/src/services/velocity/schemas.py
git commit -m "feat: add velocity engine Pydantic schemas"
```

---

## Chunk 2: VelocityProfiler

### Task 3: TDD — VelocityProfiler

**Files:**
- Create: `apps/api/tests/services/velocity/test_profiler.py`
- Create: `apps/api/src/services/velocity/profiler.py`

**What it does:** Groups completed tickets by `(developer_id, ticket_type, domain, sprint_id)`, sums points per sprint, then averages across sprints to produce one `VelocityProfile` per group.

- [ ] **Step 1: Write failing tests**

```python
# apps/api/tests/services/velocity/test_profiler.py
import pytest
from src.services.velocity.profiler import VelocityProfiler
from src.services.velocity.schemas import TicketRecord, TicketType, Domain


def ticket(dev, ttype, domain, points, sprint):
    return TicketRecord(
        developer_id=dev,
        ticket_type=ttype,
        domain=domain,
        story_points=points,
        sprint_id=sprint,
    )


def test_single_developer_averages_across_sprints():
    profiler = VelocityProfiler()
    tickets = [
        ticket("alice", TicketType.STORY, Domain.BACKEND, 5.0, "s1"),
        ticket("alice", TicketType.STORY, Domain.BACKEND, 3.0, "s2"),
    ]
    profiles = profiler.profile(tickets)
    assert len(profiles) == 1
    p = profiles[0]
    assert p.developer_id == "alice"
    assert p.avg_points_per_sprint == 4.0
    assert p.sample_count == 2


def test_multiple_tickets_same_sprint_sum_before_average():
    """Two tickets in the same sprint should be summed, not averaged."""
    profiler = VelocityProfiler()
    tickets = [
        ticket("alice", TicketType.STORY, Domain.BACKEND, 3.0, "s1"),
        ticket("alice", TicketType.STORY, Domain.BACKEND, 5.0, "s1"),  # same sprint
        ticket("alice", TicketType.STORY, Domain.BACKEND, 4.0, "s2"),
    ]
    profiles = profiler.profile(tickets)
    assert len(profiles) == 1
    # sprint s1 = 8pts, sprint s2 = 4pts → average = 6.0
    assert profiles[0].avg_points_per_sprint == 6.0
    assert profiles[0].sample_count == 2


def test_multi_domain_produces_separate_profiles():
    profiler = VelocityProfiler()
    tickets = [
        ticket("alice", TicketType.STORY, Domain.BACKEND, 5.0, "s1"),
        ticket("alice", TicketType.STORY, Domain.FRONTEND, 3.0, "s1"),
    ]
    profiles = profiler.profile(tickets)
    assert len(profiles) == 2
    domains = {p.domain for p in profiles}
    assert Domain.BACKEND in domains
    assert Domain.FRONTEND in domains


def test_multi_developer_independent_profiles():
    profiler = VelocityProfiler()
    tickets = [
        ticket("alice", TicketType.STORY, Domain.BACKEND, 5.0, "s1"),
        ticket("bob", TicketType.BUG, Domain.INFRA, 2.0, "s1"),
    ]
    profiles = profiler.profile(tickets)
    assert len(profiles) == 2
    devs = {p.developer_id for p in profiles}
    assert "alice" in devs and "bob" in devs


def test_empty_tickets_returns_empty():
    profiler = VelocityProfiler()
    assert profiler.profile([]) == []


def test_overall_velocity_new_developer_returns_zero():
    profiler = VelocityProfiler()
    assert profiler.overall_velocity("nobody", []) == 0.0


def test_overall_velocity_fallback_averages_all_types():
    profiler = VelocityProfiler()
    tickets = [
        ticket("alice", TicketType.STORY, Domain.BACKEND, 5.0, "s1"),
        ticket("alice", TicketType.BUG, Domain.FRONTEND, 3.0, "s1"),
        ticket("alice", TicketType.STORY, Domain.BACKEND, 4.0, "s2"),
    ]
    # sprint s1 = 8pts, sprint s2 = 4pts → overall avg = 6.0
    assert profiler.overall_velocity("alice", tickets) == 6.0


def test_single_sprint_profile_has_low_sample_count():
    """One sprint of history returns a profile — low sample_count signals thin data."""
    profiler = VelocityProfiler()
    tickets = [ticket("alice", TicketType.STORY, Domain.BACKEND, 8.0, "s1")]
    profiles = profiler.profile(tickets)
    assert len(profiles) == 1
    assert profiles[0].sample_count == 1
    assert profiles[0].avg_points_per_sprint == 8.0
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd apps/api
.venv/Scripts/python -m pytest tests/services/velocity/test_profiler.py -v
```

Expected: `ImportError` or `ModuleNotFoundError` — `profiler` does not exist yet.

- [ ] **Step 3: Implement `profiler.py`**

```python
# apps/api/src/services/velocity/profiler.py
from collections import defaultdict
from .schemas import TicketRecord, VelocityProfile


class VelocityProfiler:
    """Builds per-developer velocity profiles from historical ticket data."""

    def profile(self, tickets: list[TicketRecord]) -> list[VelocityProfile]:
        """
        Returns one VelocityProfile per (developer, ticket_type, domain) combination.
        Points within the same sprint are summed before averaging across sprints.
        """
        # Step 1: sum points per (dev, type, domain, sprint)
        sprint_points: dict[tuple, float] = defaultdict(float)
        for t in tickets:
            key = (t.developer_id, t.ticket_type, t.domain, t.sprint_id)
            sprint_points[key] += t.story_points

        # Step 2: collect per-sprint totals grouped by (dev, type, domain)
        group_sprints: dict[tuple, list[float]] = defaultdict(list)
        for (dev, ttype, domain, _sprint), pts in sprint_points.items():
            group_sprints[(dev, ttype, domain)].append(pts)

        # Step 3: average across sprints
        return [
            VelocityProfile(
                developer_id=dev,
                ticket_type=ttype,
                domain=domain,
                avg_points_per_sprint=sum(sprint_totals) / len(sprint_totals),
                sample_count=len(sprint_totals),
            )
            for (dev, ttype, domain), sprint_totals in group_sprints.items()
        ]

    def overall_velocity(self, developer_id: str, tickets: list[TicketRecord]) -> float:
        """
        Fallback: developer's average points/sprint across all ticket types and domains.
        Returns 0.0 if the developer has no history.
        """
        dev_tickets = [t for t in tickets if t.developer_id == developer_id]
        if not dev_tickets:
            return 0.0

        sprint_totals: dict[str, float] = defaultdict(float)
        for t in dev_tickets:
            sprint_totals[t.sprint_id] += t.story_points

        totals = list(sprint_totals.values())
        return sum(totals) / len(totals)
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd apps/api
.venv/Scripts/python -m pytest tests/services/velocity/test_profiler.py -v
```

Expected: all 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/services/velocity/profiler.py apps/api/tests/services/velocity/test_profiler.py
git commit -m "feat: implement VelocityProfiler with TDD"
```

---

## Chunk 3: CapacityModel

### Task 4: TDD — CapacityModel

**Files:**
- Create: `apps/api/tests/services/velocity/test_capacity.py`
- Create: `apps/api/src/services/velocity/capacity.py`

**What it does:** For each developer in `SprintMeta.team_members`, deducts PTO days and converts meeting hours into equivalent days lost. Returns `DeveloperCapacity` with `available_days` and `availability_ratio` (0.0–1.0).

**Key formula:**
```
meeting_days = (hours_per_day × total_working_days) / 8
available_days = max(0, total_working_days − days_off − meeting_days)
availability_ratio = available_days / total_working_days
```

- [ ] **Step 1: Write failing tests**

```python
# apps/api/tests/services/velocity/test_capacity.py
import pytest
from src.services.velocity.capacity import CapacityModel
from src.services.velocity.schemas import SprintMeta, PtoEntry, MeetingOverhead


def sprint(days, members):
    return SprintMeta(total_working_days=days, team_members=members)


def test_full_availability_no_deductions():
    model = CapacityModel()
    result = model.model(sprint(10, ["alice"]), [], [])
    assert len(result) == 1
    assert result[0].developer_id == "alice"
    assert result[0].availability_ratio == 1.0
    assert result[0].available_days == 10.0


def test_full_pto_gives_zero_availability():
    model = CapacityModel()
    pto = [PtoEntry(developer_id="alice", days_off=10.0)]
    result = model.model(sprint(10, ["alice"]), pto, [])
    assert result[0].availability_ratio == 0.0
    assert result[0].available_days == 0.0


def test_pto_exceeding_sprint_clamped_to_zero():
    """Days off > sprint length should not produce negative availability."""
    model = CapacityModel()
    pto = [PtoEntry(developer_id="alice", days_off=15.0)]
    result = model.model(sprint(10, ["alice"]), pto, [])
    assert result[0].available_days == 0.0
    assert result[0].availability_ratio == 0.0


def test_partial_pto():
    model = CapacityModel()
    pto = [PtoEntry(developer_id="alice", days_off=2.0)]
    result = model.model(sprint(10, ["alice"]), pto, [])
    assert result[0].available_days == 8.0
    assert result[0].availability_ratio == pytest.approx(0.8)


def test_meeting_overhead_deducts_equivalent_days():
    """2 hours/day meetings over 10-day sprint = 2.5 days lost (2*10/8)."""
    model = CapacityModel()
    meetings = [MeetingOverhead(developer_id="alice", hours_per_day=2.0)]
    result = model.model(sprint(10, ["alice"]), [], meetings)
    assert result[0].available_days == 7.5
    assert result[0].availability_ratio == pytest.approx(0.75)


def test_pto_and_meetings_combined():
    """2 days PTO + 2 hrs/day meetings (2.5 days) = 5.5 days available."""
    model = CapacityModel()
    pto = [PtoEntry(developer_id="alice", days_off=2.0)]
    meetings = [MeetingOverhead(developer_id="alice", hours_per_day=2.0)]
    result = model.model(sprint(10, ["alice"]), pto, meetings)
    assert result[0].available_days == 5.5
    assert result[0].availability_ratio == pytest.approx(0.55)


def test_developer_without_pto_entry_gets_full_days():
    """If a team member has no PTO entry, they lose no days."""
    model = CapacityModel()
    pto = [PtoEntry(developer_id="bob", days_off=3.0)]
    result = model.model(sprint(10, ["alice", "bob"]), pto, [])
    alice = next(r for r in result if r.developer_id == "alice")
    assert alice.available_days == 10.0


def test_multiple_team_members_independent():
    model = CapacityModel()
    pto = [PtoEntry(developer_id="alice", days_off=5.0)]
    result = model.model(sprint(10, ["alice", "bob"]), pto, [])
    alice = next(r for r in result if r.developer_id == "alice")
    bob = next(r for r in result if r.developer_id == "bob")
    assert alice.availability_ratio == pytest.approx(0.5)
    assert bob.availability_ratio == pytest.approx(1.0)
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd apps/api
.venv/Scripts/python -m pytest tests/services/velocity/test_capacity.py -v
```

Expected: `ImportError` — `capacity` does not exist yet.

- [ ] **Step 3: Implement `capacity.py`**

```python
# apps/api/src/services/velocity/capacity.py
from .schemas import SprintMeta, PtoEntry, MeetingOverhead, DeveloperCapacity

_HOURS_PER_DAY = 8.0


class CapacityModel:
    """Converts sprint calendar facts into per-developer availability ratios."""

    def model(
        self,
        sprint: SprintMeta,
        pto: list[PtoEntry],
        meetings: list[MeetingOverhead],
    ) -> list[DeveloperCapacity]:
        """
        Returns DeveloperCapacity for each member in sprint.team_members.
        availability_ratio is the fraction of the sprint the developer is present
        after deducting PTO and meeting time.
        """
        pto_map = {p.developer_id: p.days_off for p in pto}
        meeting_map = {m.developer_id: m.hours_per_day for m in meetings}
        total = sprint.total_working_days

        results = []
        for dev_id in sprint.team_members:
            days_off = pto_map.get(dev_id, 0.0)
            # Convert recurring meeting hours into equivalent full days lost
            meeting_days = (meeting_map.get(dev_id, 0.0) * total) / _HOURS_PER_DAY
            available = max(0.0, total - days_off - meeting_days)
            ratio = round(available / total, 4)
            results.append(
                DeveloperCapacity(
                    developer_id=dev_id,
                    available_days=round(available, 2),
                    availability_ratio=ratio,
                )
            )
        return results
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd apps/api
.venv/Scripts/python -m pytest tests/services/velocity/test_capacity.py -v
```

Expected: all 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/services/velocity/capacity.py apps/api/tests/services/velocity/test_capacity.py
git commit -m "feat: implement CapacityModel with TDD"
```

---

## Chunk 4: ConfidenceEngine

### Task 5: TDD — ConfidenceEngine

**Files:**
- Create: `apps/api/tests/services/velocity/test_confidence.py`
- Create: `apps/api/src/services/velocity/confidence.py`

**What it does:** Takes a list of historical sprint budgets (one list of `AdjustedBudget` per past sprint). Sums each sprint's team total. Computes a confidence interval around the mean using the normal approximation with pre-computed z-scores (NumPy is available; SciPy is not in dependencies).

**Supported confidence levels:** 0.80, 0.90, 0.95, 0.99
**Degenerate case (< 2 sprints):** interval collapses to a single point.
**Note:** Uses z-scores (normal approximation). For n < 30, a t-distribution would be more accurate — flagged for future improvement.

- [ ] **Step 1: Write failing tests**

```python
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


def test_empty_historical_returns_zero_point_interval():
    """No sprint history at all → degenerate interval at 0.0, no crash."""
    engine = ConfidenceEngine()
    result = engine.calculate([], confidence_level=0.90)
    assert result.lower_bound == result.upper_bound == 0.0
    assert result.team_total_adjusted == 0.0


def test_unsupported_confidence_level_raises():
    engine = ConfidenceEngine()
    historical = [
        sprint_of(budget("alice", 10)),
        sprint_of(budget("alice", 10)),
    ]
    with pytest.raises(ValueError, match="confidence_level"):
        engine.calculate(historical, confidence_level=0.50)
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd apps/api
.venv/Scripts/python -m pytest tests/services/velocity/test_confidence.py -v
```

Expected: `ImportError` — `confidence` does not exist yet.

- [ ] **Step 3: Implement `confidence.py`**

```python
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
            lower_bound=round(max(0.0, mean - margin), 2),
            upper_bound=round(mean + margin, 2),
            confidence_level=confidence_level,
            team_total_adjusted=current_total,
        )
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd apps/api
.venv/Scripts/python -m pytest tests/services/velocity/test_confidence.py -v
```

Expected: all 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/services/velocity/confidence.py apps/api/tests/services/velocity/test_confidence.py
git commit -m "feat: implement ConfidenceEngine with TDD"
```

---

## Chunk 5: Wire Up & Full Suite

### Task 6: Populate `__init__.py` and run full suite

**Files:**
- Modify: `apps/api/src/services/velocity/__init__.py`

- [ ] **Step 1: Export all three classes**

```python
# apps/api/src/services/velocity/__init__.py
from .profiler import VelocityProfiler
from .capacity import CapacityModel
from .confidence import ConfidenceEngine

__all__ = ["VelocityProfiler", "CapacityModel", "ConfidenceEngine"]
```

- [ ] **Step 2: Verify top-level import works**

```bash
cd apps/api
.venv/Scripts/python -c "from src.services.velocity import VelocityProfiler, CapacityModel, ConfidenceEngine; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Run the full test suite**

```bash
cd apps/api
.venv/Scripts/python -m pytest tests/ -v
```

Expected: all tests pass (velocity suite + existing auth tests).

- [ ] **Step 4: Final commit**

```bash
git add apps/api/src/services/velocity/__init__.py
git commit -m "feat: wire up velocity service exports"
```

---

## Summary

| File | Responsibility |
|---|---|
| `schemas.py` | Pydantic contracts — shared inputs/outputs, zero DB coupling |
| `profiler.py` | `VelocityProfiler` — points/sprint by dev/type/domain |
| `capacity.py` | `CapacityModel` — availability ratio from PTO + meetings |
| `confidence.py` | `ConfidenceEngine` — probability interval from historical variance |
| `__init__.py` | Package exports |

**Tests:** 24 tests total across 3 test files. All pure in-memory — no DB, no mocks.

**Blockers (tracked in `tasks/todo.md`):**
- DB models (`Sprint`, `Ticket`, `Developer`, `PtoEntry`) must be created by a separate track before this service can be wired to real data
- Meeting data is manual input (MVP); calendar integration is a future track
