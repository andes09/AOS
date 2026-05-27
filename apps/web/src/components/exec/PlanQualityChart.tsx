// apps/web/src/components/exec/PlanQualityChart.tsx
//
// Initiative A, Wave 4 — SA-15.
// Bar chart of trailing-N completed-sprint plan-override rates.
// Sprints with override_rate > 0.5 get a red warning badge.

import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '@clerk/clerk-react'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from 'recharts'
import { useApi, ApiError } from '../../lib/api'
import { Card, CardBody } from '../ui/Card'
import { Select } from '../ui/Select'
import { Badge } from '../ui/Badge'
import type { PlanQualityPoint, TeamSummary } from '../../types/exec'

interface Props {
  teams: TeamSummary[]
}

// Recharts colors — stroke/fill are SVG attrs so CSS vars don't work.
const CHART = {
  bar:     '#579DFF',
  warning: '#F85149',
  grid:    '#30363d',
  axis:    '#8b949e',
}

const WARN_THRESHOLD = 0.5

interface TooltipPayloadItem {
  payload: PlanQualityPoint & { ratePct: number }
}

function PlanQualityTooltip({ active, payload }: { active?: boolean; payload?: TooltipPayloadItem[] }) {
  if (!active || !payload || !payload.length) return null
  const point = payload[0].payload
  const reasons = point.overridesByReason ?? {}
  const reasonEntries = Object.entries(reasons)
  return (
    <div style={{
      background: 'var(--color-bg-elevated)',
      border: '1px solid var(--color-border)',
      borderRadius: 6,
      padding: '8px 10px',
      fontFamily: 'var(--font-sans)',
      fontSize: 12,
      color: 'var(--color-text-primary)',
      minWidth: 160,
    }}>
      <div style={{ fontWeight: 700, marginBottom: 4 }}>{point.sprintName}</div>
      <div style={{ color: 'var(--color-text-secondary)', marginBottom: 6 }}>
        Override rate: {(point.overrideRate ?? 0).toFixed(2)} ({Math.round((point.overrideRate ?? 0) * 100)}%)
      </div>
      {reasonEntries.length > 0 ? (
        <div>
          <div style={{ color: 'var(--color-text-muted)', fontSize: 11, marginBottom: 2 }}>By reason</div>
          {reasonEntries.map(([k, v]) => (
            <div key={k} style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
              <span>{k}</span>
              <span style={{ fontVariantNumeric: 'tabular-nums' }}>{v}</span>
            </div>
          ))}
        </div>
      ) : (
        <div style={{ color: 'var(--color-text-muted)', fontSize: 11 }}>No reason breakdown</div>
      )}
    </div>
  )
}

export function PlanQualityChart({ teams }: Props) {
  const { get } = useApi()
  const { isLoaded, isSignedIn } = useAuth()
  const [selectedTeamId, setSelectedTeamId] = useState<string>(teams[0]?.teamId ?? '')

  const teamId = selectedTeamId || teams[0]?.teamId || ''
  const query = useQuery<PlanQualityPoint[], ApiError>({
    queryKey: ['exec-plan-quality', teamId],
    queryFn: () => get<PlanQualityPoint[]>(`/api/exec/plan-quality/${teamId}?n=8`),
    enabled: Boolean(teamId) && isLoaded && isSignedIn,
  })

  const chartData = useMemo(() => {
    return (query.data ?? []).map(p => ({
      ...p,
      ratePct: Math.round((p.overrideRate ?? 0) * 100),
    }))
  }, [query.data])

  const hasWarning = chartData.some(p => (p.overrideRate ?? 0) > WARN_THRESHOLD)

  return (
    <Card style={{ marginTop: 20 }}>
      <CardBody style={{ padding: '14px 14px 10px' }}>
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 12,
          marginBottom: 12,
          flexWrap: 'wrap',
        }}>
          <div>
            <div style={{
              color: 'var(--color-text-muted)',
              fontFamily: 'var(--font-sans)',
              fontSize: 'var(--text-xs)',
              fontWeight: 700,
              textTransform: 'uppercase',
              letterSpacing: '0.06em',
            }}>
              Plan Override Rate
            </div>
            <div style={{
              color: 'var(--color-text-secondary)',
              fontFamily: 'var(--font-sans)',
              fontSize: 'var(--text-sm)',
              marginTop: 2,
            }}>
              Trailing 8 completed sprints
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            {hasWarning && (
              <Badge variant="danger">High override sprint</Badge>
            )}
            {teams.length > 1 && (
              <Select
                value={teamId}
                onChange={e => setSelectedTeamId(e.target.value)}
                containerStyle={{ minWidth: 160 }}
              >
                {teams.map(t => (
                  <option key={t.teamId} value={t.teamId}>{t.name}</option>
                ))}
              </Select>
            )}
          </div>
        </div>

        {query.isLoading && (
          <div style={{ height: 240, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--color-text-muted)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)' }}>
            Loading plan-quality data…
          </div>
        )}

        {!query.isLoading && query.isError && (
          <div style={{ height: 240, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--color-danger)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)' }}>
            Failed to load plan-quality data.
          </div>
        )}

        {!query.isLoading && !query.isError && chartData.length === 0 && (
          <div style={{ height: 240, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--color-text-muted)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)' }}>
            No completed sprints with override data yet.
          </div>
        )}

        {!query.isLoading && !query.isError && chartData.length > 0 && (
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={chartData} margin={{ top: 4, right: 12, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} />
              <XAxis
                dataKey="sprintName"
                tick={{ fill: CHART.axis, fontSize: 11 }}
                tickLine={false}
                axisLine={false}
                interval={0}
              />
              <YAxis
                domain={[0, 1]}
                tickFormatter={(v: number) => `${Math.round(v * 100)}%`}
                tick={{ fill: CHART.axis, fontSize: 11 }}
                tickLine={false}
                axisLine={false}
              />
              <Tooltip content={<PlanQualityTooltip />} cursor={{ fill: 'rgba(87,157,255,0.08)' }} />
              <Bar dataKey="overrideRate" radius={[4, 4, 0, 0]}>
                {chartData.map((p, i) => (
                  <Cell
                    key={p.sprintId ?? i}
                    fill={(p.overrideRate ?? 0) > WARN_THRESHOLD ? CHART.warning : CHART.bar}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </CardBody>
    </Card>
  )
}
