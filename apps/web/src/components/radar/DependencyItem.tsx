// apps/web/src/components/radar/DependencyItem.tsx

import { useState } from 'react'
import { useApi } from '../../lib/api'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { Card, CardBody } from '../ui/Card'
import type { BadgeVariant } from '../ui/Badge'
import type { DependencyItem as DependencyItemType } from '../../types/dependencyRadar'

const RISK_VARIANT: Record<string, BadgeVariant> = {
  high:   'danger',
  medium: 'warning',
  low:    'success',
}

const DEP_TYPE_LABEL: Record<string, string> = {
  blocks:           'Blocks',
  is_blocked_by:    'Blocked By',
  external_service: 'External Service',
  cross_team:       'Cross-Team',
}

interface Props {
  dep: DependencyItemType
  onResolve: (id: string) => void
}

export function DependencyItem({ dep, onResolve }: Props) {
  const { patch } = useApi()
  const [resolving, setResolving] = useState(false)

  async function handleResolve() {
    setResolving(true)
    try {
      await patch(`/api/dependency-radar/dependency/${dep.id}/resolve`)
      onResolve(dep.id)
    } catch {
      setResolving(false)
    }
  }

  return (
    <Card>
      <CardBody style={{ display: 'flex', alignItems: 'flex-start', gap: 12, padding: '10px 14px' }}>
        {/* Risk badge */}
        <Badge variant={RISK_VARIANT[dep.riskLevel] ?? 'default'} style={{ marginTop: 2, flexShrink: 0 }}>
          {dep.riskLevel.charAt(0).toUpperCase() + dep.riskLevel.slice(1)}
        </Badge>

        {/* Content */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 2 }}>
            <span style={{ color: 'var(--color-text-primary)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)', fontWeight: 600 }}>
              {dep.ticketKey}
            </span>
            <Badge variant="default">
              {DEP_TYPE_LABEL[dep.dependencyType] ?? dep.dependencyType}
            </Badge>
          </div>
          <div style={{ color: 'var(--color-text-secondary)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-xs)', lineHeight: 1.4 }}>
            {dep.ticketTitle}
          </div>
          {dep.description && (
            <div style={{ color: 'var(--color-text-muted)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-xs)', marginTop: 3, lineHeight: 1.4 }}>
              {dep.description}
            </div>
          )}
        </div>

        {/* Resolve button */}
        <Button
          size="sm"
          variant="ghost"
          onClick={handleResolve}
          disabled={resolving}
          style={{ flexShrink: 0, marginTop: 2 }}
        >
          {resolving ? '…' : 'Resolve'}
        </Button>
      </CardBody>
    </Card>
  )
}
