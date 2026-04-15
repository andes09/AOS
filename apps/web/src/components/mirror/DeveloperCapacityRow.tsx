// apps/web/src/components/mirror/DeveloperCapacityRow.tsx

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '@clerk/clerk-react'
import { useApi, ApiError } from '../../lib/api'
import { DeveloperProfileModal } from './DeveloperProfileModal'
import { Card, CardBody } from '../ui/Card'
import { Badge } from '../ui/Badge'

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
  teamId?: string
}

interface DevCardProps {
  dev: DeveloperCapacity
  onClick: () => void
}

function utilisationColour(ratio: number): string {
  if (ratio <= 0.8) return 'var(--color-success)'
  if (ratio <= 1.0) return 'var(--color-warning)'
  return 'var(--color-danger)'
}

function DevCard({ dev, onClick }: DevCardProps) {
  const ratio = dev.availableDays > 0 ? dev.committedPoints / (dev.availableDays * 2) : 0
  const completeRatio = dev.committedPoints > 0 ? dev.completedPoints / dev.committedPoints : 0
  const barColour = utilisationColour(ratio)
  const utilPct = Math.round(ratio * 100)
  const avatarInitial = dev.name.charAt(0).toUpperCase()

  return (
    <Card
      onClick={onClick}
      style={{ minWidth: 160, flex: '0 0 auto', position: 'relative', cursor: 'pointer' }}
    >
      <CardBody>
        {dev.isOverCapacity && (
          <div style={{ position: 'absolute', top: 6, right: 8 }}>
            <Badge variant="danger">OVER</Badge>
          </div>
        )}

        {/* Avatar + name */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
          <div style={{
            width: 28,
            height: 28,
            borderRadius: '50%',
            background: 'var(--color-accent)',
            color: '#ffffff',
            fontFamily: 'var(--font-sans)',
            fontSize: 'var(--text-xs)',
            fontWeight: 700,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            flexShrink: 0,
          }}>
            {avatarInitial}
          </div>
          <div style={{
            color: 'var(--color-text-primary)',
            fontFamily: 'var(--font-sans)',
            fontSize: 'var(--text-sm)',
            fontWeight: 600,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}>
            {dev.name}
          </div>
        </div>

        {/* Progress bar: completed / committed */}
        <div style={{ background: 'var(--color-border)', height: 6, borderRadius: 3, marginBottom: 6 }}>
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
          <div style={{ color: 'var(--color-text-muted)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-xs)' }}>
            {dev.completedPoints}/{dev.committedPoints} pts
          </div>
          <div style={{ color: barColour, fontFamily: 'var(--font-sans)', fontSize: 'var(--text-xs)', fontWeight: 700 }}>
            {utilPct}%
          </div>
        </div>
      </CardBody>
    </Card>
  )
}

export function DeveloperCapacityRow({ developers, teamId }: DeveloperCapacityRowProps) {
  const { get } = useApi()
  const { isLoaded, isSignedIn } = useAuth()
  const [selectedDeveloperId, setSelectedDeveloperId] = useState<string | null>(null)

  const teamParam = teamId && teamId !== 'default' ? `?team_id=${teamId}` : ''
  const query = useQuery<SprintCapacityResponse, ApiError>({
    queryKey: ['velocity-capacity', teamId],
    queryFn: () => get<SprintCapacityResponse>(`/api/velocity/capacity${teamParam}`),
    enabled: !developers && isLoaded && !!isSignedIn,
  })

  const devs = developers ?? query.data?.capacity ?? []

  if (!developers && query.isLoading) {
    return (
      <Card>
        <CardBody style={{ color: 'var(--color-text-muted)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)' }}>
          Loading capacity data…
        </CardBody>
      </Card>
    )
  }

  if (!developers && query.isError) {
    const is404 = query.error instanceof ApiError && query.error.status === 404
    return (
      <Card>
        <CardBody style={{ color: is404 ? 'var(--color-text-muted)' : 'var(--color-danger)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)' }}>
          {is404 ? 'No active sprint — capacity data unavailable' : 'Failed to load capacity data'}
        </CardBody>
      </Card>
    )
  }

  return (
    <div>
      <div style={{
        color: 'var(--color-text-muted)',
        fontFamily: 'var(--font-sans)',
        fontSize: 'var(--text-xs)',
        fontWeight: 700,
        textTransform: 'uppercase',
        letterSpacing: '0.06em',
        marginBottom: 8,
      }}>
        Developer Capacity
      </div>
      <div style={{ display: 'flex', gap: 10, overflowX: 'auto', paddingBottom: 4 }}>
        {devs.length === 0 ? (
          <div style={{ color: 'var(--color-text-muted)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)' }}>
            No capacity data available
          </div>
        ) : (
          devs.map(dev => (
            <DevCard key={dev.developerId} dev={dev} onClick={() => setSelectedDeveloperId(dev.developerId)} />
          ))
        )}
      </div>
      {selectedDeveloperId && (
        <DeveloperProfileModal
          developerId={selectedDeveloperId}
          onClose={() => setSelectedDeveloperId(null)}
        />
      )}
    </div>
  )
}
