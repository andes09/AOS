// apps/web/src/components/mirror/BurndownChart.tsx

import { useQuery } from '@tanstack/react-query'
import { useAuth } from '@clerk/clerk-react'
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ReferenceArea,
  ResponsiveContainer,
} from 'recharts'
import { useApi, ApiError } from '../../lib/api'
import { Card, CardBody } from '../ui/Card'

export interface BurndownDataPoint {
  day: number
  ideal: number
  actual: number | null
  predicted: number | null
}

interface BurndownChartProps {
  data?: BurndownDataPoint[]
  sprintLength?: number
  predictedEndDay?: number
  teamId?: string
}

interface BurndownApiResponse {
  data: BurndownDataPoint[]
  sprintLength: number
  predictedEndDay: number
}

// Recharts stroke/fill are SVG attrs — CSS vars don't work there.
// These are stable chart-specific colors, not theme colors.
const CHART = {
  actual:    '#579DFF',
  predicted: '#9F8FEF',
  ideal:     '#8b949e',
  danger:    '#F85149',
  grid:      '#30363d',
}

export function BurndownChart({ data, sprintLength, predictedEndDay, teamId }: BurndownChartProps) {
  const { get } = useApi()
  const { isLoaded, isSignedIn } = useAuth()

  const teamParam = teamId && teamId !== 'default' ? `?team_id=${teamId}` : ''
  const query = useQuery<BurndownApiResponse>({
    queryKey: ['burndown', teamId],
    queryFn: () => get<BurndownApiResponse>(`/api/velocity/burndown${teamParam}`),
    enabled: !data && isLoaded && isSignedIn,
  })

  const chartData = data ?? query.data?.data ?? []
  const length = sprintLength ?? query.data?.sprintLength ?? 14
  const predictedEnd = predictedEndDay ?? query.data?.predictedEndDay ?? length
  const isOverrun = predictedEnd > length

  if (!data && query.isLoading) {
    return (
      <Card style={{ height: 280, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <span style={{ color: 'var(--color-text-muted)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)' }}>
          Loading burndown data…
        </span>
      </Card>
    )
  }

  if (!data && query.isError) {
    const is404 = query.error instanceof ApiError && query.error.status === 404
    return (
      <Card style={{ height: 280, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <span style={{ color: is404 ? 'var(--color-text-muted)' : 'var(--color-danger)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)' }}>
          {is404 ? 'No active sprint data yet' : 'Failed to load burndown data'}
        </span>
      </Card>
    )
  }

  return (
    <Card>
      <CardBody style={{ padding: '12px 12px 8px' }}>
        <div style={{
          color: 'var(--color-text-muted)',
          fontFamily: 'var(--font-sans)',
          fontSize: 'var(--text-xs)',
          fontWeight: 700,
          textTransform: 'uppercase',
          letterSpacing: '0.06em',
          marginBottom: 12,
        }}>
          Burndown
        </div>
        <ResponsiveContainer width="100%" height={240}>
          <AreaChart data={chartData} margin={{ top: 4, right: 12, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id="actualGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor={CHART.actual} stopOpacity={0.3} />
                <stop offset="95%" stopColor={CHART.actual} stopOpacity={0} />
              </linearGradient>
              <linearGradient id="predictedGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor={CHART.predicted} stopOpacity={0.2} />
                <stop offset="95%" stopColor={CHART.predicted} stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} />
            <XAxis
              dataKey="day"
              tick={{ fill: CHART.ideal, fontSize: 11 }}
              tickLine={false}
              axisLine={false}
              label={{ value: 'Day', position: 'insideBottom', offset: -2, fill: CHART.ideal, fontSize: 11 }}
            />
            <YAxis
              tick={{ fill: CHART.ideal, fontSize: 11 }}
              tickLine={false}
              axisLine={false}
              label={{ value: 'Points', angle: -90, position: 'insideLeft', fill: CHART.ideal, fontSize: 11 }}
            />
            <Tooltip
              contentStyle={{ background: 'var(--color-bg-elevated)', border: '1px solid var(--color-border)', borderRadius: 6, fontSize: 12 }}
              labelStyle={{ color: 'var(--color-text-secondary)' }}
              itemStyle={{ color: 'var(--color-text-primary)' }}
              formatter={(value: unknown) => value == null ? '—' : `${value} pts`}
              labelFormatter={(label: number) => `Day ${label}`}
            />
            <Legend wrapperStyle={{ fontSize: 11, color: 'var(--color-text-secondary)', paddingTop: 8 }} />

            {isOverrun && (
              <ReferenceArea
                x1={length}
                x2={predictedEnd}
                fill={CHART.danger}
                fillOpacity={0.12}
                label={{ value: 'Overrun', position: 'insideTopRight', fill: CHART.danger, fontSize: 10 }}
              />
            )}

            <Area type="linear" dataKey="ideal" name="Ideal"
              stroke={CHART.ideal} strokeDasharray="5 3" strokeWidth={1.5} fill="none" dot={false} />
            <Area type="monotone" dataKey="actual" name="Actual"
              stroke={CHART.actual} strokeWidth={2} fill="url(#actualGrad)" dot={false} connectNulls={false} />
            <Area type="monotone" dataKey="predicted" name="Predicted"
              stroke={CHART.predicted} strokeDasharray="3 2" strokeWidth={2} fill="url(#predictedGrad)" dot={false} connectNulls={false} />
          </AreaChart>
        </ResponsiveContainer>
      </CardBody>
    </Card>
  )
}
