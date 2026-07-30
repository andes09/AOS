import { useDroppable } from '@dnd-kit/core'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { TaskCard } from './TaskCard'
import type { FlatTask } from '../../pages/planner/usePlannerData'

interface UnscheduledTrayProps {
  tasks: FlatTask[]
  collapsed: boolean
  onToggleCollapse: () => void
  colorOf: (task: FlatTask) => number | null
  onToggle: (task: FlatTask) => void
  onOpen: (task: FlatTask) => void
}

/**
 * Parking area for work with no date. Doubles as the drop target that
 * unschedules a task — dragging a card here clears both its date and time.
 */
export function UnscheduledTray({
  tasks,
  collapsed,
  onToggleCollapse,
  colorOf,
  onToggle,
  onOpen,
}: UnscheduledTrayProps) {
  const { setNodeRef, isOver } = useDroppable({ id: 'unscheduled', data: { type: 'unscheduled' } })

  // Still rendered when empty — it has to stay available as a drop target.
  return (
    <div
      ref={setNodeRef}
      className={isOver ? 'pl-drop-zone pl-drop-zone--over' : 'pl-drop-zone'}
      style={{
        marginTop: 'var(--space-4)',
        border: '1px dashed var(--color-border)',
        borderRadius: 'var(--radius-lg)',
        padding: 'var(--space-2)',
      }}
    >
      <button
        onClick={onToggleCollapse}
        aria-expanded={!collapsed}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 5,
          background: 'transparent',
          border: 'none',
          cursor: 'pointer',
          padding: 2,
          fontFamily: 'var(--font-sans)',
          fontSize: 'var(--text-xs)',
          fontWeight: 600,
          textTransform: 'uppercase',
          letterSpacing: '0.05em',
          color: 'var(--color-text-muted)',
        }}
      >
        {collapsed ? <ChevronRight size={12} /> : <ChevronDown size={12} />}
        Unscheduled · {tasks.length}
      </button>

      {!collapsed && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5, marginTop: 'var(--space-2)' }}>
          {tasks.length === 0 ? (
            <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-muted)', padding: 4 }}>
              Drop a task here to unschedule it.
            </span>
          ) : (
            tasks.map(t => (
              <div key={t.id} style={{ width: 210 }}>
                <TaskCard
                  task={t}
                  colorIndex={colorOf(t)}
                  onToggle={() => onToggle(t)}
                  onOpen={() => onOpen(t)}
                />
              </div>
            ))
          )}
        </div>
      )}
    </div>
  )
}
