// apps/web/src/components/mirror/AlertFeed.tsx

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '@clerk/clerk-react'
import { useApi } from '../../lib/api'
import { Card, CardBody } from '../ui/Card'
import { Badge } from '../ui/Badge'
import type { BadgeVariant } from '../ui/Badge'

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

const ALERT_VARIANT: Record<AlertType, BadgeVariant> = {
  stalled_ticket: 'danger',
  over_capacity: 'warning',
  dependency_risk: 'warning',
  spillover_prediction: 'info',
}

const ALERT_LABELS: Record<AlertType, string> = {
  stalled_ticket: 'Stalled Ticket',
  over_capacity: 'Over Capacity',
  dependency_risk: 'Dependency Risk',
  spillover_prediction: 'Spillover Risk',
}

const ALERT_BORDER: Record<AlertType, string> = {
  stalled_ticket: 'var(--color-danger)',
  over_capacity: 'var(--color-warning)',
  dependency_risk: 'var(--color-warning)',
  spillover_prediction: 'var(--color-accent)',
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
    <Card
      style={{
        borderLeft: `3px solid ${ALERT_BORDER[alert.type]}`,
        opacity: alert.dismissed ? 0.3 : 1,
        transition: 'opacity 0.35s ease',
        pointerEvents: alert.dismissed ? 'none' : 'auto',
      }}
    >
      <CardBody style={{ padding: '10px 12px' }}>
        {/* Header row */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 6 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Badge variant={ALERT_VARIANT[alert.type]}>{ALERT_LABELS[alert.type]}</Badge>
          </div>
          <button
            onClick={() => onDismiss(alert.id)}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--color-text-muted)',
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

        <div style={{ color: 'var(--color-text-primary)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)', fontWeight: 600, marginBottom: 2, lineHeight: 1.3 }}>
          {alert.title}
        </div>
        <div style={{ color: 'var(--color-text-muted)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-xs)', marginBottom: 6 }}>
          {timeAgo(alert.createdAt)}
        </div>

        {/* Description */}
        <div style={{ color: 'var(--color-text-secondary)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-xs)', marginBottom: 8, lineHeight: 1.5 }}>
          {alert.description}
        </div>

        {/* Recommended action */}
        <div style={{
          background: 'var(--color-bg-secondary)',
          borderRadius: 'var(--radius-sm)',
          padding: '5px 8px',
          color: 'var(--color-accent)',
          fontFamily: 'var(--font-sans)',
          fontSize: 'var(--text-xs)',
          lineHeight: 1.5,
        }}>
          <span style={{ fontWeight: 700, marginRight: 4 }}>→</span>
          {alert.recommendedAction}
        </div>
      </CardBody>
    </Card>
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
    patch(`/api/alerts/${id}/dismiss`).catch(() => {
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
      <div style={{ color: 'var(--color-text-muted)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)', padding: '0.875rem 0' }}>
        Loading alerts…
      </div>
    )
  }

  if (isError) {
    return (
      <div style={{ color: 'var(--color-danger)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)', padding: '0.875rem 0' }}>
        Failed to load alerts
      </div>
    )
  }

  return (
    <div>
      <div style={{
        fontFamily: 'var(--font-sans)',
        color: 'var(--color-text-muted)',
        fontSize: 'var(--text-xs)',
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
          <Badge variant="danger">{visible.filter(a => !a.dismissed).length}</Badge>
        )}
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, overflowY: 'auto', maxHeight: 480 }}>
        {visible.length === 0 ? (
          <div style={{ color: 'var(--color-text-muted)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)' }}>
            No active alerts
          </div>
        ) : (
          visible.map(alert => (
            <AlertCard key={alert.id} alert={alert} onDismiss={handleDismiss} />
          ))
        )}
      </div>
    </div>
  )
}
