// apps/web/src/components/retro/PatternFeed.tsx

import { useState } from 'react'
import { useApi } from '../../lib/api'
import type { RetroPattern } from '../../types/retro'

interface PatternFeedProps {
  patterns: RetroPattern[]
}

export function PatternFeed({ patterns: initialPatterns }: PatternFeedProps) {
  const { patch } = useApi()
  const [patterns, setPatterns] = useState<RetroPattern[]>(
    [...initialPatterns]
      .filter(p => p.status === 'active')
      .sort((a, b) => b.occurrenceCount - a.occurrenceCount)
  )
  const [resolving, setResolving] = useState<Set<string>>(new Set())

  async function handleResolve(id: string) {
    setResolving(prev => new Set(prev).add(id))
    // Optimistic removal
    setPatterns(prev => prev.filter(p => p.id !== id))
    try {
      await patch(`/api/retro/pattern/${id}/resolve`, {})
    } catch {
      // On failure, restore the pattern
      setPatterns(prev => {
        const restored = initialPatterns.find(p => p.id === id)
        if (!restored) return prev
        return [...prev, restored].sort((a, b) => b.occurrenceCount - a.occurrenceCount)
      })
    } finally {
      setResolving(prev => { const s = new Set(prev); s.delete(id); return s })
    }
  }

  if (patterns.length === 0) {
    return (
      <div style={{
        background: '#1e2330',
        borderLeft: '4px solid #475569',
        borderRadius: 8,
        padding: '1rem 1.25rem',
      }}>
        <div style={{ color: '#94a3b8', fontSize: 13, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>
          Recurring Patterns
        </div>
        <div style={{ color: '#475569', fontSize: 13, fontStyle: 'italic' }}>No active patterns detected</div>
      </div>
    )
  }

  return (
    <div style={{
      background: '#1e2330',
      borderLeft: '4px solid #8b5cf6',
      borderRadius: 8,
      padding: '1rem 1.25rem',
    }}>
      <div style={{ color: '#c4b5fd', fontSize: 13, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 12 }}>
        Recurring Patterns
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {patterns.map(p => (
          <div key={p.id} style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
            <span style={{
              background: '#312e81',
              color: '#a5b4fc',
              fontSize: 11,
              fontWeight: 700,
              borderRadius: 4,
              padding: '2px 7px',
              flexShrink: 0,
              marginTop: 2,
            }}>
              {p.patternType}
            </span>
            <span style={{ color: '#cbd5e1', fontSize: 14, lineHeight: 1.5, flex: 1 }}>
              {p.description}
            </span>
            <span style={{
              background: '#1e293b',
              color: '#94a3b8',
              fontSize: 12,
              fontWeight: 700,
              borderRadius: 999,
              padding: '2px 8px',
              flexShrink: 0,
              marginTop: 2,
            }}>
              ×{p.occurrenceCount}
            </span>
            <button
              onClick={() => handleResolve(p.id)}
              disabled={resolving.has(p.id)}
              style={{
                background: 'transparent',
                border: '1px solid #475569',
                borderRadius: 5,
                color: '#94a3b8',
                fontSize: 12,
                padding: '2px 10px',
                cursor: resolving.has(p.id) ? 'default' : 'pointer',
                flexShrink: 0,
                marginTop: 2,
                opacity: resolving.has(p.id) ? 0.5 : 1,
              }}
            >
              Resolve
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}
