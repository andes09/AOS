// Daily AI spend, stacked by provider (Anthropic / Groq).

import { Area, AreaChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

import { Card, CardBody, CardHeader } from '../ui/Card'
import { Spinner } from '../ui/Spinner'
import { useChartColors } from '../../hooks/useChartTheme'
import type { CostPoint } from '../../types/masterDashboard'

interface Props {
  series: CostPoint[] | undefined
  isLoading: boolean
}

function formatDate(d: string): string {
  const dt = new Date(d + 'T00:00:00')
  return dt.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

function formatUsd(n: number): string {
  return `$${n.toFixed(2)}`
}

export function CostChart({ series, isLoading }: Props) {
  const colors = useChartColors()

  return (
    <Card style={{ flex: '1 1 420px', minWidth: 0 }}>
      <CardHeader>
        <span style={{ fontSize: 'var(--text-sm)', fontWeight: 'var(--font-weight-semibold)' as const }}>
          AI Cost by provider
        </span>
      </CardHeader>
      <CardBody style={{ height: 260 }}>
        {isLoading ? (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}>
            <Spinner />
          </div>
        ) : !series || series.length === 0 ? (
          <div
            style={{
              display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%',
              color: 'var(--color-text-muted)', fontSize: 'var(--text-sm)',
            }}
          >
            No AI usage in this range.
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={series} margin={{ top: 4, right: 8, left: -16, bottom: 0 }}>
              <CartesianGrid stroke={colors.grid} vertical={false} />
              <XAxis
                dataKey="date"
                tickFormatter={formatDate}
                stroke={colors.axis}
                tick={{ fontSize: 11 }}
                tickLine={false}
                axisLine={{ stroke: colors.grid }}
                minTickGap={24}
              />
              <YAxis
                stroke={colors.axis}
                tick={{ fontSize: 11 }}
                tickLine={false}
                axisLine={false}
                tickFormatter={formatUsd}
              />
              <Tooltip labelFormatter={formatDate} contentStyle={{ fontSize: 12, borderRadius: 6 }} formatter={(value: number) => formatUsd(value)} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Area
                type="monotone"
                dataKey="anthropicUsd"
                name="Anthropic"
                stackId="cost"
                stroke={colors.accent}
                fill={colors.accent}
                fillOpacity={0.35}
                strokeWidth={2}
              />
              <Area
                type="monotone"
                dataKey="groqUsd"
                name="Groq"
                stackId="cost"
                stroke={colors.warning}
                fill={colors.warning}
                fillOpacity={0.35}
                strokeWidth={2}
              />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </CardBody>
    </Card>
  )
}
