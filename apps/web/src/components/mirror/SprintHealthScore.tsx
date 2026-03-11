// apps/web/src/components/mirror/SprintHealthScore.tsx

import { useQuery } from '@tanstack/react-query'
import { useApi } from '../../lib/api'

interface HealthScoreResponse {
  score: number
  reasons: string[]
  updatedAt: string
}

interface SprintHealthScoreProps {
  sprintId?: string
}

function scoreColour(score: number): { fg: string; bg: string; ring: string } {
  if (score >= 70) return { fg: '#4ade80', bg: '#052e16', ring: '#16a34a' }
  if (score >= 40) return { fg: '#fbbf24', bg: '#1c1400', ring: '#d97706' }
  return { fg: '#f87171', bg: '#1c0505', ring: '#dc2626' }
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

  const { data, isLoading, isFetching, isError } = useQuery<HealthScoreResponse>({
    queryKey: ['sprint-health-score', sprintId],
    queryFn: () =>
      get<HealthScoreResponse>(
        sprintId ? `/api/velocity/health-score?sprintId=${sprintId}` : '/api/velocity/health-score'
      ),
    refetchInterval: 300_000,
  })

  if (isLoading) {
    return (
      <div style={{ background: '#1e2030', borderRadius: 8, padding: '1rem', minWidth: 160, textAlign: 'center' }}>
        <div style={{ color: '#64748b', fontSize: 13 }}>Loading…</div>
      </div>
    )
  }

  if (isError || !data) {
    return (
      <div style={{ background: '#1e2030', borderRadius: 8, padding: '1rem', minWidth: 160, textAlign: 'center' }}>
        <div style={{ color: '#ef4444', fontSize: 13 }}>Health score unavailable</div>
      </div>
    )
  }

  const { fg, bg, ring } = scoreColour(data.score)

  return (
    <div style={{
      background: '#1e2030',
      borderRadius: 8,
      padding: '1rem',
      minWidth: 160,
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      gap: 10,
    }}>
      <div style={{ color: '#94a3b8', fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', alignSelf: 'flex-start' }}>
        Sprint Health
      </div>

      {/* Score badge */}
      <div style={{
        width: 72,
        height: 72,
        borderRadius: '50%',
        background: bg,
        border: `3px solid ${ring}`,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        position: 'relative',
        // Pulse while refetching
        animation: isFetching ? 'pulse 1.5s ease-in-out infinite' : 'none',
      }}>
        <style>{`
          @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.55; }
          }
        `}</style>
        <span style={{ color: fg, fontSize: 26, fontWeight: 800, lineHeight: 1 }}>
          {data.score}
        </span>
      </div>

      {/* Reasons */}
      {data.reasons.length > 0 && (
        <ul style={{ margin: 0, padding: 0, listStyle: 'none', width: '100%', display: 'flex', flexDirection: 'column', gap: 4 }}>
          {data.reasons.slice(0, 3).map((reason, i) => (
            <li key={i} style={{ display: 'flex', gap: 6, alignItems: 'flex-start' }}>
              <span style={{ color: fg, fontSize: 10, marginTop: 2, flexShrink: 0 }}>•</span>
              <span style={{ color: '#94a3b8', fontSize: 11, lineHeight: 1.4 }}>{reason}</span>
            </li>
          ))}
        </ul>
      )}

      {/* Timestamp */}
      <div style={{ color: '#475569', fontSize: 10, alignSelf: 'flex-start' }}>
        Updated {timeAgo(data.updatedAt)}
      </div>
    </div>
  )
}
