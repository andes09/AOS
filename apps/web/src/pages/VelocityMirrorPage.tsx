// apps/web/src/pages/VelocityMirrorPage.tsx

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '@clerk/clerk-react'
import { useNavigate } from 'react-router-dom'
import { useApi, ApiError } from '../lib/api'
import { BurndownChart } from '../components/mirror/BurndownChart'
import { DeveloperCapacityRow } from '../components/mirror/DeveloperCapacityRow'
import { AlertFeed } from '../components/mirror/AlertFeed'
import { SprintHealthScore } from '../components/mirror/SprintHealthScore'
import { VelocityStatsChart } from '../components/mirror/VelocityStatsChart'
import { VelocityControls } from '../components/mirror/VelocityControls'
import type { RadarResponse } from '../types/dependencyRadar'

const TEAM_ID = 'default'

interface CurrentSprint {
  id: string
  name: string
  startDate: string
  endDate: string
  sprintLength: number
  totalPoints: number
}

export function VelocityMirrorPage() {
  const [window, setWindow] = useState(6)
  const [fromDate, setFromDate] = useState<string | null>(null)
  const [visibleMetrics, setVisibleMetrics] = useState(['rolling', 'weighted', 'stddev'])

  const { get } = useApi()
  const { isLoaded, isSignedIn } = useAuth()
  const navigate = useNavigate()

  const { data: sprint, isLoading, isError, error } = useQuery<CurrentSprint, ApiError>({
    queryKey: ['current-sprint'],
    queryFn: () => get<CurrentSprint>('/api/sprints/current'),
    enabled: isLoaded && isSignedIn,
  })

  const { data: radarData } = useQuery<RadarResponse>({
    queryKey: ['dependency-radar', TEAM_ID],
    queryFn: () => get<RadarResponse>(`/api/dependency-radar/team/${TEAM_ID}`),
    enabled: isLoaded && isSignedIn,
  })

  const highRiskDeps = radarData?.dependencies.filter(d => d.riskLevel === 'high') ?? []

  return (
    <div style={{
      background: '#0f1117',
      minHeight: '100%',
      padding: '1.5rem',
      fontFamily: 'system-ui, sans-serif',
    }}>

      {/* Page header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 20 }}>
        <div>
          <h1 style={{ color: '#e2e8f0', fontSize: 22, fontWeight: 800, margin: 0, letterSpacing: '-0.01em' }}>
            Velocity Mirror
          </h1>
          {isLoading && (
            <div style={{ color: '#64748b', fontSize: 13, marginTop: 4 }}>Loading sprint…</div>
          )}
          {isError && (
            <div style={{ color: error instanceof ApiError && error.status === 404 ? '#475569' : '#ef4444', fontSize: 13, marginTop: 4 }}>
              {error instanceof ApiError && error.status === 404 ? 'No active sprint — connect Jira to get started' : 'Could not load sprint data'}
            </div>
          )}
          {sprint && (
            <div style={{ color: '#64748b', fontSize: 13, marginTop: 4 }}>
              {sprint.name} · {new Date(sprint.startDate).toLocaleDateString()} – {new Date(sprint.endDate).toLocaleDateString()}
            </div>
          )}
        </div>

        {/* Health score — top right */}
        <SprintHealthScore sprintId={sprint?.id} />
      </div>

      {/* Main content + sidebar */}
      <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>

        {/* Left: chart + capacity */}
        <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 16 }}>
          <BurndownChart sprintLength={sprint?.sprintLength} />
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
          />
          <DeveloperCapacityRow />
        </div>

        {/* Right: alerts + high-risk dep alerts */}
        <div style={{ width: 300, flexShrink: 0, display: 'flex', flexDirection: 'column', gap: 16 }}>
          <AlertFeed />

          {highRiskDeps.length > 0 && (
            <div>
              <div style={{
                color: '#94a3b8',
                fontSize: 11,
                fontWeight: 700,
                textTransform: 'uppercase',
                letterSpacing: '0.06em',
                marginBottom: 10,
                display: 'flex',
                alignItems: 'center',
                gap: 8,
              }}>
                <span>High-Risk Dependencies</span>
                <span style={{
                  background: '#ef4444',
                  color: '#fff',
                  borderRadius: '50%',
                  width: 18,
                  height: 18,
                  fontSize: 10,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontWeight: 700,
                }}>
                  {highRiskDeps.length}
                </span>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {highRiskDeps.map(dep => (
                  <div
                    key={dep.id}
                    style={{
                      background: '#1e2030',
                      borderRadius: 8,
                      padding: '0.75rem 1rem',
                      borderLeft: '3px solid #ef4444',
                    }}
                  >
                    <div style={{ color: '#e2e8f0', fontSize: 13, fontWeight: 600, marginBottom: 3 }}>
                      {dep.ticketKey}
                    </div>
                    {dep.description && (
                      <div style={{ color: '#94a3b8', fontSize: 12, marginBottom: 8, lineHeight: 1.4 }}>
                        {dep.description}
                      </div>
                    )}
                    <button
                      onClick={() => navigate('/dependency-radar')}
                      style={{
                        background: 'transparent',
                        border: '1px solid #334155',
                        color: '#94a3b8',
                        borderRadius: 5,
                        padding: '3px 10px',
                        fontSize: 11,
                        fontWeight: 600,
                        cursor: 'pointer',
                      }}
                    >
                      View Radar
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

      </div>
    </div>
  )
}
