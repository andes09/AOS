// apps/web/src/pages/planner/dependencyLayout.ts
//
// Geometry for the task-dependency DAG: which column (rank) each task sits
// in and where it stacks within that column.
//
// Pure and React-free, same spirit as taskLayout.ts, so the graph algorithm
// can be tested directly.

export interface DagTaskInput {
  id: string
  dependsOn: string[]
  milestoneIndex: number
  sortOrder: number
}

export interface DagNode {
  id: string
  rank: number
  order: number
  x: number
  y: number
}

/** `from` is the prerequisite, `to` is the task that depends on it. */
export interface DagEdge {
  from: string
  to: string
}

export interface DagLayout {
  nodes: DagNode[]
  edges: DagEdge[]
  width: number
  height: number
}

export const NODE_WIDTH = 200
export const NODE_HEIGHT = 64
export const COLUMN_GAP = 96
export const ROW_GAP = 16
export const PADDING = 24

/**
 * Rank every task by longest-path depth from a root (a task with no
 * in-plan prerequisites), group into rank columns, and place each node's
 * pixel position.
 *
 * `dependsOn` ids that don't match any task in the plan (a stale reference
 * left behind by a generator/adjuster edit) are treated as no constraint —
 * filtered out before ranking and never turned into an edge, rather than
 * crashing or drawing a dangling line.
 *
 * The DB models dependencies as an actual DAG, so cycles shouldn't occur,
 * but rank computation still guards against one: a three-state visited map
 * (unvisited/visiting/done) stops recursion the moment it re-enters a node
 * that's still being resolved, so a data drift produces a wrong-but-finite
 * rank instead of hanging the tab.
 */
export function computeDagLayout(tasks: DagTaskInput[]): DagLayout {
  const byId = new Map(tasks.map(t => [t.id, t]))
  const idSet = new Set(byId.keys())

  const rankOf = new Map<string, number>()
  const state = new Map<string, 'visiting' | 'done'>()

  function resolveRank(id: string): number {
    const cached = rankOf.get(id)
    if (cached !== undefined) return cached
    if (state.get(id) === 'visiting') return 0 // cycle — break recursion, don't cache

    state.set(id, 'visiting')
    const task = byId.get(id)
    const deps = (task?.dependsOn ?? []).filter(d => idSet.has(d) && d !== id)
    const rank = deps.length === 0 ? 0 : 1 + Math.max(...deps.map(resolveRank))
    state.set(id, 'done')
    rankOf.set(id, rank)
    return rank
  }

  for (const t of tasks) resolveRank(t.id)

  const columns = new Map<number, DagTaskInput[]>()
  for (const t of tasks) {
    const rank = rankOf.get(t.id) ?? 0
    const col = columns.get(rank)
    if (col) col.push(t)
    else columns.set(rank, [t])
  }

  const nodes: DagNode[] = []
  let maxRank = -1
  let maxRowsInAnyColumn = 0

  for (const [rank, col] of columns) {
    maxRank = Math.max(maxRank, rank)
    col.sort(
      (a, b) => a.milestoneIndex - b.milestoneIndex || a.sortOrder - b.sortOrder || a.id.localeCompare(b.id),
    )
    maxRowsInAnyColumn = Math.max(maxRowsInAnyColumn, col.length)
    col.forEach((t, order) => {
      nodes.push({
        id: t.id,
        rank,
        order,
        x: PADDING + rank * (NODE_WIDTH + COLUMN_GAP),
        y: PADDING + order * (NODE_HEIGHT + ROW_GAP),
      })
    })
  }

  const edges: DagEdge[] = []
  for (const t of tasks) {
    for (const dep of t.dependsOn) {
      if (idSet.has(dep) && dep !== t.id) edges.push({ from: dep, to: t.id })
    }
  }

  const width = nodes.length === 0 ? 0 : PADDING * 2 + (maxRank + 1) * NODE_WIDTH + maxRank * COLUMN_GAP
  const height = nodes.length === 0 ? 0 : PADDING * 2 + maxRowsInAnyColumn * NODE_HEIGHT + (maxRowsInAnyColumn - 1) * ROW_GAP

  return { nodes, edges, width, height }
}
