import { CSSProperties } from 'react'
import { PanelLeftClose, Users } from 'lucide-react'
import { MemberLane } from './MemberLane'
import { IconButton } from '../ui/IconButton'
import type { RoadmapMember } from '../../types/roadmap'
import type { FlatTask } from '../../pages/planner/usePlannerData'

interface PlannerSidebarProps {
  /** Rendered at the very top of the rail — the date nav lives here. */
  topSlot?: React.ReactNode
  members: RoadmapMember[]
  byAssignee: Map<string | null, FlatTask[]>
  collapsedIds: Set<string>
  selectedIds: Set<string>
  onToggleCollapse: (key: string) => void
  onToggleSelect: (key: string) => void
  /** Hide the whole panel — the calendar goes full-width. */
  onCollapsePanel: () => void
  onAddTask: (assigneeId: string | null) => void
  renderTask: (task: FlatTask) => React.ReactNode
}

/** Sentinel key for the unassigned lane — mirrors plannerFilters.UNASSIGNED. */
const UNASSIGNED = '__unassigned__'

/**
 * The left rail: one lane per teammate, plus an unassigned lane.
 *
 * The unassigned lane is deliberately first-class rather than hidden. A freshly
 * generated roadmap has no owners at all, so this is where every new plan
 * starts — burying it would make the planner look empty on day one.
 */
export function PlannerSidebar({
  topSlot,
  members,
  byAssignee,
  collapsedIds,
  selectedIds,
  onToggleCollapse,
  onToggleSelect,
  onCollapsePanel,
  onAddTask,
  renderTask,
}: PlannerSidebarProps) {
  const unassigned = byAssignee.get(null) ?? []

  return (
    <aside
      style={{
        width: 300,
        flexShrink: 0,
        display: 'flex',
        flexDirection: 'column',
        gap: 'var(--space-2)',
        borderRight: '1px solid var(--color-border-subtle)',
        paddingRight: 'var(--space-4)',
        overflowY: 'auto',
      }}
    >
      {topSlot && (
        <div style={{ paddingBottom: 'var(--space-3)', marginBottom: 'var(--space-1)', borderBottom: '1px solid var(--color-border-subtle)' }}>
          {topSlot}
        </div>
      )}

      <div style={headerStyle}>
        <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <Users size={15} />
          By person
        </span>
        <IconButton label="Hide people panel" size={24} onClick={onCollapsePanel}>
          <PanelLeftClose size={16} />
        </IconButton>
      </div>

      {members.length === 0 && unassigned.length === 0 && (
        <p style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-muted)', margin: 0, lineHeight: 1.5 }}>
          No teammates yet. Invite people to your org and they'll appear here as lanes.
        </p>
      )}

      {members.map(m => (
        <MemberLane
          key={m.id}
          id={m.id}
          name={m.name}
          subtitle={m.role}
          colorIndex={m.colorIndex}
          avatarUrl={m.avatarUrl}
          initials={m.initials}
          count={m.scheduledCount}
          tasks={byAssignee.get(m.id) ?? []}
          collapsed={collapsedIds.has(m.id)}
          selected={selectedIds.has(m.id)}
          onToggleCollapse={() => onToggleCollapse(m.id)}
          onToggleSelect={() => onToggleSelect(m.id)}
          onAddTask={() => onAddTask(m.id)}
          renderTask={renderTask}
        />
      ))}

      {unassigned.length > 0 && (
        <MemberLane
          id={null}
          name="Unassigned"
          subtitle="Not owned by anyone yet"
          colorIndex={null}
          count={unassigned.length}
          tasks={unassigned}
          collapsed={collapsedIds.has(UNASSIGNED)}
          selected={selectedIds.has(UNASSIGNED)}
          onToggleCollapse={() => onToggleCollapse(UNASSIGNED)}
          onToggleSelect={() => onToggleSelect(UNASSIGNED)}
          onAddTask={() => onAddTask(null)}
          renderTask={renderTask}
        />
      )}
    </aside>
  )
}

const headerStyle: CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  fontSize: 'var(--text-sm)',
  fontWeight: 'var(--font-weight-semibold)' as CSSProperties['fontWeight'],
  color: 'var(--color-text-muted)',
  textTransform: 'uppercase',
  letterSpacing: '0.06em',
  padding: '0 var(--space-3)',
}
