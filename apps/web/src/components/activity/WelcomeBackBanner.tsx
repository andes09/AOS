// The anti-dormancy "welcome back" banner. Renders nothing unless the user has
// been away long enough (server decides via ActivitySummary.isReturning) — so
// it's inert for active users and safe to mount unconditionally on the landing
// surface. Shows how long they were gone, what changed while away, and a capped
// next-step list (the direct antidote to "I opened my plan and felt buried").
// See docs/plans/2026-07-20-anti-dormancy-mvp.md.

import { useState, type CSSProperties } from 'react'
import { Sparkles, X, Circle } from 'lucide-react'
import { IconButton } from '../ui/IconButton'
import { parseISO, MONTHS } from '../../lib/date'
import { useActivitySummary } from '../../features/activity'

function daysAwayLabel(days: number | null): string {
  if (days === null) return ''
  if (days === 1) return 'a day'
  if (days < 7) return `${days} days`
  if (days < 14) return 'a week'
  return `${Math.floor(days / 7)} weeks`
}

function schedLabel(iso: string | null): string | null {
  if (!iso) return null
  const d = parseISO(iso)
  return `${MONTHS[d.getMonth()]} ${d.getDate()}`
}

const chipStyle: CSSProperties = {
  fontFamily: 'var(--font-mono, monospace)',
  fontSize: 'var(--text-xs)',
  color: 'var(--color-text-muted)',
}

export function WelcomeBackBanner() {
  const { data, isLoading } = useActivitySummary()
  const [dismissed, setDismissed] = useState(false)

  if (isLoading || !data || !data.isReturning || dismissed) return null

  const { daysSinceLastActive, tasksCompletedSinceLastVisit, tasksRemaining, overdueCount, nextUp } = data

  // "What changed / where you stand" — only the parts that are non-zero, so the
  // line stays honest and short.
  const facts: string[] = []
  if (tasksCompletedSinceLastVisit > 0) {
    facts.push(`${tasksCompletedSinceLastVisit} task${tasksCompletedSinceLastVisit === 1 ? '' : 's'} completed while you were away`)
  }
  facts.push(`${tasksRemaining} remaining`)
  if (overdueCount > 0) facts.push(`${overdueCount} overdue`)

  return (
    <section
      aria-label="Welcome back"
      style={{
        position: 'relative',
        display: 'flex',
        flexDirection: 'column',
        gap: 'var(--space-3)',
        padding: 'var(--space-4)',
        borderRadius: 'var(--radius-lg)',
        border: '1px solid var(--color-border)',
        borderLeft: '3px solid var(--color-accent)',
        background: 'var(--color-accent-subtle)',
      }}
    >
      <div style={{ position: 'absolute', top: 'var(--space-2)', right: 'var(--space-2)' }}>
        <IconButton label="Dismiss" onClick={() => setDismissed(true)}>
          <X size={16} />
        </IconButton>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
        <Sparkles size={18} style={{ color: 'var(--color-accent)', flexShrink: 0 }} />
        <h2 style={{ margin: 0, fontSize: 'var(--text-lg)', fontWeight: 600, color: 'var(--color-text-primary)' }}>
          Welcome back{daysSinceLastActive ? ` — it's been ${daysAwayLabel(daysSinceLastActive)}` : ''}
        </h2>
      </div>

      <p style={{ margin: 0, fontSize: 'var(--text-sm)', color: 'var(--color-text-secondary)' }}>
        {facts.join(' · ')}
      </p>

      {nextUp.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
          <span
            style={{
              fontSize: 'var(--text-xs)',
              fontWeight: 600,
              textTransform: 'uppercase',
              letterSpacing: '0.04em',
              color: 'var(--color-text-muted)',
            }}
          >
            Pick up where you left off
          </span>
          <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 'var(--space-1)' }}>
            {nextUp.map(task => {
              const when = schedLabel(task.scheduledDate)
              return (
                <li key={task.id} style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', fontSize: 'var(--text-sm)' }}>
                  <Circle size={7} style={{ color: 'var(--color-accent)', flexShrink: 0 }} fill="var(--color-accent)" />
                  <span style={{ color: 'var(--color-text-primary)' }}>{task.title}</span>
                  {task.shortId && <span style={chipStyle}>{task.shortId}</span>}
                  {when && <span style={{ ...chipStyle, marginLeft: 'auto' }}>{when}</span>}
                </li>
              )
            })}
          </ul>
        </div>
      )}
    </section>
  )
}
