# Velocity Stats Endpoint Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `GET /api/velocity/stats` returning rolling avg, weighted avg, std dev, trend, 90% CI, outlier sprints, and next-sprint forecast; display as a two-line Recharts chart in VelocityMirrorPage.

**Architecture:** Pure stats function in `services/velocity/stats.py` (numpy, no DB); thin endpoint in the existing `dashboard_router` using `resolve_team_query` (optional team_id query param, consistent with `/burndown` etc.); new `VelocityStatsChart` frontend component inserted into VelocityMirrorPage between BurndownChart and DeveloperCapacityRow.

**Tech Stack:** Python 3.12, numpy (already installed), FastAPI Query param validation, Pydantic v2 camelCase aliases, React + TanStack Query, Recharts ComposedChart.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `apps/api/src/services/velocity/stats.py` | Pure stats function, `VelocityStats` dataclass |
| Create | `apps/api/tests/services/velocity/test_stats.py` | Unit tests for stats logic |
| Modify | `apps/api/src/routers/velocity.py` | Add response models + `/stats` endpoint |
| Create | `apps/web/src/components/mirror/VelocityStatsChart.tsx` | Recharts chart + trend arrow |
| Modify | `apps/web/src/pages/VelocityMirrorPage.tsx` | Insert `<VelocityStatsChart />` |

---

## Chunk 1: Stats Service

### Task 1: Create `stats.py` with pure calculation function

**Files:**
- Create: `apps/api/src/services/velocity/stats.py`

- [ ] **Step 1: Write the failing tests first** (see Task 2 below — write tests before implementation)

- [ ] **Step 2: Create `apps/api/src/services/velocity/stats.py`**

```python
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
```

- [ ] **Step 3: Commit**

```bash
git add apps/api/src/services/velocity/stats.py
git commit -m "feat: add compute_velocity_stats pure function"
```

---

### Task 2: Write and pass unit tests for `stats.py`

**Files:**
- Create: `apps/api/tests/services/velocity/test_stats.py`

- [ ] **Step 1: Create the test file**

```python
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
```

- [ ] **Step 2: Run tests — expect them to pass (implementation already committed)**

```bash
cd apps/api && python -m pytest tests/services/velocity/test_stats.py -v
```

Expected: All 12 tests PASS.

- [ ] **Step 3: Run full test suite to confirm no regressions**

```bash
cd apps/api && python -m pytest -v
```

Expected: All tests PASS.

- [ ] **Step 4: Commit**

```bash
git add apps/api/tests/services/velocity/test_stats.py
git commit -m "test: unit tests for compute_velocity_stats"
```

---

## Chunk 2: Backend Endpoint

### Task 3: Add `/stats` endpoint to `dashboard_router`

**Files:**
- Modify: `apps/api/src/routers/velocity.py`

The existing file already imports `ConfigDict`, `to_camel`, `select`, `AsyncSession`, `Depends`, `HTTPException`, `status`, `Sprint`, `SprintStatus`, `resolve_team_query`, `get_db`. You only need to add `Query` to the FastAPI import and add the new code blocks below.

- [ ] **Step 1: Add `Query` to the FastAPI import at the top of `velocity.py`**

Find this line:
```python
from fastapi import APIRouter, Depends, HTTPException, status
```

Replace with:
```python
from fastapi import APIRouter, Depends, HTTPException, Query, status
```

- [ ] **Step 2: Add the import for `compute_velocity_stats` after the existing service imports**

Find the block ending with:
```python
from src.services.velocity.schemas import SprintMeta
```

Add immediately after:
```python
from src.services.velocity.stats import VelocityStats, compute_velocity_stats
```

- [ ] **Step 3: Add response models before the `# Dashboard endpoints` section**

Insert these three models after the existing `HealthScoreResponse` model:

```python
class ConfidenceIntervalRange(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    lower: float
    upper: float


class ForecastRange(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    point: float
    lower: float
    upper: float


class SprintPoint(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    name: str
    velocity: float


class VelocityStatsResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    team_id: str
    window: int
    sprint_count: int
    rolling_avg: float
    weighted_avg: float
    std_dev: float
    trend: float
    confidence_interval: ConfidenceIntervalRange
    outlier_sprints: list[str]
    forecast: ForecastRange
    sprint_window: list[SprintPoint]  # per-sprint data for the chart x-axis
```

- [ ] **Step 4: Add the `/stats` endpoint at the end of the dashboard endpoints section**

Append after the `get_health_score` function:

```python
@dashboard_router.get("/stats", response_model=VelocityStatsResponse)
async def get_velocity_stats(
    window: int = Query(default=6, ge=3, le=12),
    team: Team = Depends(resolve_team_query),
    db: AsyncSession = Depends(get_db),
):
    """Statistical velocity analysis for the team over the last N completed sprints."""
    sprints = (
        await db.scalars(
            select(Sprint)
            .where(
                Sprint.team_id == team.id,
                Sprint.status == SprintStatus.COMPLETED,
                Sprint.delivered_points.isnot(None),
            )
            .order_by(Sprint.end_date.asc())
        )
    ).all()

    if len(sprints) < 3:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Insufficient sprint data (need at least 3 completed sprints with delivered points)",
        )

    velocities = [float(s.delivered_points) for s in sprints]
    stats = compute_velocity_stats(velocities, window=window)

    # Map outlier indices (relative to window slice) → sprint IDs
    window_sprints = list(sprints[-window:])
    outlier_sprint_ids = [
        str(window_sprints[i].id)
        for i in stats.outlier_sprint_indices
        if i < len(window_sprints)
    ]

    sprint_window_points = [
        SprintPoint(name=s.name, velocity=float(s.delivered_points))
        for s in window_sprints
    ]

    return VelocityStatsResponse(
        team_id=str(team.id),
        window=window,
        sprint_count=len(sprints),
        rolling_avg=stats.rolling_avg,
        weighted_avg=stats.weighted_avg,
        std_dev=stats.std_dev,
        trend=stats.trend,
        confidence_interval=ConfidenceIntervalRange(
            lower=stats.ci_lower,
            upper=stats.ci_upper,
        ),
        outlier_sprints=outlier_sprint_ids,
        forecast=ForecastRange(
            point=stats.forecast_point,
            lower=stats.forecast_lower,
            upper=stats.forecast_upper,
        ),
        sprint_window=sprint_window_points,
    )
```

- [ ] **Step 5: Run full test suite**

```bash
cd apps/api && python -m pytest -v
```

Expected: All tests PASS. No import errors.

- [ ] **Step 6: Commit**

```bash
git add apps/api/src/routers/velocity.py
git commit -m "feat: add GET /api/velocity/stats endpoint"
```

---

## Chunk 3: Frontend

### Task 4: Create `VelocityStatsChart` component

**Files:**
- Create: `apps/web/src/components/mirror/VelocityStatsChart.tsx`

- [ ] **Step 1: Create `apps/web/src/components/mirror/VelocityStatsChart.tsx`**

```tsx
// apps/web/src/components/mirror/VelocityStatsChart.tsx

import { useQuery } from '@tanstack/react-query'
import { useAuth } from '@clerk/clerk-react'
import {
  ComposedChart,
  Line,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts'
import { useApi, ApiError } from '../../lib/api'

interface SprintPoint {
  name: string
  velocity: number
}

interface VelocityStatsData {
  teamId: string
  window: number
  sprintCount: number
  rollingAvg: number
  weightedAvg: number
  stdDev: number
  trend: number
  confidenceInterval: { lower: number; upper: number }
  outlierSprints: string[]
  forecast: { point: number; lower: number; upper: number }
  sprintWindow: SprintPoint[]
}

function TrendArrow({ trend }: { trend: number }) {
  const arrow = trend > 0.5 ? '↑' : trend < -0.5 ? '↓' : '→'
  const color = trend > 0.5 ? '#22c55e' : trend < -0.5 ? '#ef4444' : '#94a3b8'
  return (
    <span style={{ color, fontSize: 18, fontWeight: 700, marginLeft: 8 }}>
      {arrow}
    </span>
  )
}

export function VelocityStatsChart() {
  const { get } = useApi()
  const { isLoaded, isSignedIn } = useAuth()

  const { data, isLoading, isError, error } = useQuery<VelocityStatsData, ApiError>({
    queryKey: ['velocity-stats'],
    queryFn: () => get<VelocityStatsData>('/api/velocity/stats'),
    enabled: isLoaded && isSignedIn,
  })

  if (isLoading) {
    return (
      <div style={{ background: '#1e2030', borderRadius: 8, padding: '1.5rem', height: 280, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <span style={{ color: '#64748b', fontSize: 13 }}>Loading velocity stats…</span>
      </div>
    )
  }

  if (isError) {
    const is422 = error instanceof ApiError && error.status === 422
    return (
      <div style={{ background: '#1e2030', borderRadius: 8, padding: '1.5rem', height: 280, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <span style={{ color: is422 ? '#475569' : '#ef4444', fontSize: 13 }}>
          {is422 ? 'Not enough completed sprints for velocity stats' : 'Failed to load velocity stats'}
        </span>
      </div>
    )
  }

  if (!data) return null

  // Compute per-sprint trailing rolling/weighted averages so the lines show
  // actual history rather than a flat scalar repeated across all points.
  // The final sprint's values converge to the API's summary scalars.
  const LAMBDA = 0.3
  function trailingAvgs(vels: number[]): { rolling: number; weighted: number } {
    const n = vels.length
    const rolling = vels.reduce((a, b) => a + b, 0) / n
    const weights = vels.map((_, j) => Math.pow(1 - LAMBDA, n - 1 - j))
    const weightSum = weights.reduce((a, b) => a + b, 0)
    const weighted = vels.reduce((acc, v, j) => acc + v * weights[j] / weightSum, 0)
    return {
      rolling: Math.round(rolling * 100) / 100,
      weighted: Math.round(weighted * 100) / 100,
    }
  }

  // Build chart data: per-sprint history + one forecast point.
  // The last real sprint also gets forecastLow/High so the Area band has two
  // adjacent data points and renders as a visible shaded region.
  const lastIndex = data.sprintWindow.length - 1
  const chartData = [
    ...data.sprintWindow.map((s, i) => {
      const slice = data.sprintWindow.slice(0, i + 1).map(p => p.velocity)
      const { rolling, weighted } = trailingAvgs(slice)
      return {
        name: s.name,
        velocity: s.velocity,
        rollingAvg: rolling,
        weightedAvg: weighted,
        // Anchor the forecast band at the last real sprint so the Area renders
        forecastLow: i === lastIndex ? data.forecast.lower : undefined as number | undefined,
        forecastHigh: i === lastIndex ? data.forecast.upper : undefined as number | undefined,
      }
    }),
    {
      name: 'Forecast',
      velocity: undefined as number | undefined,
      rollingAvg: undefined as number | undefined,
      weightedAvg: undefined as number | undefined,
      forecastLow: data.forecast.lower,
      forecastHigh: data.forecast.upper,
    },
  ]

  // Find which chart indices are outliers (by sprint name matching outlier sprint IDs is tricky;
  // instead we flag by velocity deviation from rolling avg > 1.5 * stdDev)
  const outlierNames = new Set(
    data.sprintWindow
      .filter(s => data.stdDev > 0 && Math.abs(s.velocity - data.rollingAvg) > 1.5 * data.stdDev)
      .map(s => s.name)
  )

  return (
    <div style={{ background: '#1e2030', borderRadius: 8, padding: '1rem 1rem 0.5rem' }}>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 12 }}>
        <span style={{ color: '#94a3b8', fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          Velocity Trend
        </span>
        <TrendArrow trend={data.trend} />
        <span style={{ marginLeft: 'auto', color: '#475569', fontSize: 11 }}>
          {data.sprintCount} sprints · window {data.window}
        </span>
      </div>

      <ResponsiveContainer width="100%" height={240}>
        <ComposedChart data={chartData} margin={{ top: 4, right: 12, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id="forecastGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#a78bfa" stopOpacity={0.25} />
              <stop offset="95%" stopColor="#a78bfa" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#2d2f45" />
          <XAxis
            dataKey="name"
            tick={{ fill: '#64748b', fontSize: 10 }}
            tickLine={false}
            axisLine={false}
          />
          <YAxis
            tick={{ fill: '#64748b', fontSize: 11 }}
            tickLine={false}
            axisLine={false}
            label={{ value: 'Points', angle: -90, position: 'insideLeft', fill: '#64748b', fontSize: 11 }}
          />
          <Tooltip
            contentStyle={{ background: '#0f1117', border: '1px solid #2d2f45', borderRadius: 6, fontSize: 12 }}
            labelStyle={{ color: '#94a3b8' }}
            itemStyle={{ color: '#e2e8f0' }}
            formatter={(value: unknown) => value == null ? '—' : `${value} pts`}
          />
          <Legend wrapperStyle={{ fontSize: 11, color: '#94a3b8', paddingTop: 8 }} />

          {/* Actual velocity per sprint */}
          <Line
            type="monotone"
            dataKey="velocity"
            name="Actual"
            stroke="#64748b"
            strokeWidth={1.5}
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            dot={(props: any) =>
              outlierNames.has(props.payload?.name)
                ? <circle key={props.payload.name} cx={props.cx} cy={props.cy} r={5} fill="#f59e0b" stroke="#f59e0b" />
                : <circle key={props.payload?.name} cx={props.cx} cy={props.cy} r={3} fill="#64748b" />
            }
            connectNulls={false}
          />

          {/* Rolling avg — solid indigo reference line */}
          <Line
            type="monotone"
            dataKey="rollingAvg"
            name="Rolling Avg"
            stroke="#6366f1"
            strokeWidth={2}
            dot={false}
            connectNulls={false}
          />

          {/* Weighted avg — dashed violet reference line */}
          <Line
            type="monotone"
            dataKey="weightedAvg"
            name="Weighted Avg"
            stroke="#a78bfa"
            strokeWidth={2}
            strokeDasharray="4 2"
            dot={false}
            connectNulls={false}
          />

          {/* Forecast band */}
          <Area
            type="monotone"
            dataKey="forecastHigh"
            name="Forecast High"
            stroke="none"
            fill="url(#forecastGrad)"
            dot={false}
            connectNulls={false}
            legendType="none"
          />
          <Area
            type="monotone"
            dataKey="forecastLow"
            name="Forecast Low"
            stroke="#a78bfa"
            strokeDasharray="3 2"
            strokeWidth={1}
            fill="#1e2030"
            dot={false}
            connectNulls={false}
            legendType="none"
          />
        </ComposedChart>
      </ResponsiveContainer>

      {/* Summary stats row */}
      <div style={{ display: 'flex', gap: 24, marginTop: 8, paddingTop: 8, borderTop: '1px solid #2d2f45' }}>
        {[
          { label: 'Rolling Avg', value: `${data.rollingAvg} pts` },
          { label: 'Weighted Avg', value: `${data.weightedAvg} pts` },
          { label: 'Std Dev', value: `±${data.stdDev}` },
          { label: 'Forecast', value: `${data.forecast.point} pts` },
        ].map(({ label, value }) => (
          <div key={label}>
            <div style={{ color: '#475569', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.05em' }}>{label}</div>
            <div style={{ color: '#e2e8f0', fontSize: 13, fontWeight: 600 }}>{value}</div>
          </div>
        ))}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add apps/web/src/components/mirror/VelocityStatsChart.tsx
git commit -m "feat: add VelocityStatsChart component"
```

---

### Task 5: Insert `VelocityStatsChart` into `VelocityMirrorPage`

**Files:**
- Modify: `apps/web/src/pages/VelocityMirrorPage.tsx`

- [ ] **Step 1: Add the import**

Find:
```tsx
import { SprintHealthScore } from '../components/mirror/SprintHealthScore'
```

Add after it:
```tsx
import { VelocityStatsChart } from '../components/mirror/VelocityStatsChart'
```

- [ ] **Step 2: Insert the chart between BurndownChart and DeveloperCapacityRow**

Find:
```tsx
          <BurndownChart sprintLength={sprint?.sprintLength} />
          <DeveloperCapacityRow />
```

Replace with:
```tsx
          <BurndownChart sprintLength={sprint?.sprintLength} />
          <VelocityStatsChart />
          <DeveloperCapacityRow />
```

- [ ] **Step 3: Verify the frontend builds without type errors**

```bash
cd apps/web && npx tsc --noEmit
```

Expected: No type errors.

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/pages/VelocityMirrorPage.tsx
git commit -m "feat: insert VelocityStatsChart into VelocityMirrorPage"
```

---

## Branch & PR

- [ ] **Create branch before writing any code**

```bash
git checkout -b feat/velocity-engine
```

- [ ] **Final verification — run full backend test suite**

```bash
cd apps/api && python -m pytest -v
```

Expected: All tests PASS.

- [ ] **Open PR**

```bash
gh pr create --title "feat: statistical velocity stats endpoint + chart (Track D)" \
  --body "Adds GET /api/velocity/stats with rolling avg, weighted avg, std dev, trend, 90% CI, outlier detection, and next-sprint forecast. Frontend VelocityStatsChart displays rolling vs weighted avg as a two-line Recharts chart with forecast band and trend arrow."
```
