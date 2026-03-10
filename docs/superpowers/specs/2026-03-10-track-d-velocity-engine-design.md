# Track D — Statistical Velocity Engine
**Date:** 2026-03-10
**Branch:** `track-d-velocity-engine`
**Scope:** `apps/api/src/services/velocity/`

---

## Overview

A statistical engine that answers three questions at sprint planning time:
1. How fast is each developer, at what kind of work?
2. How much can they actually do this sprint given availability?
3. How confident should we be in that estimate?

---

## Architecture

Three focused service classes, each with one job:

### `VelocityProfiler` (`profiler.py`)
Builds per-developer velocity profiles from historical ticket data.
Output: average points per sprint, broken down by ticket type (story/bug/task) and domain (frontend/backend/infra).
Transparent about thin data — returns `sample_count` so callers know when estimates are weak.

### `CapacityModel` (`capacity.py`)
Converts raw sprint length into real developer availability.
Takes PTO days and manual meeting overhead hours, computes `availability_ratio` (0.0–1.0).
Multiplies baseline velocity by ratio to produce `adjusted_points` per developer.

### `ConfidenceEngine` (`confidence.py`)
Wraps historical adjusted budgets in a probability distribution.
Outputs a confidence interval (e.g. 90% chance team delivers 28–36 points) based on variance across past sprints.

---

## Data Flow

```
TicketRecord[]  →  VelocityProfiler  →  VelocityProfile (baseline_velocity)
                                                ↓
SprintMeta + PtoEntry[] + MeetingOverhead[]
        →  CapacityModel  →  DeveloperCapacity (availability_ratio)
                                                ↓
                              AdjustedBudget (baseline × ratio)
                                                ↓
historical AdjustedBudget[]  →  ConfidenceEngine  →  ConfidenceInterval
```

---

## Key Design Decisions

**Points ≠ Days**
Story points measure complexity, not time. The capacity model works in days/hours; the profiler works in points/sprint. They connect only through `availability_ratio`.

**No DB coupling**
All inputs/outputs are Pydantic schemas. The service has zero SQLAlchemy dependency. When DB models land (separate track), a thin adapter maps them to these schemas.

**Meeting data: manual input for MVP**
Team lead submits `MeetingOverhead` (hours/day per developer) via API input.
Full version: replace with calendar integration (Google Calendar / Outlook) — planned as a future track.

**Graceful degradation**
- < 3 sprints of history → return profile with low `sample_count`, no exception
- Zero availability → `adjusted_points = 0`
- Missing type/domain → fall back to developer overall average

---

## Schemas (`schemas.py`)

**Inputs:**
- `TicketRecord` — `developer_id`, `ticket_type`, `domain`, `story_points`, `sprint_id`
- `SprintMeta` — `total_working_days`, `team_members: list[str]`
- `PtoEntry` — `developer_id`, `days_off`
- `MeetingOverhead` — `developer_id`, `hours_per_day`

**Outputs:**
- `VelocityProfile` — `developer_id`, `ticket_type`, `domain`, `avg_points_per_sprint`, `sample_count`
- `DeveloperCapacity` — `developer_id`, `available_days`, `availability_ratio`
- `AdjustedBudget` — `developer_id`, `baseline_velocity`, `availability_ratio`, `adjusted_points`
- `ConfidenceInterval` — `lower_bound`, `upper_bound`, `confidence_level`, `team_total_adjusted`

---

## File Layout

```
apps/api/src/services/velocity/
├── __init__.py
├── schemas.py
├── profiler.py
├── capacity.py
└── confidence.py

apps/api/tests/services/velocity/
├── __init__.py
├── test_profiler.py
├── test_capacity.py
└── test_confidence.py
```

---

## Testing Strategy

Pure Pydantic inputs — no DB or mocks required. Key cases per class:

| Class | Key Test Cases |
|---|---|
| `VelocityProfiler` | new developer (no history), single ticket type, multi-domain breakdown |
| `CapacityModel` | full PTO (zero availability), no overhead (ratio = 1.0), partial availability |
| `ConfidenceEngine` | consistent sprints (narrow interval), high variance (wide interval), single sprint (degenerate case) |

---

## Dependencies & Blockers

- **DB Models not yet created** — `apps/api/src/models/` does not exist. A separate track must create `Sprint`, `Ticket`, `Developer`, `PtoEntry` SQLAlchemy models before Track D integrates with the DB.
- **Calendar integration** — meeting overhead is manual input for MVP; full version requires a calendar sync track.
