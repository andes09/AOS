// apps/web/src/components/retro/PatternFeed.tsx

import { useState } from 'react'
import { useApi } from '../../lib/api'
import { Card, CardBody } from '../ui/Card'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
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
    setPatterns(prev => prev.filter(p => p.id !== id))
    try {
      await patch(`/api/retro/pattern/${id}/resolve`, {})
    } catch {
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
      <Card style={{ borderLeft: '4px solid var(--color-border)' }}>
        <CardBody style={{ padding: '14px 18px' }}>
          <div style={{
            color: 'var(--color-text-muted)',
            fontFamily: 'var(--font-sans)',
            fontSize: 'var(--text-xs)',
            fontWeight: 700,
            textTransform: 'uppercase',
            letterSpacing: '0.06em',
            marginBottom: 8,
          }}>
            Recurring Patterns
          </div>
          <div style={{ color: 'var(--color-text-muted)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)', fontStyle: 'italic' }}>
            No active patterns detected
          </div>
        </CardBody>
      </Card>
    )
  }

  return (
    <Card style={{ borderLeft: '4px solid var(--color-accent)' }}>
      <CardBody style={{ padding: '14px 18px' }}>
        <div style={{
          color: 'var(--color-accent)',
          fontFamily: 'var(--font-sans)',
          fontSize: 'var(--text-xs)',
          fontWeight: 700,
          textTransform: 'uppercase',
          letterSpacing: '0.06em',
          marginBottom: 12,
        }}>
          Recurring Patterns
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {patterns.map(p => (
            <div key={p.id} style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
              <Badge variant="info" style={{ marginTop: 2, flexShrink: 0 }}>
                {p.patternType}
              </Badge>
              <span style={{ color: 'var(--color-text-primary)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-base)', lineHeight: 1.5, flex: 1 }}>
                {p.description}
              </span>
              <Badge variant="default" style={{ marginTop: 2, flexShrink: 0 }}>
                ×{p.occurrenceCount}
              </Badge>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => handleResolve(p.id)}
                disabled={resolving.has(p.id)}
                style={{ marginTop: 2, flexShrink: 0 }}
              >
                Resolve
              </Button>
            </div>
          ))}
        </div>
      </CardBody>
    </Card>
  )
}
