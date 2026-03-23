// apps/web/src/pages/VelocityMirrorPage.tsx

import { useQuery } from '@tanstack/react-query'
import { useAuth } from '@clerk/clerk-react'
import { useApi, ApiError } from '../lib/api'
import { BurndownChart } from '../components/mirror/BurndownChart'
import { DeveloperCapacityRow } from '../components/mirror/DeveloperCapacityRow'
import { AlertFeed } from '../components/mirror/AlertFeed'
import { SprintHealthScore } from '../components/mirror/SprintHealthScore'

interface CurrentSprint {
  id: string
  name: string
  startDate: string
  endDate: string
  sprintLength: number
  totalPoints: number
}

export function VelocityMirrorPage() {
  const { get } = useApi()
  const { isLoaded, isSignedIn } = useAuth()

  const { data: sprint, isLoading, isError, error } = useQuery<CurrentSprint, ApiError>({
    queryKey: ['current-sprint'],
    queryFn: () => get<CurrentSprint>('/api/sprints/current'),
    enabled: isLoaded && isSignedIn,
  })

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
          <DeveloperCapacityRow />
        </div>

        {/* Right: alerts */}
        <div style={{ width: 300, flexShrink: 0 }}>
          <AlertFeed />
        </div>

      </div>
    </div>
  )
}
