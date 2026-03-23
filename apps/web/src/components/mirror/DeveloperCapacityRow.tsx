// apps/web/src/components/mirror/DeveloperCapacityRow.tsx

import { useQuery } from '@tanstack/react-query'
import { useAuth } from '@clerk/clerk-react'
import { useApi, ApiError } from '../../lib/api'

export interface DeveloperCapacity {
  developerId: string
  name: string
  availableDays: number
  availabilityRatio: number
  committedPoints: number
  completedPoints: number
  isOverCapacity: boolean
}

interface SprintCapacityResponse {
  sprintId: string
  sprintLengthDays: number
  capacity: DeveloperCapacity[]
}

interface DeveloperCapacityRowProps {
  developers?: DeveloperCapacity[]
}

function utilisationColour(ratio: number): string {
  if (ratio <= 0.8) return '#4ade80'
  if (ratio <= 1.0) return '#fbbf24'
  return '#ef4444'
}

function DevCard({ dev }: { dev: DeveloperCapacity }) {
  const ratio = dev.availableDays > 0 ? dev.committedPoints / (dev.availableDays * 2) : 0
  const completeRatio = dev.committedPoints > 0 ? dev.completedPoints / dev.committedPoints : 0
  const barColour = utilisationColour(ratio)
  const utilPct = Math.round(ratio * 100)
  const avatarInitial = dev.name.charAt(0).toUpperCase()

  return (
    <div style={{
      background: '#1e2030',
      borderRadius: 8,
      padding: '0.875rem 1rem',
      minWidth: 160,
      flex: '0 0 auto',
      position: 'relative',
    }}>
      {dev.isOverCapacity && (
        <div style={{
          position: 'absolute',
          top: 6,
          right: 8,
          background: '#7f1d1d',
          color: '#fca5a5',
          fontSize: 10,
          fontWeight: 700,
          padding: '1px 6px',
          borderRadius: 4,
          letterSpacing: '0.04em',
        }}>
          OVER
        </div>
      )}

      {/* Avatar + name */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
        <div style={{
          width: 28,
          height: 28,
          borderRadius: '50%',
          background: '#6366f1',
          color: '#fff',
          fontSize: 12,
          fontWeight: 700,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          flexShrink: 0,
        }}>
          {avatarInitial}
        </div>
        <div style={{ color: '#e2e8f0', fontSize: 13, fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {dev.name}
        </div>
      </div>

      {/* Progress bar: completed / committed */}
      <div style={{ background: '#2d2f45', height: 6, borderRadius: 3, marginBottom: 6 }}>
        <div style={{
          width: `${Math.min(completeRatio * 100, 100)}%`,
          height: 6,
          borderRadius: 3,
          background: barColour,
          transition: 'width 0.4s ease',
        }} />
      </div>

      {/* Stats row */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <div style={{ color: '#64748b', fontSize: 11 }}>
          {dev.completedPoints}/{dev.committedPoints} pts
        </div>
        <div style={{ color: barColour, fontSize: 12, fontWeight: 700 }}>
          {utilPct}%
        </div>
      </div>
    </div>
  )
}

export function DeveloperCapacityRow({ developers }: DeveloperCapacityRowProps) {
  const { get } = useApi()
  const { isLoaded, isSignedIn } = useAuth()

  const query = useQuery<SprintCapacityResponse, ApiError>({
    queryKey: ['velocity-capacity'],
    queryFn: () => get<SprintCapacityResponse>('/api/velocity/capacity'),
    enabled: !developers && isLoaded && !!isSignedIn,
  })

  const devs = developers ?? query.data?.capacity ?? []

  if (!developers && query.isLoading) {
    return (
      <div style={{ background: '#1e2030', borderRadius: 8, padding: '0.875rem 1rem', color: '#64748b', fontSize: 13 }}>
        Loading capacity data…
      </div>
    )
  }

  if (!developers && query.isError) {
    const is404 = query.error instanceof ApiError && query.error.status === 404
    return (
      <div style={{ background: '#1e2030', borderRadius: 8, padding: '0.875rem 1rem', color: is404 ? '#475569' : '#ef4444', fontSize: 13 }}>
        {is404 ? 'No active sprint — capacity data unavailable' : 'Failed to load capacity data'}
      </div>
    )
  }

  return (
    <div>
      <div style={{ color: '#94a3b8', fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>
        Developer Capacity
      </div>
      <div style={{
        display: 'flex',
        gap: 10,
        overflowX: 'auto',
        paddingBottom: 4,
      }}>
        {devs.length === 0 ? (
          <div style={{ color: '#475569', fontSize: 13 }}>No capacity data available</div>
        ) : (
          devs.map(dev => <DevCard key={dev.developerId} dev={dev} />)
        )}
      </div>
    </div>
  )
}
