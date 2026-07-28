import { ReactNode } from 'react'

interface PlannerToolbarProps {
  /** Left-aligned content — the date nav, when it isn't in the sidebar. */
  leftSlot?: ReactNode
  done: number
  total: number
  pct: number
}

/**
 * The thin row above the content: an optional left slot (the date nav lives in
 * the sidebar when it's open, here when it's collapsed) and the visible range's
 * completion on the right. The view switcher and panel toggle are in the top bar.
 */
export function PlannerToolbar({ leftSlot, done, total, pct }: PlannerToolbarProps) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-4)', marginBottom: 'var(--space-2)', flexWrap: 'wrap' }}>
      {leftSlot}

      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', flexShrink: 0, marginLeft: 'auto' }}>
        <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-muted)', whiteSpace: 'nowrap' }}>
          {done}/{total} done
        </span>
        <div
          role="progressbar"
          aria-valuenow={pct}
          aria-valuemin={0}
          aria-valuemax={100}
          style={{ width: 180, height: 8, borderRadius: 999, background: 'var(--color-bg-tertiary)', border: '1px solid var(--color-border)', overflow: 'hidden' }}
        >
          <div style={{ width: `${pct}%`, height: '100%', background: 'var(--color-success)', transition: 'width 0.2s' }} />
        </div>
      </div>
    </div>
  )
}
