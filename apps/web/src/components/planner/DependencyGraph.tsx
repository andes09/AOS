import { CSSProperties, useMemo } from 'react'
import { laneVars } from '../../lib/laneColors'
import type { FlatTask } from '../../pages/planner/usePlannerData'
import { computeDagLayout, NODE_HEIGHT, NODE_WIDTH, type DagTaskInput } from '../../pages/planner/dependencyLayout'

interface DependencyGraphProps {
  /** Unfiltered — every task in the plan, so a hidden/filtered task never
   *  leaves a dangling edge pointing at nothing. */
  tasksById: Map<string, FlatTask>
  colorOf: (task: FlatTask) => number | null
  onOpen: (task: FlatTask) => void
}

/**
 * Task-level prerequisite graph: one node per task, one edge per `dependsOn`
 * entry, laid out left-to-right by dependency depth.
 *
 * Nodes are absolutely-positioned HTML divs (not SVG `<text>`) so titles get
 * free line-clamping and click targets identical to every other task card in
 * the app; edges are a thin SVG layer underneath since a plain bezier `<path>`
 * is simpler than faking a curve with HTML. No graph library — the plan sizes
 * involved (dozens of tasks) don't need one, and MilestoneMap already sets the
 * precedent of a hand-rolled SVG here.
 */
export function DependencyGraph({ tasksById, colorOf, onOpen }: DependencyGraphProps) {
  const tasks = useMemo(() => Array.from(tasksById.values()), [tasksById])

  const layout = useMemo(() => {
    const inputs: DagTaskInput[] = tasks.map(t => ({
      id: t.id,
      dependsOn: t.dependsOn,
      milestoneIndex: t.milestoneIndex,
      sortOrder: t.sortOrder,
    }))
    return computeDagLayout(inputs)
  }, [tasks])

  if (tasks.length === 0) {
    return (
      <p style={{ color: 'var(--color-text-muted)', fontSize: 'var(--text-sm)', margin: 0 }}>
        No tasks yet — generate a plan to see the dependency graph here.
      </p>
    )
  }

  const nodeById = new Map(layout.nodes.map(n => [n.id, n]))

  return (
    <div style={{ maxHeight: 460, overflow: 'auto' }}>
      <div style={{ position: 'relative', width: layout.width, height: layout.height }}>
        <svg
          width={layout.width}
          height={layout.height}
          style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }}
        >
          {layout.edges.map(edge => {
            const from = nodeById.get(edge.from)
            const to = nodeById.get(edge.to)
            if (!from || !to) return null
            const x1 = from.x + NODE_WIDTH
            const y1 = from.y + NODE_HEIGHT / 2
            const x2 = to.x
            const y2 = to.y + NODE_HEIGHT / 2
            const midX = (x1 + x2) / 2
            return (
              <path
                key={`${edge.from}->${edge.to}`}
                d={`M ${x1},${y1} C ${midX},${y1} ${midX},${y2} ${x2},${y2}`}
                stroke="var(--color-border)"
                strokeWidth={1.5}
                fill="none"
              />
            )
          })}
        </svg>

        {tasks.map(task => {
          const node = nodeById.get(task.id)
          if (!node) return null
          return (
            <GraphNode
              key={task.id}
              task={task}
              x={node.x}
              y={node.y}
              colorIndex={colorOf(task)}
              waiting={task.dependsOn.some(id => tasksById.get(id)?.status !== 'done')}
              onOpen={() => onOpen(task)}
            />
          )
        })}
      </div>
    </div>
  )
}

function GraphNode({
  task,
  x,
  y,
  colorIndex,
  waiting,
  onOpen,
}: {
  task: FlatTask
  x: number
  y: number
  colorIndex: number | null
  waiting: boolean
  onOpen: () => void
}) {
  const done = task.status === 'done'
  const lane = laneVars(colorIndex)

  return (
    <div
      onClick={onOpen}
      style={{
        position: 'absolute',
        left: x,
        top: y,
        width: NODE_WIDTH,
        height: NODE_HEIGHT,
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
        gap: 2,
        padding: '6px 8px',
        borderRadius: 'var(--radius-md)',
        border: waiting ? '2px solid var(--color-border-subtle)' : '1px solid var(--color-border-subtle)',
        borderLeft: `3px solid ${lane.solid}`,
        background: done ? 'var(--color-bg-secondary)' : lane.bg,
        opacity: done ? 0.65 : waiting ? 0.5 : 1,
        cursor: 'pointer',
        boxSizing: 'border-box',
      }}
    >
      {task.shortId && (
        <div style={{ fontFamily: 'var(--font-mono, monospace)', fontSize: 10, color: 'var(--color-text-muted)' }}>
          {task.shortId}
        </div>
      )}
      <div
        style={{
          fontSize: 'var(--text-sm)',
          lineHeight: 1.3,
          color: 'var(--color-text-primary)',
          textDecoration: done ? 'line-through' : 'none',
          display: '-webkit-box',
          WebkitLineClamp: 2,
          WebkitBoxOrient: 'vertical' as CSSProperties['WebkitBoxOrient'],
          overflow: 'hidden',
          overflowWrap: 'anywhere',
        }}
      >
        {task.title}
      </div>
    </div>
  )
}
