import { CSSProperties, useMemo } from 'react'
import { useDroppable } from '@dnd-kit/core'
import { HourGrid } from './TimeAxis'
import { TaskCard } from './TaskCard'
import { gridHeight, layoutDay, nowOffset, PX_PER_MINUTE } from '../../pages/planner/taskLayout'
import { toTimeStr } from '../../lib/date'
import type { FlatTask } from '../../pages/planner/usePlannerData'

/** Drop granularity inside the timed grid. */
const SLOT_MINUTES = 15

interface DayColumnProps {
  iso: string
  label: string
  dayOfMonth: number
  tasks: FlatTask[]
  isToday: boolean
  startHour: number
  endHour: number
  colorOf: (task: FlatTask) => number | null
  onToggle: (task: FlatTask) => void
  onDelete: (task: FlatTask) => void
  onOpen: (task: FlatTask) => void
}

/**
 * One day: an all-day strip of untimed tasks at the top, then the timed grid
 * with tasks positioned against the hour rules.
 *
 * Overlapping tasks are split side by side rather than collapsed behind a
 * "+2 more" — a scheduling conflict is exactly what you need to see.
 */
export function DayColumn({
  iso,
  label,
  dayOfMonth,
  tasks,
  isToday,
  startHour,
  endHour,
  colorOf,
  onToggle,
  onDelete,
  onOpen,
}: DayColumnProps) {
  const untimed = tasks.filter(t => !t.scheduledTime)
  const timed = tasks.filter(t => t.scheduledTime)

  const boxes = useMemo(
    () => layoutDay(timed, startHour * 60),
    [timed, startHour],
  )
  const boxById = useMemo(() => new Map(boxes.map(b => [b.id, b])), [boxes])

  const height = gridHeight(startHour, endHour)
  const now = isToday ? nowOffset(startHour, endHour) : null

  // A drop target per quarter hour. The column itself is not a drop target —
  // dropping needs to resolve to a specific time, not just a day.
  const slots = useMemo(() => {
    const out: { key: string; time: string; top: number }[] = []
    for (let m = startHour * 60; m < endHour * 60; m += SLOT_MINUTES) {
      out.push({ key: `${iso}-${m}`, time: toTimeStr(m), top: (m - startHour * 60) * PX_PER_MINUTE })
    }
    return out
  }, [iso, startHour, endHour])

  return (
    <div style={columnStyle(isToday)}>
      <div style={headerStyle(isToday)}>
        <span
          style={{
            fontSize: 'var(--text-xs)',
            fontWeight: 600,
            textTransform: 'uppercase',
            letterSpacing: '0.05em',
            color: isToday ? 'var(--color-accent)' : 'var(--color-text-muted)',
          }}
        >
          {label}
        </span>
        <span style={{ fontSize: 'var(--text-sm)', fontWeight: 700, color: 'var(--color-text-primary)' }}>
          {dayOfMonth}
        </span>
      </div>

      <AllDayStrip
        iso={iso}
        tasks={untimed}
        colorOf={colorOf}
        onToggle={onToggle}
        onDelete={onDelete}
        onOpen={onOpen}
      />

      <div style={{ position: 'relative', height, flex: '0 0 auto' }}>
        <HourGrid startHour={startHour} endHour={endHour} />

        {slots.map(s => (
          <TimeSlot key={s.key} iso={iso} time={s.time} top={s.top} />
        ))}

        {now !== null && (
          <div
            className="pl-now-line"
            aria-hidden="true"
            style={{
              position: 'absolute',
              left: 0,
              right: 0,
              top: now,
              borderTop: '2px solid var(--color-danger)',
              zIndex: 2,
              pointerEvents: 'none',
            }}
          />
        )}

        {timed.map(task => {
          const box = boxById.get(task.id)
          if (!box) return null
          return (
            <TaskCard
              key={task.id}
              task={task}
              colorIndex={colorOf(task)}
              showMilestone={box.height > 56}
              onToggle={() => onToggle(task)}
              onDelete={() => onDelete(task)}
              onOpen={() => onOpen(task)}
              style={{
                position: 'absolute',
                top: box.top,
                height: box.height,
                left: `calc(${box.leftPct * 100}% + 2px)`,
                width: `calc(${box.widthPct * 100}% - 4px)`,
                overflow: 'hidden',
                zIndex: 3,
              }}
            />
          )
        })}
      </div>
    </div>
  )
}

/** Quarter-hour drop target. Invisible until something is dragged over it. */
function TimeSlot({ iso, time, top }: { iso: string; time: string; top: number }) {
  const { setNodeRef, isOver } = useDroppable({
    id: `slot:${iso}:${time}`,
    data: { type: 'slot', iso, time },
  })
  return (
    <div
      ref={setNodeRef}
      className={isOver ? 'pl-drop-zone pl-drop-zone--over' : 'pl-drop-zone'}
      style={{
        position: 'absolute',
        left: 0,
        right: 0,
        top,
        height: SLOT_MINUTES * PX_PER_MINUTE,
        zIndex: 1,
      }}
    />
  )
}

/** Untimed work for the day, banded above the grid. Dropping here clears time. */
function AllDayStrip({
  iso,
  tasks,
  colorOf,
  onToggle,
  onDelete,
  onOpen,
}: {
  iso: string
  tasks: FlatTask[]
  colorOf: (t: FlatTask) => number | null
  onToggle: (t: FlatTask) => void
  onDelete: (t: FlatTask) => void
  onOpen: (t: FlatTask) => void
}) {
  const { setNodeRef, isOver } = useDroppable({ id: `day:${iso}`, data: { type: 'day', iso } })

  return (
    <div
      ref={setNodeRef}
      className={isOver ? 'pl-drop-zone pl-drop-zone--over' : 'pl-drop-zone'}
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 4,
        padding: 'var(--space-1)',
        minHeight: 34,
        borderBottom: '1px solid var(--color-border-subtle)',
      }}
    >
      {tasks.map(t => (
        <TaskCard
          key={t.id}
          task={t}
          colorIndex={colorOf(t)}
          showMilestone={false}
          onToggle={() => onToggle(t)}
          onDelete={() => onDelete(t)}
          onOpen={() => onOpen(t)}
        />
      ))}
    </div>
  )
}

const columnStyle = (isToday: boolean): CSSProperties => ({
  display: 'flex',
  flexDirection: 'column',
  minWidth: 0,
  border: `1px solid ${isToday ? 'var(--color-accent)' : 'var(--color-border)'}`,
  borderRadius: 'var(--radius-lg)',
  background: 'var(--color-bg-elevated)',
  overflow: 'hidden',
})

const headerStyle = (isToday: boolean): CSSProperties => ({
  display: 'flex',
  alignItems: 'baseline',
  gap: 6,
  padding: '6px var(--space-2)',
  borderBottom: '1px solid var(--color-border-subtle)',
  background: isToday ? 'var(--color-accent-subtle)' : 'transparent',
  position: 'sticky',
  top: 0,
  zIndex: 'var(--z-sticky)' as never,
})
