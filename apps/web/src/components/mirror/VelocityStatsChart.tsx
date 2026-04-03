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

interface VelocityStatsChartProps {
  window: number
  fromDate: string | null
  visibleMetrics: string[]
}

export function VelocityStatsChart({ window, fromDate, visibleMetrics }: VelocityStatsChartProps) {
  const { get } = useApi()
  const { isLoaded, isSignedIn } = useAuth()

  const params = new URLSearchParams()
  params.set('window', String(window))
  if (fromDate) params.set('fromDate', fromDate)

  const { data, isLoading, isError, error } = useQuery<VelocityStatsData, ApiError>({
    queryKey: ['velocity-stats', window, fromDate],
    queryFn: () => get<VelocityStatsData>(`/api/velocity/stats?${params.toString()}`),
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

          {/* Rolling avg — solid indigo */}
          {visibleMetrics.includes('rolling') && (
            <Line
              type="monotone"
              dataKey="rollingAvg"
              name="Rolling Avg"
              stroke="#6366f1"
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
              stroke="#a78bfa"
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
          { label: 'Rolling Avg', value: `${data.rollingAvg} pts`, metric: 'rolling' },
          { label: 'Weighted Avg', value: `${data.weightedAvg} pts`, metric: 'weighted' },
          { label: 'Std Dev', value: `±${data.stdDev}`, metric: 'stddev' },
          { label: 'Forecast', value: `${data.forecast.point} pts`, metric: null },
        ]
          .filter(({ metric }) => metric === null || visibleMetrics.includes(metric))
          .map(({ label, value }) => (
            <div key={label}>
              <div style={{ color: '#475569', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.05em' }}>{label}</div>
              <div style={{ color: '#e2e8f0', fontSize: 13, fontWeight: 600 }}>{value}</div>
            </div>
          ))}
      </div>
    </div>
  )
}
