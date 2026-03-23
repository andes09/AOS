# Track D — Statistical Velocity Stats Endpoint
**Date:** 2026-03-23
**Branch:** `feat/velocity-engine`
**Scope:** `apps/api/src/routers/velocity.py`, `apps/api/src/services/velocity/stats.py`, `apps/web/src/components/mirror/VelocityStatsChart.tsx`, `apps/web/src/pages/VelocityMirrorPage.tsx`

---

## Overview

Adds a statistical velocity analysis endpoint that replaces the naive "average last N sprints" with a richer set of metrics: rolling average, exponentially weighted average, standard deviation, linear trend, 90% confidence interval, outlier detection, and a next-sprint forecast. A new frontend chart displays these stats on the Velocity Mirror page.

---

## Architecture

### Backend — Stats calculation service (`stats.py`)

A pure-function module `apps/api/src/services/velocity/stats.py` that accepts a list of sprint velocity values (floats) and a window size, and returns a `VelocityStats` dataclass. No database coupling — testable with plain lists.

**Inputs:** `velocities: list[float]` (ordered oldest→newest), `window: int` (3–12), `lambda_: float` (EWM decay, default 0.3)

**Outputs:**
- `rolling_avg` — mean of last `window` values
- `weighted_avg` — exponentially weighted mean (recent sprints weighted more); computed manually with `numpy`
- `std_dev` — sample std dev of the window
- `trend` — slope of `numpy.polyfit` over the window (points/sprint)
- `confidence_interval` — `(lower, upper)` 90% CI = `rolling_avg ± 1.645 * std_dev / sqrt(n)`
- `outlier_sprint_indices` — indices where `|v - mean| > 1.5 * std_dev` (flagged, not excluded)
- `forecast` — `rolling_avg + trend`, with CI applied as `(forecast - margin, forecast + margin)`

Uses `numpy` (already in `pyproject.toml`). Falls back gracefully when `len(velocities) < 2` (returns None for fields that require variance).

### Backend — New endpoint

Added to `dashboard_router` in `apps/api/src/routers/velocity.py`:

```
GET /api/velocity/stats?team_id=<uuid>&window=6
```

- `team_id` — optional UUID query param (same pattern as `/burndown`, `/capacity`, `/health-score`); resolves via `resolve_team_query`
- `window` — int, 3–12, default 6

Queries `sprints` table for completed sprints ordered by `end_date` for the resolved team, extracts `delivered_points`, passes to the stats service, and returns a `VelocityStatsResponse` Pydantic model.

**Response shape:**
```json
{
  "teamId": "...",
  "window": 6,
  "sprintCount": 8,
  "rollingAvg": 42.1,
  "weightedAvg": 44.3,
  "stdDev": 5.2,
  "trend": 1.8,
  "confidenceInterval": { "lower": 37.6, "upper": 46.6 },
  "outlierSprints": ["sprint-id-1"],
  "forecast": { "point": 43.9, "lower": 39.4, "upper": 48.4 }
}
```

Uses `ConfigDict(alias_generator=to_camel)` consistent with other response models in this router.

No Alembic migration required — computed entirely from existing `sprints.delivered_points`.

### Frontend — `VelocityStatsChart` component

New file: `apps/web/src/components/mirror/VelocityStatsChart.tsx`

- Fetches `GET /api/velocity/stats` via TanStack Query (`queryKey: ['velocity-stats']`)
- Recharts `ComposedChart` with:
  - Two `Line`s: rolling avg (solid indigo `#6366f1`) and weighted avg (dashed violet `#a78bfa`)
  - One `Area` for forecast band (lower/upper CI, low-opacity fill)
- Trend arrow badge above the chart: `↑` if `trend > 0.5`, `↓` if `trend < -0.5`, `→` otherwise
- Outlier sprints shown as `ReferenceDot` markers on the rolling avg line
- Inline styles matching the existing dark theme (`#1e2030` card, `#0f1117` background)

### Frontend — `VelocityMirrorPage` update

Insert `<VelocityStatsChart />` between `<BurndownChart />` and `<DeveloperCapacityRow />` in the left column.

---

## Error handling

- `< 3` completed sprints → 422 with `"Insufficient sprint data (need at least 3 completed sprints)"`
- No completed sprints at all → same 422
- `window` out of range → FastAPI validation error (Query with `ge=3, le=12`)

---

## Tests

`apps/api/tests/services/velocity/test_stats.py` — unit tests for the pure stats function:
- Correct rolling avg for a known sequence
- Weighted avg weights recent sprints more heavily than older ones
- Trend is positive for an increasing sequence
- Outlier detection flags values >1.5 std devs from mean
- Graceful handling of fewer than 2 data points (no crash)

---

## Decision log

- **Query param not path param** for `team_id`: consistent with all other dashboard routes; frontend has no team_id in context and auto-resolves to first org team.
- **numpy over `statistics` stdlib**: already a dependency; `polyfit` and EWMA are cleaner with numpy.
- **Flagged outliers, not excluded**: exclusion would silently distort history; flagging lets the UI surface them to the user.
