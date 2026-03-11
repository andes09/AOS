// apps/web/src/components/mirror/BurndownChart.tsx

import { useQuery } from '@tanstack/react-query'
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
import { useApi } from '../../lib/api'

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
}

interface BurndownApiResponse {
  data: BurndownDataPoint[]
  sprintLength: number
  predictedEndDay: number
}

export function BurndownChart({ data, sprintLength, predictedEndDay }: BurndownChartProps) {
  const { get } = useApi()

  const query = useQuery<BurndownApiResponse>({
    queryKey: ['burndown'],
    queryFn: () => get<BurndownApiResponse>('/api/velocity/burndown'),
    enabled: !data,
  })

  const chartData = data ?? query.data?.data ?? []
  const length = sprintLength ?? query.data?.sprintLength ?? 14
  const predictedEnd = predictedEndDay ?? query.data?.predictedEndDay ?? length

  const isOverrun = predictedEnd > length

  if (!data && query.isLoading) {
    return (
      <div style={{ background: '#1e2030', borderRadius: 8, padding: '1.5rem', height: 280, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <span style={{ color: '#64748b', fontSize: 13 }}>Loading burndown data…</span>
      </div>
    )
  }

  if (!data && query.isError) {
    return (
      <div style={{ background: '#1e2030', borderRadius: 8, padding: '1.5rem', height: 280, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <span style={{ color: '#ef4444', fontSize: 13 }}>Failed to load burndown data</span>
      </div>
    )
  }

  return (
    <div style={{ background: '#1e2030', borderRadius: 8, padding: '1rem 1rem 0.5rem' }}>
      <div style={{ color: '#94a3b8', fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 12 }}>
        Burndown
      </div>
      <ResponsiveContainer width="100%" height={240}>
        <AreaChart data={chartData} margin={{ top: 4, right: 12, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id="actualGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#6366f1" stopOpacity={0.3} />
              <stop offset="95%" stopColor="#6366f1" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="predictedGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#a78bfa" stopOpacity={0.2} />
              <stop offset="95%" stopColor="#a78bfa" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#2d2f45" />
          <XAxis
            dataKey="day"
            tick={{ fill: '#64748b', fontSize: 11 }}
            tickLine={false}
            axisLine={false}
            label={{ value: 'Day', position: 'insideBottom', offset: -2, fill: '#64748b', fontSize: 11 }}
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
            labelFormatter={(label: number) => `Day ${label}`}
          />
          <Legend
            wrapperStyle={{ fontSize: 11, color: '#94a3b8', paddingTop: 8 }}
          />

          {/* Red overrun zone */}
          {isOverrun && (
            <ReferenceArea
              x1={length}
              x2={predictedEnd}
              fill="#ef4444"
              fillOpacity={0.12}
              label={{ value: 'Overrun', position: 'insideTopRight', fill: '#ef4444', fontSize: 10 }}
            />
          )}

          {/* Ideal: dashed gray */}
          <Area
            type="linear"
            dataKey="ideal"
            name="Ideal"
            stroke="#475569"
            strokeDasharray="5 3"
            strokeWidth={1.5}
            fill="none"
            dot={false}
          />

          {/* Actual: solid indigo */}
          <Area
            type="monotone"
            dataKey="actual"
            name="Actual"
            stroke="#6366f1"
            strokeWidth={2}
            fill="url(#actualGrad)"
            dot={false}
            connectNulls={false}
          />

          {/* Predicted: dotted violet */}
          <Area
            type="monotone"
            dataKey="predicted"
            name="Predicted"
            stroke="#a78bfa"
            strokeDasharray="3 2"
            strokeWidth={2}
            fill="url(#predictedGrad)"
            dot={false}
            connectNulls={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}
