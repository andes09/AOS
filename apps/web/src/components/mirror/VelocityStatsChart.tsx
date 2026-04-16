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
import { Card, CardBody } from '../ui/Card'

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

// Recharts stroke/fill are SVG attrs — CSS vars don't work there.
// These are stable chart-specific colors, not theme colors.
const CHART = {
  velocity:   '#64748b',
  rolling:    '#6366f1',
  weighted:   '#a78bfa',
  forecast:   '#a78bfa',
  outlier:    '#f59e0b',
  grid:       '#30363d',
}

function TrendArrow({ trend }: { trend: number }) {
  const arrow = trend > 0.5 ? '↑' : trend < -0.5 ? '↓' : '→'
  const color = trend > 0.5 ? 'var(--color-success)' : trend < -0.5 ? 'var(--color-danger)' : 'var(--color-text-muted)'
  return (
    <span style={{ color, fontSize: 18, fontWeight: 700, marginLeft: 8 }}>
      {arrow}
    </span>
  )
}

interface VelocityStatsChartProps {
  window: number
  fromDate: string | null
  visibleMetrics: string[]
  teamId?: string
}

export function VelocityStatsChart({ window, fromDate, visibleMetrics, teamId }: VelocityStatsChartProps) {
  const { get } = useApi()
  const { isLoaded, isSignedIn } = useAuth()

  const params = new URLSearchParams()
  params.set('window', String(window))
  if (fromDate) params.set('fromDate', fromDate)
  if (teamId && teamId !== 'default') params.set('team_id', teamId)

  const { data, isLoading, isError, error } = useQuery<VelocityStatsData, ApiError>({
    queryKey: ['velocity-stats', window, fromDate, teamId],
    queryFn: () => get<VelocityStatsData>(`/api/velocity/stats?${params.toString()}`),
    enabled: isLoaded && isSignedIn,
  })

  if (isLoading) {
    return (
      <Card style={{ height: 280, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <span style={{ color: 'var(--color-text-muted)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)' }}>
          Loading velocity stats…
        </span>
      </Card>
    )
  }

  if (isError) {
    const is422 = error instanceof ApiError && error.status === 422
    return (
      <Card style={{ height: 280, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <span style={{ color: is422 ? 'var(--color-text-muted)' : 'var(--color-danger)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)' }}>
          {is422 ? 'Not enough completed sprints for velocity stats' : 'Failed to load velocity stats'}
        </span>
      </Card>
    )
  }

  if (!data) return null

  // Compute per-sprint trailing rolling/weighted averages so lines show
  // actual history rather than a flat scalar repeated across all points.
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

  const outlierNames = new Set(
    data.sprintWindow
      .filter(s => data.stdDev > 0 && Math.abs(s.velocity - data.rollingAvg) > 1.5 * data.stdDev)
      .map(s => s.name)
  )

  return (
    <Card>
      <CardBody style={{ padding: '12px 12px 8px' }}>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 12 }}>
        <span style={{ color: 'var(--color-text-muted)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-xs)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          Velocity Trend
        </span>
        <TrendArrow trend={data.trend} />
        <span style={{ marginLeft: 'auto', color: 'var(--color-text-muted)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-xs)' }}>
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
          <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} />
          <XAxis
            dataKey="name"
            tick={{ fill: CHART.velocity, fontSize: 10 }}
            tickLine={false}
            axisLine={false}
          />
          <YAxis
            tick={{ fill: CHART.velocity, fontSize: 11 }}
            tickLine={false}
            axisLine={false}
            label={{ value: 'Points', angle: -90, position: 'insideLeft', fill: CHART.velocity, fontSize: 11 }}
          />
          <Tooltip
            contentStyle={{ background: 'var(--color-bg-elevated)', border: '1px solid var(--color-border)', borderRadius: 6, fontSize: 12 }}
            labelStyle={{ color: 'var(--color-text-secondary)' }}
            itemStyle={{ color: 'var(--color-text-primary)' }}
            formatter={(value: unknown) => value == null ? '—' : `${value} pts`}
          />
          <Legend wrapperStyle={{ fontSize: 11, color: 'var(--color-text-secondary)', paddingTop: 8 }} />

          {/* Actual velocity per sprint */}
          <Line
            type="monotone"
            dataKey="velocity"
            name="Actual"
            stroke={CHART.velocity}
            strokeWidth={1.5}
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            dot={(props: any) =>
              outlierNames.has(props.payload?.name)
                ? <circle key={props.payload.name} cx={props.cx} cy={props.cy} r={5} fill={CHART.outlier} stroke={CHART.outlier} />
                : <circle key={props.payload?.name} cx={props.cx} cy={props.cy} r={3} fill={CHART.velocity} />
            }
            connectNulls={false}
          />

          {/* Rolling avg — solid indigo */}
          {visibleMetrics.includes('rolling') && (
            <Line
              type="monotone"
              dataKey="rollingAvg"
              name="Rolling Avg"
              stroke={CHART.rolling}
              strokeWidth={2}
              dot={false}
              connectNulls={false}
            />
          )}

          {/* Weighted avg — dashed violet */}
          {visibleMetrics.includes('weighted') && (
            <Line
              type="monotone"
              dataKey="weightedAvg"
              name="Weighted Avg"
              stroke={CHART.weighted}
              strokeWidth={2}
              strokeDasharray="4 2"
              dot={false}
              connectNulls={false}
            />
          )}

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
            stroke={CHART.forecast}
            strokeDasharray="3 2"
            strokeWidth={1}
            fillOpacity={0}
            dot={false}
            connectNulls={false}
            legendType="none"
          />
        </ComposedChart>
      </ResponsiveContainer>

      {/* Summary stats row */}
      <div style={{ display: 'flex', gap: 24, marginTop: 8, paddingTop: 8, borderTop: '1px solid var(--color-border)' }}>
        {[
          { label: 'Rolling Avg', value: `${data.rollingAvg} pts`, metric: 'rolling' },
          { label: 'Weighted Avg', value: `${data.weightedAvg} pts`, metric: 'weighted' },
          { label: 'Std Dev', value: `±${data.stdDev}`, metric: 'stddev' },
          { label: 'Forecast', value: `${data.forecast.point} pts`, metric: null },
        ]
          .filter(({ metric }) => metric === null || visibleMetrics.includes(metric))
          .map(({ label, value }) => (
            <div key={label}>
              <div style={{ color: 'var(--color-text-muted)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-xs)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{label}</div>
              <div style={{ color: 'var(--color-text-primary)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)', fontWeight: 600 }}>{value}</div>
            </div>
          ))}
      </div>
      </CardBody>
    </Card>
  )
}
