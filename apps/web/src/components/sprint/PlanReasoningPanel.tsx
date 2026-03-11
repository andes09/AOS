import { useState } from 'react'
import type { Assignment } from '../../types/sprint'

interface PlanReasoningPanelProps {
  assignments: Assignment[]
}

function dotColour(c: number): string {
  if (c > 0.75) return '#4ade80'
  if (c >= 0.5) return '#fbbf24'
  return '#ef4444'
}

export function PlanReasoningPanel({ assignments }: PlanReasoningPanelProps) {
  const [openId, setOpenId] = useState<string | null>(null)

  if (assignments.length === 0) {
    return (
      <div style={{ color: '#64748b', fontSize: 13, padding: '1rem 0' }}>
        Generate a plan to see assignment reasoning.
      </div>
    )
  }

  return (
    <div>
      <div style={{
        color: '#a5b4fc',
        fontSize: 11,
        fontWeight: 700,
        textTransform: 'uppercase',
        letterSpacing: '0.06em',
        marginBottom: 10,
      }}>
        Why this assignment?
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        {assignments.map(a => {
          const isOpen = openId === a.ticket_id
          return (
            <div key={a.ticket_id} style={{ background: '#0f1117', borderRadius: 6, overflow: 'hidden' }}>
              <button
                onClick={() => setOpenId(isOpen ? null : a.ticket_id)}
                style={{
                  width: '100%',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  padding: '0.625rem 0.75rem',
                  background: 'transparent',
                  border: 'none',
                  cursor: 'pointer',
                  textAlign: 'left',
                }}
              >
                <span style={{ color: '#6366f1', fontSize: 12, fontWeight: 700, whiteSpace: 'nowrap' }}>
                  {a.ticket_id}
                </span>
                <span style={{
                  color: '#94a3b8',
                  fontSize: 12,
                  flex: 1,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}>
                  → {a.developer_id}
                </span>
                <span style={{ color: '#64748b', fontSize: 11, whiteSpace: 'nowrap' }}>
                  {a.story_points}pts
                </span>
                <span style={{
                  width: 8,
                  height: 8,
                  borderRadius: '50%',
                  background: dotColour(a.confidence),
                  flexShrink: 0,
                }} />
                <span style={{ color: '#64748b', fontSize: 10 }}>{isOpen ? '▲' : '▼'}</span>
              </button>

              {isOpen && (
                <div style={{
                  padding: '0.5rem 0.75rem 0.75rem',
                  color: '#94a3b8',
                  fontSize: 13,
                  lineHeight: 1.6,
                  borderTop: '1px solid #2d2f45',
                }}>
                  {a.reasoning}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
