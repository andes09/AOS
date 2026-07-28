// Daily commit counts, summed across every org.

import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

import { Card, CardBody, CardHeader } from '../ui/Card'
import { Spinner } from '../ui/Spinner'
import { useChartColors } from '../../hooks/useChartTheme'
import type { CommitsPoint } from '../../types/masterDashboard'

interface Props {
  series: CommitsPoint[] | undefined
  isLoading: boolean
}

function formatDate(d: string): string {
  const dt = new Date(d + 'T00:00:00')
  return dt.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

export function CommitsChart({ series, isLoading }: Props) {
  const colors = useChartColors()

  return (
    <Card style={{ flex: '1 1 420px', minWidth: 0 }}>
      <CardHeader>
        <span style={{ fontSize: 'var(--text-sm)', fontWeight: 'var(--font-weight-semibold)' as const }}>
          Commits
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
            No commits in this range.
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={series} margin={{ top: 4, right: 8, left: -16, bottom: 0 }}>
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
              <Tooltip labelFormatter={formatDate} contentStyle={{ fontSize: 12, borderRadius: 6 }} />
              <Bar dataKey="commits" name="Commits" fill={colors.accent} radius={[3, 3, 0, 0]} maxBarSize={28} />
            </BarChart>
          </ResponsiveContainer>
        )}
      </CardBody>
    </Card>
  )
}
