// Cumulative users/orgs over the selected range. Two series → always shows
// a legend; thin 2px lines, recessive grid, tooltip carries the daily deltas.

import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

import { Card, CardBody, CardHeader } from '../ui/Card'
import { Spinner } from '../ui/Spinner'
import { useChartColors } from '../../hooks/useChartTheme'
import type { SignupsPoint } from '../../types/masterDashboard'

interface Props {
  series: SignupsPoint[] | undefined
  isLoading: boolean
}

function formatDate(d: string): string {
  const dt = new Date(d + 'T00:00:00')
  return dt.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

export function SignupsChart({ series, isLoading }: Props) {
  const colors = useChartColors()

  return (
    <Card style={{ flex: '1 1 420px', minWidth: 0 }}>
      <CardHeader>
        <span style={{ fontSize: 'var(--text-sm)', fontWeight: 'var(--font-weight-semibold)' as const }}>
          Signups
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
            No signups in this range.
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={series} margin={{ top: 4, right: 8, left: -16, bottom: 0 }}>
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
              <YAxis stroke={colors.axis} tick={{ fontSize: 11 }} tickLine={false} axisLine={false} allowDecimals={false} />
              <Tooltip
                labelFormatter={formatDate}
                contentStyle={{ fontSize: 12, borderRadius: 6 }}
                formatter={(value: number, name: string) => [value, name]}
              />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Line
                type="monotone"
                dataKey="cumulativeUsers"
                name="Cumulative users"
                stroke={colors.accent}
                strokeWidth={2}
                dot={false}
              />
              <Line
                type="monotone"
                dataKey="cumulativeOrgs"
                name="Cumulative orgs"
                stroke={colors.success}
                strokeWidth={2}
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </CardBody>
    </Card>
  )
}
