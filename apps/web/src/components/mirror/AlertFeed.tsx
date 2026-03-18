// apps/web/src/components/mirror/AlertFeed.tsx

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '@clerk/clerk-react'
import { useApi } from '../../lib/api'

export type AlertType = 'stalled_ticket' | 'over_capacity' | 'dependency_risk' | 'spillover_prediction'

export interface Alert {
  id: string
  type: AlertType
  title: string
  description: string
  recommendedAction: string
  createdAt: string
  dismissed: boolean
}

const ALERT_ICONS: Record<AlertType, string> = {
  stalled_ticket: '🔴',
  over_capacity: '🟡',
  dependency_risk: '🟠',
  spillover_prediction: '🔵',
}

const ALERT_LABELS: Record<AlertType, string> = {
  stalled_ticket: 'Stalled Ticket',
  over_capacity: 'Over Capacity',
  dependency_risk: 'Dependency Risk',
  spillover_prediction: 'Spillover Risk',
}

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}

function AlertCard({
  alert,
  onDismiss,
}: {
  alert: Alert
  onDismiss: (id: string) => void
}) {
  return (
    <div style={{
      background: '#1e2030',
      borderRadius: 8,
      padding: '0.875rem 1rem',
      opacity: alert.dismissed ? 0.3 : 1,
      transition: 'opacity 0.35s ease',
      pointerEvents: alert.dismissed ? 'none' : 'auto',
    }}>
      {/* Header row */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 6 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 16 }}>{ALERT_ICONS[alert.type]}</span>
          <div>
            <div style={{ color: '#e2e8f0', fontSize: 13, fontWeight: 600, lineHeight: 1.3 }}>
              {alert.title}
            </div>
            <div style={{ color: '#64748b', fontSize: 10, marginTop: 1 }}>
              {ALERT_LABELS[alert.type]} · {timeAgo(alert.createdAt)}
            </div>
          </div>
        </div>
        <button
          onClick={() => onDismiss(alert.id)}
          style={{
            background: 'transparent',
            border: 'none',
            color: '#475569',
            cursor: 'pointer',
            fontSize: 16,
            lineHeight: 1,
            padding: '0 0 0 8px',
            flexShrink: 0,
          }}
          title="Dismiss"
        >
          ×
        </button>
      </div>

      {/* Description */}
      <div style={{ color: '#94a3b8', fontSize: 12, marginBottom: 8, lineHeight: 1.5 }}>
        {alert.description}
      </div>

      {/* Recommended action */}
      <div style={{
        background: '#0f1117',
        borderRadius: 6,
        padding: '0.5rem 0.75rem',
        color: '#a5b4fc',
        fontSize: 11,
        lineHeight: 1.5,
      }}>
        <span style={{ fontWeight: 700, marginRight: 4 }}>→</span>
        {alert.recommendedAction}
      </div>
    </div>
  )
}

export function AlertFeed() {
  const { get, patch } = useApi()
  const { isLoaded, isSignedIn } = useAuth()
  const [dismissedIds, setDismissedIds] = useState<Set<string>>(new Set())

  const { data: alerts = [], isLoading, isError } = useQuery<Alert[]>({
    queryKey: ['alerts'],
    queryFn: () => get<Alert[]>('/api/alerts'),
    enabled: isLoaded && isSignedIn,
  })

  function handleDismiss(id: string) {
    setDismissedIds(prev => new Set([...prev, id]))
    // Fire-and-forget — optimistic dismiss
    patch(`/api/alerts/${id}/dismiss`).catch(() => {
      // Roll back if the call fails
      setDismissedIds(prev => {
        const next = new Set(prev)
        next.delete(id)
        return next
      })
    })
  }

  const visible = alerts.map(a => ({
    ...a,
    dismissed: a.dismissed || dismissedIds.has(a.id),
  }))

  if (isLoading) {
    return (
      <div style={{ color: '#64748b', fontSize: 13, padding: '0.875rem 0' }}>
        Loading alerts…
      </div>
    )
  }

  if (isError) {
    return (
      <div style={{ color: '#ef4444', fontSize: 13, padding: '0.875rem 0' }}>
        Failed to load alerts
      </div>
    )
  }

  return (
    <div>
      <div style={{
        color: '#94a3b8',
        fontSize: 11,
        fontWeight: 700,
        textTransform: 'uppercase',
        letterSpacing: '0.06em',
        marginBottom: 10,
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
      }}>
        <span>Alerts</span>
        {visible.filter(a => !a.dismissed).length > 0 && (
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
            {visible.filter(a => !a.dismissed).length}
          </span>
        )}
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, overflowY: 'auto', maxHeight: 480 }}>
        {visible.length === 0 ? (
          <div style={{ color: '#475569', fontSize: 13 }}>No active alerts</div>
        ) : (
          visible.map(alert => (
            <AlertCard key={alert.id} alert={alert} onDismiss={handleDismiss} />
          ))
        )}
      </div>
    </div>
  )
}
