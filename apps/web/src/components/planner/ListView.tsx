import { useMemo } from 'react'
import { TaskCard } from './TaskCard'
import { MONTHS, parseISO, todayISO, WEEKDAY_LABELS } from '../../lib/date'
import type { FlatTask } from '../../pages/planner/usePlannerData'

interface ListViewProps {
  tasks: FlatTask[]
  colorOf: (task: FlatTask) => number | null
  onToggle: (task: FlatTask) => void
  onDelete: (task: FlatTask) => void
  onOpen: (task: FlatTask) => void
}

/** Flat chronological agenda, grouped by day. Unscheduled work sorts last. */
export function ListView({ tasks, colorOf, onToggle, onDelete, onOpen }: ListViewProps) {
  const groups = useMemo(() => {
    const byDate = new Map<string, FlatTask[]>()
    for (const t of tasks) {
      const key = t.scheduledDate ?? ''
      const list = byDate.get(key)
      if (list) list.push(t)
      else byDate.set(key, [t])
    }
    return [...byDate.entries()].sort(([a], [b]) => {
      if (a === '') return 1 // undated last
      if (b === '') return -1
      return a.localeCompare(b)
    })
  }, [tasks])

  if (groups.length === 0) {
    return <p style={{ color: 'var(--color-text-muted)', fontSize: 'var(--text-sm)' }}>Nothing matches these filters.</p>
  }

  const today = todayISO()

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-5)', maxWidth: 720 }}>
      {groups.map(([iso, items]) => {
        const d = iso ? parseISO(iso) : null
        const isToday = iso === today
        return (
          <section key={iso || 'undated'}>
            <h2
              style={{
                margin: '0 0 var(--space-2)',
                fontSize: 'var(--text-xs)',
                fontWeight: 600,
                textTransform: 'uppercase',
                letterSpacing: '0.06em',
                color: isToday ? 'var(--color-accent)' : 'var(--color-text-muted)',
              }}
            >
              {d
                ? `${WEEKDAY_LABELS[(d.getDay() + 6) % 7]} ${MONTHS[d.getMonth()]} ${d.getDate()}${isToday ? ' · Today' : ''}`
                : 'Unscheduled'}
            </h2>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
              {items.map(t => (
                <TaskCard
                  key={t.id}
                  task={t}
                  colorIndex={colorOf(t)}
                  onToggle={() => onToggle(t)}
                  onDelete={() => onDelete(t)}
                  onOpen={() => onOpen(t)}
                />
              ))}
            </div>
          </section>
        )
      })}
    </div>
  )
}
