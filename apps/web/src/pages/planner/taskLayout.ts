// apps/web/src/pages/planner/taskLayout.ts
//
// Geometry for the timed day column: where each task block sits and how wide
// it is when several overlap.
//
// Pure and React-free so the fiddly interval math can be tested directly.

import { parseTime } from '../../lib/date'

/** Vertical scale of the time grid. 1px per minute → an hour is 60px tall. */
export const PX_PER_MINUTE = 1
/** Even a 5-minute task needs to stay readable and clickable. */
export const MIN_BLOCK_HEIGHT = 22
/** Assumed length of a task with no explicit duration, for overlap purposes. */
export const DEFAULT_DURATION_MINUTES = 30

export interface LayoutInput {
  id: string
  scheduledTime: string | null
  durationMinutes: number | null
}

export interface LayoutBox {
  id: string
  top: number
  height: number
  /** Fraction of column width, 0–1. */
  widthPct: number
  /** Fraction offset from the column's left edge, 0–1. */
  leftPct: number
}

interface Interval extends LayoutInput {
  start: number
  end: number
}

/**
 * Lay timed tasks out against the axis, splitting the column between tasks
 * that overlap in time.
 *
 * Two tasks at 9:30 render side by side at half width rather than stacking
 * invisibly on top of each other. The alternative — collapsing to "+2 more" —
 * hides work at exactly the moment the user most needs to see the conflict.
 *
 * `dayStartMinutes` is the top of the visible grid, so a task at 09:00 in a
 * grid starting at 07:00 sits 120px down rather than 540px.
 */
export function layoutDay(tasks: LayoutInput[], dayStartMinutes: number): LayoutBox[] {
  const intervals: Interval[] = []
  for (const t of tasks) {
    const start = parseTime(t.scheduledTime)
    if (start === null) continue // untimed tasks live in the all-day strip
    const duration = t.durationMinutes && t.durationMinutes > 0
      ? t.durationMinutes
      : DEFAULT_DURATION_MINUTES
    intervals.push({ ...t, start, end: start + duration })
  }
  if (intervals.length === 0) return []

  intervals.sort((a, b) => a.start - b.start || a.end - b.end)

  const boxes: LayoutBox[] = []

  // Walk the intervals accumulating "clusters" — maximal runs of tasks
  // connected by overlap. Every task in a cluster shares the column width, so
  // that a 3-way pileup at 09:00 doesn't leave a lone 14:00 task at 1/3 width.
  let cluster: Interval[] = []
  let clusterEnd = -Infinity

  const flush = () => {
    if (cluster.length === 0) return
    // Greedy column packing: place each task in the first column whose last
    // occupant has already ended.
    const columnEnds: number[] = []
    const columnOf = new Map<string, number>()
    for (const iv of cluster) {
      let col = columnEnds.findIndex(end => end <= iv.start)
      if (col === -1) {
        col = columnEnds.length
        columnEnds.push(iv.end)
      } else {
        columnEnds[col] = iv.end
      }
      columnOf.set(iv.id, col)
    }
    const columns = columnEnds.length
    for (const iv of cluster) {
      const col = columnOf.get(iv.id) ?? 0
      boxes.push({
        id: iv.id,
        top: (iv.start - dayStartMinutes) * PX_PER_MINUTE,
        height: Math.max((iv.end - iv.start) * PX_PER_MINUTE, MIN_BLOCK_HEIGHT),
        widthPct: 1 / columns,
        leftPct: col / columns,
      })
    }
    cluster = []
    clusterEnd = -Infinity
  }

  for (const iv of intervals) {
    if (cluster.length > 0 && iv.start >= clusterEnd) flush()
    cluster.push(iv)
    clusterEnd = Math.max(clusterEnd, iv.end)
  }
  flush()

  return boxes
}

/** Total grid height for a start/end hour window. */
export function gridHeight(startHour: number, endHour: number): number {
  return (endHour - startHour) * 60 * PX_PER_MINUTE
}

/** Offset of the "now" line, or null when now is outside the visible window. */
export function nowOffset(startHour: number, endHour: number, now = new Date()): number | null {
  const mins = now.getHours() * 60 + now.getMinutes()
  if (mins < startHour * 60 || mins > endHour * 60) return null
  return (mins - startHour * 60) * PX_PER_MINUTE
}
