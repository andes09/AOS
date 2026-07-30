import { DayColumn } from './DayColumn'
import { TimeAxis } from './TimeAxis'
import { addDays, toISO, todayISO, WEEKDAY_LABELS } from '../../lib/date'
import type { FlatTask } from '../../pages/planner/usePlannerData'

interface CalendarGridProps {
  /** First day shown. Week view passes a Monday; day view passes any day. */
  anchor: Date
  /** How many day columns to render. 5 = Mon–Fri, 7 = full week, 1 = day view. */
  dayCount: number
  byDate: Map<string, FlatTask[]>
  startHour: number
  endHour: number
  colorOf: (task: FlatTask) => number | null
  onToggle: (task: FlatTask) => void
  onOpen: (task: FlatTask) => void
}

/**
 * The timed calendar surface, shared by the week and day views — they differ
 * only in how many columns they show, so they are one component rather than
 * two near-identical ones.
 */
export function CalendarGrid({
  anchor,
  dayCount,
  byDate,
  startHour,
  endHour,
  colorOf,
  onToggle,
  onOpen,
}: CalendarGridProps) {
  const days = Array.from({ length: dayCount }, (_, i) => addDays(anchor, i))
  const today = todayISO()

  return (
    <div style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'flex-start', overflowX: 'auto' }}>
      {/* Spacer aligns the axis with the day headers above the grid. */}
      <div style={{ paddingTop: 66, flexShrink: 0 }}>
        <TimeAxis startHour={startHour} endHour={endHour} />
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: `repeat(${dayCount}, minmax(${dayCount === 1 ? 320 : 150}px, 1fr))`,
          gap: 'var(--space-2)',
          flex: 1,
          minWidth: 0,
        }}
      >
        {days.map(day => {
          const iso = toISO(day)
          return (
            <DayColumn
              key={iso}
              iso={iso}
              label={WEEKDAY_LABELS[(day.getDay() + 6) % 7]}
              dayOfMonth={day.getDate()}
              tasks={byDate.get(iso) ?? []}
              isToday={iso === today}
              startHour={startHour}
              endHour={endHour}
              colorOf={colorOf}
              onToggle={onToggle}
              onOpen={onOpen}
            />
          )
        })}
      </div>
    </div>
  )
}
