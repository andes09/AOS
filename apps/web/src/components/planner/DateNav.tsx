import { CSSProperties } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { Button } from '../ui/Button'
import { MONTHS } from '../../lib/date'

interface DateNavProps {
  rangeStart: Date
  rangeEnd: Date
  onPrev: () => void
  onNext: () => void
  onToday: () => void
}

/**
 * Day/week navigation: a "Today" reset above the ‹ date › stepper. Lives inside
 * the planner sidebar so date controls and the people panel read as one rail.
 */
export function DateNav({ rangeStart, rangeEnd, onPrev, onNext, onToday }: DateNavProps) {
  const sameDay = rangeStart.toDateString() === rangeEnd.toDateString()
  const sameMonth = rangeStart.getMonth() === rangeEnd.getMonth()
  const range = sameDay
    ? `${MONTHS[rangeStart.getMonth()]} ${rangeStart.getDate()}`
    : sameMonth
      ? `${MONTHS[rangeStart.getMonth()]} ${rangeStart.getDate()} – ${rangeEnd.getDate()}`
      : `${MONTHS[rangeStart.getMonth()]} ${rangeStart.getDate()} – ${MONTHS[rangeEnd.getMonth()]} ${rangeEnd.getDate()}`

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
      <Button variant="ghost" size="sm" onClick={onToday}>
        Today
      </Button>
      <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
        <Button variant="ghost" size="sm" onClick={onPrev} aria-label="Previous">
          <ChevronLeft size={14} />
        </Button>
        <span
          style={{
            fontSize: 'var(--text-base)',
            fontWeight: 'var(--font-weight-semibold)' as CSSProperties['fontWeight'],
            color: 'var(--color-text-primary)',
            minWidth: 130,
            textAlign: 'center',
          }}
        >
          {range}
        </span>
        <Button variant="ghost" size="sm" onClick={onNext} aria-label="Next">
          <ChevronRight size={14} />
        </Button>
      </div>
    </div>
  )
}
