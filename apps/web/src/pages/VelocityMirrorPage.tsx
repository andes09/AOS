// apps/web/src/pages/VelocityMirrorPage.tsx

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '@clerk/clerk-react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useApi, ApiError } from '../lib/api'
import { useAppRole } from '../hooks/useAppRole'
import { BurndownChart } from '../components/mirror/BurndownChart'
import { DeveloperCapacityRow } from '../components/mirror/DeveloperCapacityRow'
import { AlertFeed } from '../components/mirror/AlertFeed'
import { SprintHealthScore } from '../components/mirror/SprintHealthScore'
import { VelocityStatsChart } from '../components/mirror/VelocityStatsChart'
import { VelocityControls } from '../components/mirror/VelocityControls'
import { Badge } from '../components/ui/Badge'
import { Card, CardBody } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import type { RadarResponse } from '../types/dependencyRadar'
import type { TeamListItem } from '../types/multiTeam'

interface CurrentSprint {
  id: string
  name: string
  startDate: string
  endDate: string
  sprintLength: number
  totalPoints: number
}

interface CompletedSprint {
  id: string
  name: string
  startDate: string | null
  endDate: string | null
}

interface CompletedSprintsResponse {
  sprints: CompletedSprint[]
}

export function VelocityMirrorPage() {
  const [window, setWindow] = useState(6)
  const [fromDate, setFromDate] = useState<string | null>(null)
  const [visibleMetrics, setVisibleMetrics] = useState(['rolling', 'weighted', 'stddev'])
  const [searchParams, setSearchParams] = useSearchParams()

  const { get } = useApi()
  const { isLoaded, isSignedIn } = useAuth()
  const { appRole } = useAppRole()
  const isLead = appRole === 'lead' || appRole === 'exec' || appRole === 'admin'
  const navigate = useNavigate()

  const activeTeamId = searchParams.get('teamId') || 'default'
  const teamParam = activeTeamId !== 'default' ? `?team_id=${activeTeamId}` : ''

  const { data: teamsData } = useQuery<{ teams: TeamListItem[] }>({
    queryKey: ['teams-list'],
    queryFn: () => get<{ teams: TeamListItem[] }>('/api/teams'),
    enabled: isLoaded && !!isSignedIn,
  })
  const teams = teamsData?.teams ?? []

  const { data: sprint, isLoading, isError, error } = useQuery<CurrentSprint, ApiError>({
    queryKey: ['current-sprint', activeTeamId],
    queryFn: () => get<CurrentSprint>(`/api/sprints/current${teamParam}`),
    enabled: isLoaded && isSignedIn,
  })

  const { data: completedSprintsData } = useQuery<CompletedSprintsResponse>({
    queryKey: ['completed-sprints', activeTeamId],
    queryFn: () => get<CompletedSprintsResponse>(`/api/sprints/completed${teamParam}`),
    enabled: isLoaded && isSignedIn,
  })

  const { data: radarData } = useQuery<RadarResponse>({
    queryKey: ['dependency-radar', activeTeamId],
    queryFn: () => get<RadarResponse>(`/api/dependency-radar/team/${activeTeamId}`),
    enabled: isLoaded && isSignedIn && isLead,
  })

  const highRiskDeps = radarData?.dependencies.filter(d => d.riskLevel === 'high') ?? []

  function handleTeamChange(teamId: string) {
    if (teamId === 'default') {
      setSearchParams({})
    } else {
      setSearchParams({ teamId })
    }
  }

  return (
    <div style={{ fontFamily: 'var(--font-sans)', minHeight: '100%' }}>

      {/* Page header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 20 }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 4 }}>
            <h1 style={{ color: 'var(--color-text-primary)', fontSize: 'var(--text-xl)', fontWeight: 700, margin: 0 }}>
              Sprint Pulse
            </h1>
            {teams.length > 1 && (
              <select
                value={activeTeamId}
                onChange={e => handleTeamChange(e.target.value)}
                style={{
                  background: 'var(--color-bg-elevated)',
                  border: '1px solid var(--color-border)',
                  borderRadius: 'var(--radius-md)',
                  color: 'var(--color-text-primary)',
                  fontFamily: 'var(--font-sans)',
                  fontSize: 'var(--text-sm)',
                  padding: '4px 10px',
                  cursor: 'pointer',
                  outline: 'none',
                }}
              >
                <option value="default">Default team</option>
                {teams.filter(t => !t.isPrimary).map(t => (
                  <option key={t.teamId} value={t.teamId}>{t.teamName}</option>
                ))}
              </select>
            )}
          </div>
          <div style={{ color: 'var(--color-text-muted)', fontSize: 'var(--text-sm)', marginTop: 4 }}>
            Live sprint health and execution signals
          </div>
          {isLoading && (
            <div style={{ color: 'var(--color-text-muted)', fontSize: 'var(--text-sm)', marginTop: 4 }}>Loading sprint…</div>
          )}
          {isError && (
            <div style={{
              color: error instanceof ApiError && error.status === 404 ? 'var(--color-text-muted)' : 'var(--color-danger)',
              fontSize: 'var(--text-sm)',
              marginTop: 4,
            }}>
              {error instanceof ApiError && error.status === 404 ? 'No active sprint — connect Jira to get started' : 'Could not load sprint data'}
            </div>
          )}
          {sprint && (
            <div style={{ color: 'var(--color-text-muted)', fontSize: 'var(--text-sm)', marginTop: 4 }}>
              {sprint.name} · {new Date(sprint.startDate).toLocaleDateString()} – {new Date(sprint.endDate).toLocaleDateString()}
            </div>
          )}
        </div>

        {/* Health score + completed sprint retro links */}
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 8 }}>
          <SprintHealthScore sprintId={sprint?.id} />
          {(completedSprintsData?.sprints ?? []).length > 0 && (
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
              {(completedSprintsData?.sprints ?? []).slice(0, 3).map(s => (
                <Button
                  key={s.id}
                  size="sm"
                  variant="ghost"
                  onClick={() => navigate(`/app/retrospective?sprintId=${s.id}`)}
                >
                  {s.name} · View Retro
                </Button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Main content + sidebar */}
      <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>

        {/* Left: chart + capacity */}
        <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 16 }}>
          <BurndownChart sprintLength={sprint?.sprintLength} teamId={activeTeamId} />
          <VelocityControls
            window={window}
            setWindow={setWindow}
            fromDate={fromDate}
            setFromDate={setFromDate}
            visibleMetrics={visibleMetrics}
            setVisibleMetrics={setVisibleMetrics}
          />
          <VelocityStatsChart
            window={window}
            fromDate={fromDate}
            visibleMetrics={visibleMetrics}
            teamId={activeTeamId}
          />
          <DeveloperCapacityRow teamId={activeTeamId} />

          {/* Completed sprints */}
          {(completedSprintsData?.sprints ?? []).length > 0 && (
            <Card>
              <CardBody>
                <div style={{
                  color: 'var(--color-text-muted)',
                  fontSize: 'var(--text-xs)',
                  fontWeight: 600,
                  textTransform: 'uppercase',
                  letterSpacing: '0.06em',
                  marginBottom: 10,
                }}>
                  Completed Sprints
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {(completedSprintsData?.sprints ?? []).map(s => (
                    <div key={s.id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
                      <span style={{ color: 'var(--color-text-primary)', fontSize: 'var(--text-sm)' }}>{s.name}</span>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => navigate(`/app/retrospective?sprintId=${s.id}`)}
                      >
                        View Retro
                      </Button>
                    </div>
                  ))}
                </div>
              </CardBody>
            </Card>
          )}
        </div>

        {/* Right: alerts + high-risk dep alerts */}
        <div style={{ width: 300, flexShrink: 0, display: 'flex', flexDirection: 'column', gap: 16 }}>
          <AlertFeed />

          {highRiskDeps.length > 0 && (
            <div>
              <div style={{
                color: 'var(--color-text-muted)',
                fontSize: 'var(--text-xs)',
                fontWeight: 700,
                textTransform: 'uppercase',
                letterSpacing: '0.06em',
                marginBottom: 10,
                display: 'flex',
                alignItems: 'center',
                gap: 8,
              }}>
                <span>High-Risk Dependencies</span>
                <Badge variant="danger">{highRiskDeps.length}</Badge>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {highRiskDeps.map(dep => (
                  <Card
                    key={dep.id}
                    style={{ borderLeft: '3px solid var(--color-danger)' }}
                  >
                    <CardBody style={{ padding: '10px 14px' }}>
                      <div style={{ color: 'var(--color-text-primary)', fontSize: 'var(--text-sm)', fontWeight: 600, marginBottom: 3 }}>
                        {dep.ticketKey}
                      </div>
                      {dep.description && (
                        <div style={{ color: 'var(--color-text-secondary)', fontSize: 'var(--text-xs)', marginBottom: 8, lineHeight: 1.4 }}>
                          {dep.description}
                        </div>
                      )}
                      <Button size="sm" variant="ghost" onClick={() => navigate('/app/dependency-radar')}>
                        View Radar
                      </Button>
                    </CardBody>
                  </Card>
                ))}
              </div>
            </div>
          )}
        </div>

      </div>
    </div>
  )
}
