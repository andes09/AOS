import { CSSProperties } from 'react'
import { useDroppable } from '@dnd-kit/core'
import { ChevronDown, ChevronRight, Plus } from 'lucide-react'
import { Avatar } from '../ui/Avatar'
import { IconButton } from '../ui/IconButton'
import { laneVars } from '../../lib/laneColors'
import type { FlatTask } from '../../pages/planner/usePlannerData'

interface MemberLaneProps {
  id: string | null
  name: string
  /** Free-text job title, shown under the name. */
  subtitle?: string | null
  colorIndex: number | null
  avatarUrl?: string | null
  initials?: string | null
  count: number
  tasks: FlatTask[]
  collapsed: boolean
  /** Whether this lane is part of the active assignee filter. */
  selected: boolean
  onToggleCollapse: () => void
  onToggleSelect: () => void
  onAddTask: () => void
  renderTask: (task: FlatTask) => React.ReactNode
}

/**
 * One person's row in the planner sidebar: color dot, avatar, name, a count of
 * open scheduled work, and — when expanded — their tasks.
 *
 * The whole row is a drop target, so dragging a card onto a lane reassigns it
 * without touching its date.
 */
export function MemberLane({
  id,
  name,
  subtitle,
  colorIndex,
  avatarUrl,
  initials,
  count,
  tasks,
  collapsed,
  selected,
  onToggleCollapse,
  onToggleSelect,
  onAddTask,
  renderTask,
}: MemberLaneProps) {
  const lane = laneVars(colorIndex)
  const { setNodeRef, isOver } = useDroppable({
    id: `lane:${id ?? 'none'}`,
    data: { type: 'lane', assigneeId: id },
  })

  const headerStyle: CSSProperties = {
    display: 'flex',
    alignItems: 'center',
    gap: 'var(--space-2)',
    padding: '6px var(--space-2)',
    borderRadius: 'var(--radius-md)',
    cursor: 'pointer',
    background: selected ? 'var(--color-accent-subtle)' : 'transparent',
    border: `1px solid ${selected ? 'var(--color-accent)' : 'transparent'}`,
  }

  return (
    <div
      ref={setNodeRef}
      className={`pl-drop-zone${isOver ? ' pl-drop-zone--over' : ''}`}
      style={{ borderRadius: 'var(--radius-md)', padding: 2 }}
    >
      <div
        className="pl-lane-row"
        style={headerStyle}
        onClick={onToggleSelect}
        onKeyDown={e => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            onToggleSelect()
          }
        }}
        role="button"
        tabIndex={0}
        aria-pressed={selected}
        aria-label={`${name}, ${count} scheduled${selected ? ', filtered' : ''}`}
      >
        <span
          aria-hidden="true"
          style={{
            width: 8,
            height: 8,
            flexShrink: 0,
            borderRadius: '50%',
            background: lane.solid,
          }}
        />
        <Avatar name={name} colorIndex={colorIndex} avatarUrl={avatarUrl} initials={initials} size="sm" />
        <span style={{ minWidth: 0, flex: 1 }}>
          <span
            style={{
              display: 'block',
              fontSize: 'var(--text-sm)',
              fontWeight: 'var(--font-weight-semibold)' as CSSProperties['fontWeight'],
              color: 'var(--color-text-primary)',
              letterSpacing: '0.02em',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {name}
          </span>
          {subtitle && (
            <span
              style={{
                display: 'block',
                fontSize: 'var(--text-xs)',
                color: 'var(--color-text-muted)',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
            >
              {subtitle}
            </span>
          )}
        </span>
        <IconButton
          label={`Add a task for ${name}`}
          size={20}
          onClick={e => {
            e.stopPropagation()
            onAddTask()
          }}
        >
          <Plus size={13} />
        </IconButton>
      </div>

      <button
        onClick={onToggleCollapse}
        aria-expanded={!collapsed}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 4,
          margin: '2px 0 0 var(--space-2)',
          padding: '2px 4px',
          background: 'transparent',
          border: 'none',
          cursor: 'pointer',
          color: 'var(--color-accent)',
          fontFamily: 'var(--font-sans)',
          fontSize: 'var(--text-xs)',
        }}
      >
        {collapsed ? <ChevronRight size={12} /> : <ChevronDown size={12} />}
        {count} scheduled
      </button>

      {!collapsed && tasks.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, padding: '4px 0 var(--space-2)' }}>
          {tasks.map(renderTask)}
        </div>
      )}
    </div>
  )
}
