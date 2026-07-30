import { TaskCard } from './TaskCard'
import type { RoadmapTaskStatus } from '../../types/roadmap'
import type { FlatTask } from '../../pages/planner/usePlannerData'

const COLUMNS: { status: RoadmapTaskStatus; label: string }[] = [
  { status: 'todo', label: 'To do' },
  { status: 'in_progress', label: 'In progress' },
  { status: 'done', label: 'Done' },
]

interface BoardViewProps {
  tasks: FlatTask[]
  colorOf: (task: FlatTask) => number | null
  onToggle: (task: FlatTask) => void
  onOpen: (task: FlatTask) => void
}

/** Kanban by status. Cards keep their assignee color, so lanes read across columns. */
export function BoardView({ tasks, colorOf, onToggle, onOpen }: BoardViewProps) {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(3, minmax(220px, 1fr))',
        gap: 'var(--space-3)',
        alignItems: 'start',
        overflowX: 'auto',
      }}
    >
      {COLUMNS.map(col => {
        const items = tasks.filter(t => t.status === col.status)
        return (
          <div
            key={col.status}
            style={{
              border: '1px solid var(--color-border)',
              borderRadius: 'var(--radius-lg)',
              background: 'var(--color-bg-elevated)',
              overflow: 'hidden',
            }}
          >
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '7px var(--space-3)',
                borderBottom: '1px solid var(--color-border-subtle)',
                fontSize: 'var(--text-xs)',
                fontWeight: 600,
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
                color: 'var(--color-text-muted)',
              }}
            >
              {col.label}
              <span>{items.length}</span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 5, padding: 'var(--space-2)', minHeight: 80 }}>
              {items.map(t => (
                <TaskCard
                  key={t.id}
                  task={t}
                  colorIndex={colorOf(t)}
                  onToggle={() => onToggle(t)}
                  onOpen={() => onOpen(t)}
                />
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}
