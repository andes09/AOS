// apps/web/src/components/mirror/SprintHealthScore.tsx

import { useQuery } from '@tanstack/react-query'
import { useAuth } from '@clerk/clerk-react'
import { useApi, ApiError } from '../../lib/api'
import { Card, CardBody } from '../ui/Card'

interface HealthScoreResponse {
  score: number
  reasons: string[]
  updatedAt: string
}

interface SprintHealthScoreProps {
  sprintId?: string
}

function scoreColour(score: number): { fg: string; ring: string } {
  if (score >= 70) return { fg: 'var(--color-success)', ring: 'var(--color-success)' }
  if (score >= 40) return { fg: 'var(--color-warning)', ring: 'var(--color-warning)' }
  return { fg: 'var(--color-danger)', ring: 'var(--color-danger)' }
}

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins === 1) return '1 min ago'
  if (mins < 60) return `${mins} min ago`
  const hrs = Math.floor(mins / 60)
  return `${hrs}h ago`
}

export function SprintHealthScore({ sprintId }: SprintHealthScoreProps) {
  const { get } = useApi()
  const { isLoaded, isSignedIn } = useAuth()

  const { data, isLoading, isFetching, isError, error } = useQuery<HealthScoreResponse>({
    queryKey: ['sprint-health-score', sprintId],
    queryFn: () =>
      get<HealthScoreResponse>(
        sprintId ? `/api/velocity/health-score?sprintId=${sprintId}` : '/api/velocity/health-score'
      ),
    enabled: isLoaded && isSignedIn,
    refetchInterval: 300_000,
  })

  if (isLoading) {
    return (
      <Card style={{ minWidth: 160, textAlign: 'center' }}>
        <CardBody>
          <div style={{ color: 'var(--color-text-muted)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)' }}>Loading…</div>
        </CardBody>
      </Card>
    )
  }

  if (isError || !data) {
    const is404 = error instanceof ApiError && error.status === 404
    return (
      <Card style={{ minWidth: 160, textAlign: 'center' }}>
        <CardBody>
          <div style={{ color: is404 ? 'var(--color-text-muted)' : 'var(--color-danger)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)' }}>
            {is404 ? 'No active sprint' : 'Health score unavailable'}
          </div>
        </CardBody>
      </Card>
    )
  }

  const { fg, ring } = scoreColour(data.score)

  return (
    <Card style={{ minWidth: 160 }}>
      <CardBody style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10 }}>
        <div style={{
          fontFamily: 'var(--font-sans)',
          color: 'var(--color-text-muted)',
          fontSize: 'var(--text-xs)',
          fontWeight: 700,
          textTransform: 'uppercase',
          letterSpacing: '0.06em',
          alignSelf: 'flex-start',
        }}>
          Sprint Health
        </div>

        {/* Score badge */}
        <div style={{
          width: 72,
          height: 72,
          borderRadius: '50%',
          background: 'var(--color-bg-secondary)',
          border: `3px solid ${ring}`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          animation: isFetching ? 'pulse 1.5s ease-in-out infinite' : 'none',
        }}>
          <style>{`
            @keyframes pulse {
              0%, 100% { opacity: 1; }
              50% { opacity: 0.55; }
            }
          `}</style>
          <span style={{ color: fg, fontFamily: 'var(--font-sans)', fontSize: 26, fontWeight: 800, lineHeight: 1 }}>
            {data.score}
          </span>
        </div>

        {/* Reasons */}
        {data.reasons.length > 0 && (
          <ul style={{ margin: 0, padding: 0, listStyle: 'none', width: '100%', display: 'flex', flexDirection: 'column', gap: 4 }}>
            {data.reasons.slice(0, 3).map((reason, i) => (
              <li key={i} style={{ display: 'flex', gap: 6, alignItems: 'flex-start' }}>
                <span style={{ color: fg, fontSize: 'var(--text-xs)', marginTop: 2, flexShrink: 0 }}>•</span>
                <span style={{ color: 'var(--color-text-secondary)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-xs)', lineHeight: 1.4 }}>{reason}</span>
              </li>
            ))}
          </ul>
        )}

        <div style={{ color: 'var(--color-text-muted)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-xs)', alignSelf: 'flex-start' }}>
          Updated {timeAgo(data.updatedAt)}
        </div>
      </CardBody>
    </Card>
  )
}
