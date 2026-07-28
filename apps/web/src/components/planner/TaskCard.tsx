import { CSSProperties, memo } from 'react'
import { useDraggable } from '@dnd-kit/core'
import { Check, GripVertical, Trash2 } from 'lucide-react'
import { IconButton } from '../ui/IconButton'
import { laneVars } from '../../lib/laneColors'
import { formatDuration, formatTime12h } from '../../lib/date'
import type { FlatTask } from '../../pages/planner/usePlannerData'

export interface TaskCardProps {
  task: FlatTask
  /** Assignee's palette slot; null renders the neutral unassigned treatment. */
  colorIndex: number | null
  onToggle: () => void
  onDelete: () => void
  onOpen?: () => void
  /** Show the milestone name under the title. Off in dense timed blocks. */
  showMilestone?: boolean
  draggable?: boolean
  style?: CSSProperties
}

/**
 * The planner's task card. Color comes strictly from the assignee via
 * `laneVars` — there is no per-task color prop, by design.
 *
 * Memoized because an optimistic update rewrites the whole roadmap object, and
 * without this every card in the visible week re-renders on each checkbox tick.
 */
export const TaskCard = memo(function TaskCard({
  task,
  colorIndex,
  onToggle,
  onDelete,
  onOpen,
  showMilestone = true,
  draggable = true,
  style,
}: TaskCardProps) {
  const done = task.status === 'done'
  const lane = laneVars(colorIndex)

  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: task.id,
    disabled: !draggable,
    data: { type: 'task', task },
  })

  const timeLabel = formatTime12h(task.scheduledTime)
  const durationLabel = formatDuration(task.durationMinutes)

  return (
    <div
      ref={setNodeRef}
      className={`pl-task-card${isDragging ? ' pl-dragging' : ''}`}
      style={{
        position: 'relative',
        display: 'flex',
        gap: 6,
        padding: '6px 7px',
        borderRadius: 'var(--radius-md)',
        border: '1px solid var(--color-border-subtle)',
        // The lane color reads as a left spine plus a tinted fill, so a glance
        // down a column tells you whose day it is without reading any names.
        borderLeft: `3px solid ${lane.solid}`,
        background: done ? 'var(--color-bg-secondary)' : lane.bg,
        opacity: done ? 0.65 : 1,
        cursor: onOpen ? 'pointer' : 'default',
        ...style,
      }}
      onClick={onOpen}
    >
      <button
        onClick={e => {
          e.stopPropagation()
          onToggle()
        }}
        aria-label={done ? 'Mark as not done' : 'Mark as done'}
        aria-pressed={done}
        style={{
          flexShrink: 0,
          width: 15,
          height: 15,
          marginTop: 1,
          padding: 0,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          borderRadius: 4,
          cursor: 'pointer',
          border: `1.5px solid ${done ? 'var(--color-success)' : 'var(--color-border-strong)'}`,
          background: done ? 'var(--color-success)' : 'transparent',
        }}
      >
        {done && <Check size={10} color="#fff" strokeWidth={3} />}
      </button>

      <div style={{ minWidth: 0, flex: 1 }}>
        {timeLabel && (
          <div style={{ fontSize: 10, color: lane.text, fontWeight: 600, lineHeight: 1.3 }}>
            {timeLabel}
            {durationLabel && (
              <span style={{ color: 'var(--color-text-muted)', fontWeight: 400 }}> · {durationLabel}</span>
            )}
          </div>
        )}
        <div
          style={{
            fontSize: 'var(--text-sm)',
            lineHeight: 1.35,
            color: 'var(--color-text-primary)',
            textDecoration: done ? 'line-through' : 'none',
            overflowWrap: 'anywhere',
          }}
        >
          {task.title}
        </div>
        {(showMilestone || task.shortId) && (
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              fontSize: 10,
              color: 'var(--color-text-muted)',
              marginTop: 2,
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}
          >
            {task.shortId && (
              <span style={{ fontFamily: 'var(--font-mono, monospace)', flexShrink: 0 }}>{task.shortId}</span>
            )}
            {showMilestone && <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{task.milestoneTitle}</span>}
          </div>
        )}
      </div>

      <div className="pl-task-actions" style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        {draggable && (
          <span
            {...attributes}
            {...listeners}
            aria-label="Drag task"
            style={{ cursor: 'grab', color: 'var(--color-text-muted)', display: 'flex', touchAction: 'none' }}
            onClick={e => e.stopPropagation()}
          >
            <GripVertical size={12} />
          </span>
        )}
        <IconButton
          label="Delete task"
          size={16}
          onClick={e => {
            e.stopPropagation()
            onDelete()
          }}
        >
          <Trash2 size={11} />
        </IconButton>
      </div>
    </div>
  )
})
