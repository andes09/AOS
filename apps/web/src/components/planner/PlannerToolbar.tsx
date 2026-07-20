import { CSSProperties } from 'react'
import { CalendarDays, ChevronLeft, ChevronRight, Columns3, List, Rows3 } from 'lucide-react'
import { Button } from '../ui/Button'
import { SegmentedControl, type SegmentedOption } from '../ui/SegmentedControl'
import { MONTHS } from '../../lib/date'

export type PlannerView = 'week' | 'day' | 'list' | 'board'

const VIEW_OPTIONS: readonly SegmentedOption<PlannerView>[] = [
  { value: 'week', label: 'Week view', icon: <CalendarDays size={13} /> },
  { value: 'day', label: 'Day view', icon: <Rows3 size={13} /> },
  { value: 'list', label: 'List view', icon: <List size={13} /> },
  { value: 'board', label: 'Board view', icon: <Columns3 size={13} /> },
]

interface PlannerToolbarProps {
  title: string
  rangeStart: Date
  rangeEnd: Date
  view: PlannerView
  onViewChange: (v: PlannerView) => void
  onPrev: () => void
  onNext: () => void
  onToday: () => void
  done: number
  total: number
  pct: number
  /** Hidden for list/board, which aren't anchored to a date range. */
  showDateNav: boolean
}

export function PlannerToolbar({
  title,
  rangeStart,
  rangeEnd,
  view,
  onViewChange,
  onPrev,
  onNext,
  onToday,
  done,
  total,
  pct,
  showDateNav,
}: PlannerToolbarProps) {
  const sameMonth = rangeStart.getMonth() === rangeEnd.getMonth()
  const range = sameMonth
    ? `${MONTHS[rangeStart.getMonth()]} ${rangeStart.getDate()} – ${rangeEnd.getDate()}`
    : `${MONTHS[rangeStart.getMonth()]} ${rangeStart.getDate()} – ${MONTHS[rangeEnd.getMonth()]} ${rangeEnd.getDate()}`

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)', marginBottom: 'var(--space-3)' }}>
      <div style={rowStyle}>
        <h1
          style={{
            margin: 0,
            fontSize: 'var(--text-xl)',
            fontWeight: 700,
            color: 'var(--color-text-primary)',
            minWidth: 0,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {title}
        </h1>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', flexShrink: 0 }}>
          <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-muted)', whiteSpace: 'nowrap' }}>
            {done}/{total} done
          </span>
          <div
            role="progressbar"
            aria-valuenow={pct}
            aria-valuemin={0}
            aria-valuemax={100}
            style={{ width: 110, height: 6, borderRadius: 999, background: 'var(--color-bg-tertiary)', overflow: 'hidden' }}
          >
            <div style={{ width: `${pct}%`, height: '100%', background: 'var(--color-success)', transition: 'width 0.2s' }} />
          </div>
        </div>
      </div>

      <div style={rowStyle}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
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
        <SegmentedControl
          ariaLabel="Calendar view"
          options={VIEW_OPTIONS}
          value={view}
          onChange={onViewChange}
          size="sm"
        />
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
