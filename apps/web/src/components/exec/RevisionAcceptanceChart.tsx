// apps/web/src/components/exec/RevisionAcceptanceChart.tsx
//
// Initiative B, Wave 4 — SB-14.
// Bar chart of trailing-N completed-sprint Scope Cop revision-acceptance rates.
// When the latest sprint's acceptance rate < 0.3, a warning banner surfaces:
// "Scope Cop suggestions aren't landing — review the prompt".
//
// Mirrors PlanQualityChart: same per-team selector + react-query fetch shape.

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
import { Alert } from '../ui/Alert'
import type { RevisionAcceptancePoint, TeamSummary } from '../../types/exec'

interface Props {
  teams: TeamSummary[]
}

// Recharts colors — stroke/fill are SVG attrs so CSS vars don't work.
const CHART = {
  bar:     '#3FB950',
  warning: '#F85149',
  grid:    '#30363d',
  axis:    '#8b949e',
}

// Below this acceptance rate a sprint's bar turns red.
const LOW_THRESHOLD = 0.3

interface TooltipPayloadItem {
  payload: RevisionAcceptancePoint & { ratePct: number }
}

function RevisionAcceptanceTooltip({ active, payload }: { active?: boolean; payload?: TooltipPayloadItem[] }) {
  if (!active || !payload || !payload.length) return null
  const point = payload[0].payload
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
        Acceptance: {(point.acceptanceRate ?? 0).toFixed(2)} ({Math.round((point.acceptanceRate ?? 0) * 100)}%)
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
        <span>Proposed</span>
        <span style={{ fontVariantNumeric: 'tabular-nums' }}>{point.proposed}</span>
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
        <span>Accepted verbatim</span>
        <span style={{ fontVariantNumeric: 'tabular-nums' }}>{point.acceptedVerbatim}</span>
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
        <span>Edited</span>
        <span style={{ fontVariantNumeric: 'tabular-nums' }}>{point.edited}</span>
      </div>
    </div>
  )
}

export function RevisionAcceptanceChart({ teams }: Props) {
  const { get } = useApi()
  const { isLoaded, isSignedIn } = useAuth()
  const [selectedTeamId, setSelectedTeamId] = useState<string>(teams[0]?.teamId ?? '')

  const teamId = selectedTeamId || teams[0]?.teamId || ''
  const query = useQuery<RevisionAcceptancePoint[], ApiError>({
    queryKey: ['exec-revision-acceptance', teamId],
    queryFn: () => get<RevisionAcceptancePoint[]>(`/api/exec/revision-acceptance/${teamId}?n=8`),
    enabled: Boolean(teamId) && isLoaded && isSignedIn,
  })

  const chartData = useMemo(() => {
    return (query.data ?? []).map(p => ({
      ...p,
      ratePct: Math.round((p.acceptanceRate ?? 0) * 100),
    }))
  }, [query.data])

  // Threshold alert keys off the latest (most recent, last in oldest→newest list)
  // sprint that actually proposed revisions.
  const latestWithData = useMemo(() => {
    for (let i = chartData.length - 1; i >= 0; i--) {
      if (chartData[i].proposed > 0) return chartData[i]
    }
    return undefined
  }, [chartData])

  const lowAcceptance =
    latestWithData !== undefined && (latestWithData.acceptanceRate ?? 0) < LOW_THRESHOLD

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
              Scope Cop Revision Acceptance
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

        {lowAcceptance && (
          <Alert variant="warning" title="Low acceptance" style={{ marginBottom: 12 }}>
            Scope Cop suggestions aren't landing — review the prompt.
          </Alert>
        )}

        {query.isLoading && (
          <div style={{ height: 240, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--color-text-muted)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)' }}>
            Loading revision-acceptance data…
          </div>
        )}

        {!query.isLoading && query.isError && (
          <div style={{ height: 240, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--color-danger)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)' }}>
            Failed to load revision-acceptance data.
          </div>
        )}

        {!query.isLoading && !query.isError && chartData.length === 0 && (
          <div style={{ height: 240, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--color-text-muted)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)' }}>
            No completed sprints with revision data yet.
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
              <Tooltip content={<RevisionAcceptanceTooltip />} cursor={{ fill: 'rgba(63,185,80,0.08)' }} />
              <Bar dataKey="acceptanceRate" radius={[4, 4, 0, 0]}>
                {chartData.map((p, i) => (
                  <Cell
                    key={p.sprintId ?? i}
                    fill={p.proposed > 0 && (p.acceptanceRate ?? 0) < LOW_THRESHOLD ? CHART.warning : CHART.bar}
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
