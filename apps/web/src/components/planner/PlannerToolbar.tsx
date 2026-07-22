import { CSSProperties } from 'react'
import { ChevronLeft, ChevronRight, PanelLeftClose, PanelLeftOpen } from 'lucide-react'
import { Button } from '../ui/Button'
import { IconButton } from '../ui/IconButton'
import { MONTHS } from '../../lib/date'

interface PlannerToolbarProps {
  rangeStart: Date
  rangeEnd: Date
  onPrev: () => void
  onNext: () => void
  onToday: () => void
  done: number
  total: number
  pct: number
  /** Hidden for list/board, which aren't anchored to a date range. */
  showDateNav: boolean
  lanesCollapsed: boolean
  onToggleLanes: () => void
}

/**
 * The row above the calendar: a toggle for the member-lane panel, date
 * navigation, and progress. The view switcher lives in the top bar now.
 */
export function PlannerToolbar({
  rangeStart,
  rangeEnd,
  onPrev,
  onNext,
  onToday,
  done,
  total,
  pct,
  showDateNav,
  lanesCollapsed,
  onToggleLanes,
}: PlannerToolbarProps) {
  const sameMonth = rangeStart.getMonth() === rangeEnd.getMonth()
  const range = sameMonth
    ? `${MONTHS[rangeStart.getMonth()]} ${rangeStart.getDate()} – ${rangeEnd.getDate()}`
    : `${MONTHS[rangeStart.getMonth()]} ${rangeStart.getDate()} – ${MONTHS[rangeEnd.getMonth()]} ${rangeEnd.getDate()}`

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)', marginBottom: 'var(--space-3)' }}>
      <div style={rowStyle}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', flexShrink: 0, marginRight: 'auto' }}>
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

      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
        <IconButton
          label={lanesCollapsed ? 'Show people panel' : 'Hide people panel'}
          onClick={onToggleLanes}
          style={{ color: 'var(--color-text-secondary)' }}
        >
          {lanesCollapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
        </IconButton>

        {showDateNav && (
          <>
            <Button variant="ghost" size="sm" onClick={onPrev} aria-label="Previous">
              <ChevronLeft size={15} />
            </Button>
            <span
              style={{
                fontSize: 'var(--text-sm)',
                fontWeight: 'var(--font-weight-medium)' as CSSProperties['fontWeight'],
                color: 'var(--color-text-primary)',
                minWidth: 150,
                textAlign: 'center',
              }}
            >
              {range}
            </span>
            <Button variant="ghost" size="sm" onClick={onNext} aria-label="Next">
              <ChevronRight size={15} />
            </Button>
            <Button variant="ghost" size="sm" onClick={onToday}>
              Today
            </Button>
          </>
        )}
      </div>
    </div>
  )
}

const rowStyle: CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  gap: 'var(--space-4)',
  flexWrap: 'wrap',
}
