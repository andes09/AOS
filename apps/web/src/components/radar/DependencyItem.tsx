// apps/web/src/components/radar/DependencyItem.tsx

import { useState } from 'react'
import { useApi } from '../../lib/api'
import type { DependencyItem as DependencyItemType } from '../../types/dependencyRadar'

const RISK_BADGE: Record<string, { bg: string; color: string; label: string }> = {
  high:   { bg: '#7f1d1d', color: '#fca5a5', label: 'High' },
  medium: { bg: '#78350f', color: '#fcd34d', label: 'Medium' },
  low:    { bg: '#14532d', color: '#86efac', label: 'Low' },
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

  const badge = RISK_BADGE[dep.riskLevel]

  return (
    <div style={{
      background: '#1e2030',
      borderRadius: 8,
      padding: '0.75rem 1rem',
      display: 'flex',
      alignItems: 'flex-start',
      gap: 12,
    }}>
      {/* Risk badge */}
      <span style={{
        background: badge.bg,
        color: badge.color,
        fontSize: 10,
        fontWeight: 700,
        padding: '2px 7px',
        borderRadius: 4,
        flexShrink: 0,
        marginTop: 2,
        textTransform: 'uppercase',
        letterSpacing: '0.04em',
      }}>
        {badge.label}
      </span>

      {/* Content */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <span style={{ color: '#e2e8f0', fontSize: 13, fontWeight: 600 }}>
            {dep.ticketKey}
          </span>
          <span style={{
            background: '#2d3148',
            color: '#94a3b8',
            fontSize: 10,
            fontWeight: 600,
            padding: '1px 6px',
            borderRadius: 4,
            textTransform: 'uppercase',
            letterSpacing: '0.04em',
          }}>
            {DEP_TYPE_LABEL[dep.dependencyType] ?? dep.dependencyType}
          </span>
        </div>
        <div style={{ color: '#94a3b8', fontSize: 12, marginTop: 2, lineHeight: 1.4 }}>
          {dep.ticketTitle}
        </div>
        {dep.description && (
          <div style={{ color: '#64748b', fontSize: 11, marginTop: 3, lineHeight: 1.4 }}>
            {dep.description}
          </div>
        )}
      </div>

      {/* Resolve button */}
      <button
        onClick={handleResolve}
        disabled={resolving}
        style={{
          background: resolving ? '#1e2030' : '#0f1117',
          border: '1px solid #334155',
          color: resolving ? '#475569' : '#94a3b8',
          borderRadius: 6,
          padding: '4px 10px',
          fontSize: 11,
          fontWeight: 600,
          cursor: resolving ? 'not-allowed' : 'pointer',
          flexShrink: 0,
          marginTop: 2,
        }}
      >
        {resolving ? '…' : 'Resolve'}
      </button>
    </div>
  )
}
