// The drift banner — the product's answer to "your roadmap went stale and
// nobody noticed". Renders nothing unless the server found a warning-level
// divergence between the plan and the repo, so it's inert for healthy projects
// and safe to mount unconditionally on the planner.
//
// Read-only on purpose: it reports and offers a human-triggered reconcile. The
// plan is never rewritten behind the user's back — a roadmap that silently
// edits itself is worse than one that's out of date, because you can no longer
// trust that what you read yesterday is what it says today.
//
// Dismissal is per-session (sessionStorage), not persisted: drift is a live
// condition, not a notification. If it's still true next time you open the
// app, you should still hear about it.

import { useState, type CSSProperties } from 'react'
import { GitBranch, X } from 'lucide-react'
import { Button } from '../ui/Button'
import { IconButton } from '../ui/IconButton'
import type { DriftReport, DriftSignal } from '../../pages/planner/useDriftSignal'

interface DriftBannerProps {
  report: DriftReport | undefined
  isLoading?: boolean
  /** Opens the plan map so the user can see which milestones are flagged. */
  onOpenPlanMap?: () => void
  onReconcile?: () => void
  isReconciling?: boolean
  reconcileError?: string | null
}

const dismissKey = (signals: DriftSignal[]) =>
  `omada.drift.dismissed.${signals.map(s => s.kind).sort().join('+')}`

const evidenceStyle: CSSProperties = {
  fontFamily: 'var(--font-mono, monospace)',
  fontSize: 'var(--text-xs)',
  color: 'var(--color-text-muted)',
  overflow: 'hidden',
  textOverflow: 'ellipsis',
  whiteSpace: 'nowrap',
}

export function DriftBanner({
  report,
  isLoading,
  onOpenPlanMap,
  onReconcile,
  isReconciling,
  reconcileError,
}: DriftBannerProps) {
  const [dismissed, setDismissed] = useState(false)

  const warnings = (report?.signals ?? []).filter(s => s.severity === 'warning')
  const info = (report?.signals ?? []).filter(s => s.severity === 'info')

  // Keyed by which signals are present, so resolving one kind of drift and
  // hitting another still surfaces — dismissing "stalled milestones" shouldn't
  // also silence "80% of your work is off-plan".
  const key = dismissKey(warnings)
  const alreadyDismissed =
    dismissed || (typeof sessionStorage !== 'undefined' && sessionStorage.getItem(key) === '1')

  if (isLoading || !report || !report.hasDrift || warnings.length === 0 || alreadyDismissed) {
    return null
  }

  const dismiss = () => {
    try {
      sessionStorage.setItem(key, '1')
    } catch {
      // Private browsing / storage disabled — the local state below still works
      // for this render, which is all dismissal needs to do.
    }
    setDismissed(true)
  }

  return (
    <section
      aria-label="Plan drift"
      style={{
        position: 'relative',
        display: 'flex',
        flexDirection: 'column',
        gap: 'var(--space-3)',
        padding: 'var(--space-4)',
        borderRadius: 'var(--radius-lg)',
        border: '1px solid var(--color-border)',
        borderLeft: '3px solid var(--color-warning)',
        background: 'var(--color-warning-bg)',
      }}
    >
      <div style={{ position: 'absolute', top: 'var(--space-2)', right: 'var(--space-2)' }}>
        <IconButton label="Dismiss" onClick={dismiss}>
          <X size={16} />
        </IconButton>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
        <GitBranch size={18} style={{ color: 'var(--color-warning)', flexShrink: 0 }} />
        <h2
          style={{
            margin: 0,
            fontSize: 'var(--text-lg)',
            fontWeight: 600,
            color: 'var(--color-text-primary)',
          }}
        >
          Your plan and your repo have drifted
        </h2>
      </div>

      <ul
        style={{
          listStyle: 'none',
          margin: 0,
          padding: 0,
          display: 'flex',
          flexDirection: 'column',
          gap: 'var(--space-3)',
        }}
      >
        {warnings.map(signal => (
          <li key={signal.kind} style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-1)' }}>
            <span style={{ fontSize: 'var(--text-sm)', fontWeight: 600, color: 'var(--color-text-primary)' }}>
              {signal.headline}
            </span>
            <span style={{ fontSize: 'var(--text-sm)', color: 'var(--color-text-secondary)' }}>
              {signal.detail}
            </span>
            {signal.evidence.length > 0 && (
              <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 2 }}>
                {signal.evidence.map(item => (
                  <li key={item} style={evidenceStyle}>
                    {item}
                  </li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ul>

      {info.length > 0 && (
        <p style={{ margin: 0, fontSize: 'var(--text-xs)', color: 'var(--color-text-muted)' }}>
          {info.map(s => s.headline).join(' · ')}
        </p>
      )}

      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
        {onReconcile && (
          <Button variant="primary" onClick={onReconcile} disabled={isReconciling}>
            {isReconciling ? 'Updating the plan…' : 'Update my plan to match'}
          </Button>
        )}
        {onOpenPlanMap && (
          <Button variant="ghost" onClick={onOpenPlanMap}>
            See the plan
          </Button>
        )}
      </div>

      <p style={{ margin: 0, fontSize: 'var(--text-xs)', color: 'var(--color-text-muted)' }}>
        Updating keeps everything you've finished or started — only untouched tasks are replanned.
      </p>

      {reconcileError && (
        <p style={{ margin: 0, fontSize: 'var(--text-xs)', color: 'var(--color-danger)' }}>{reconcileError}</p>
      )}
    </section>
  )
}
