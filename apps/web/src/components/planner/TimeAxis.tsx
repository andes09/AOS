import { CSSProperties } from 'react'
import { PX_PER_MINUTE } from '../../pages/planner/taskLayout'

interface TimeAxisProps {
  startHour: number
  endHour: number
  /** Width of the gutter. Day columns align to this. */
  width?: number
}

function hourLabel(h: number): string {
  if (h === 0 || h === 24) return '12am'
  if (h === 12) return '12pm'
  return h < 12 ? `${h}am` : `${h - 12}pm`
}

/** The hour gutter down the left of the timed grid. */
export function TimeAxis({ startHour, endHour, width = 46 }: TimeAxisProps) {
  const hours = Array.from({ length: endHour - startHour + 1 }, (_, i) => startHour + i)

  return (
    <div style={{ width, flexShrink: 0, position: 'relative' }} aria-hidden="true">
      {hours.map(h => (
        <div
          key={h}
          style={{
            position: 'absolute',
            top: (h - startHour) * 60 * PX_PER_MINUTE,
            right: 6,
            transform: 'translateY(-50%)',
            fontSize: 10,
            color: 'var(--color-text-muted)',
            fontVariantNumeric: 'tabular-nums',
            whiteSpace: 'nowrap',
          }}
        >
          {hourLabel(h)}
        </div>
      ))}
    </div>
  )
}

/** Horizontal hour rules, rendered behind a day column's task blocks. */
export function HourGrid({ startHour, endHour }: { startHour: number; endHour: number }) {
  const hours = Array.from({ length: endHour - startHour + 1 }, (_, i) => startHour + i)
  const line: CSSProperties = {
    position: 'absolute',
    left: 0,
    right: 0,
    borderTop: '1px solid var(--color-border-subtle)',
  }
  return (
    <div aria-hidden="true" style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }}>
      {hours.map(h => (
        <div key={h} style={{ ...line, top: (h - startHour) * 60 * PX_PER_MINUTE }} />
      ))}
    </div>
  )
}
