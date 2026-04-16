import { useState } from 'react'
import type { Assignment } from '../../types/sprint'

interface PlanReasoningPanelProps {
  assignments: Assignment[]
}

function confidenceDot(c: number): string {
  if (c > 0.75) return 'var(--color-success)'
  if (c >= 0.5) return 'var(--color-warning)'
  return 'var(--color-danger)'
}

export function PlanReasoningPanel({ assignments }: PlanReasoningPanelProps) {
  const [openId, setOpenId] = useState<string | null>(null)

  if (assignments.length === 0) {
    return (
      <div style={{ color: 'var(--color-text-muted)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)', padding: '1rem 0' }}>
        Generate a plan to see assignment reasoning.
      </div>
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
        marginBottom: 10,
      }}>
        Why this assignment?
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        {assignments.map(a => {
          const isOpen = openId === a.ticket_id
          return (
            <div
              key={a.ticket_id}
              style={{
                background: 'var(--color-bg-secondary)',
                border: '1px solid var(--color-border)',
                borderRadius: 'var(--radius-md)',
                overflow: 'hidden',
              }}
            >
              <button
                onClick={() => setOpenId(isOpen ? null : a.ticket_id)}
                style={{
                  width: '100%',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  padding: '8px 10px',
                  background: 'transparent',
                  border: 'none',
                  cursor: 'pointer',
                  textAlign: 'left',
                }}
              >
                <span style={{ color: 'var(--color-accent)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-xs)', fontWeight: 700, whiteSpace: 'nowrap' }}>
                  {a.ticket_id}
                </span>
                <span style={{
                  color: 'var(--color-text-secondary)',
                  fontFamily: 'var(--font-sans)',
                  fontSize: 'var(--text-xs)',
                  flex: 1,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}>
                  → {a.developer_name || a.developer_id}
                </span>
                <span style={{ color: 'var(--color-text-muted)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-xs)', whiteSpace: 'nowrap' }}>
                  {a.story_points}pts
                </span>
                <span style={{ width: 8, height: 8, borderRadius: '50%', background: confidenceDot(a.confidence), flexShrink: 0 }} />
                <span style={{ color: 'var(--color-text-muted)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-xs)' }}>
                  {isOpen ? '▲' : '▼'}
                </span>
              </button>

              {isOpen && (
                <div style={{
                  padding: '8px 10px 10px',
                  color: 'var(--color-text-secondary)',
                  fontFamily: 'var(--font-sans)',
                  fontSize: 'var(--text-sm)',
                  lineHeight: 1.6,
                  borderTop: '1px solid var(--color-border-subtle)',
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
