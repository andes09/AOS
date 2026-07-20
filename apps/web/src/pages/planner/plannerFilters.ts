// apps/web/src/pages/planner/plannerFilters.ts
//
// Pure predicates for the planner's filter bar. Kept separate from the data
// hook so filtering can be reasoned about (and tested) without React.

import type { RoadmapTaskStatus } from '../../types/roadmap'

/** Sentinel for the unassigned lane in an assignee filter set. */
export const UNASSIGNED = '__unassigned__'

export interface PlannerFilters {
  /** Empty set means "no assignee filter", NOT "show nothing". */
  assigneeIds: Set<string>
  /** Empty set means "all statuses". */
  statuses: Set<RoadmapTaskStatus>
  milestoneId: string | null
  search: string
}

export const EMPTY_FILTERS: PlannerFilters = {
  assigneeIds: new Set(),
  statuses: new Set(),
  milestoneId: null,
  search: '',
}

export function hasActiveFilters(f: PlannerFilters): boolean {
  return (
    f.assigneeIds.size > 0 ||
    f.statuses.size > 0 ||
    f.milestoneId !== null ||
    f.search.trim() !== ''
  )
}

interface FilterableTask {
  title: string
  description: string | null
  status: RoadmapTaskStatus
  assigneeId: string | null
  milestoneId: string
}

/**
 * True when a task survives every active filter.
 *
 * An empty filter set means "unfiltered" rather than "match nothing" — the
 * inverse would make clearing the last chip blank the whole board, which reads
 * as a bug even though it is technically consistent.
 */
export function matchesFilters(task: FilterableTask, f: PlannerFilters): boolean {
  if (f.assigneeIds.size > 0) {
    const key = task.assigneeId ?? UNASSIGNED
    if (!f.assigneeIds.has(key)) return false
  }
  if (f.statuses.size > 0 && !f.statuses.has(task.status)) return false
  if (f.milestoneId !== null && task.milestoneId !== f.milestoneId) return false

  const q = f.search.trim().toLowerCase()
  if (q) {
    const haystack = `${task.title} ${task.description ?? ''}`.toLowerCase()
    if (!haystack.includes(q)) return false
  }
  return true
}

/** Toggle a value in a Set, returning a new Set (never mutating the input). */
export function toggleInSet<T>(set: Set<T>, value: T): Set<T> {
  const next = new Set(set)
  if (next.has(value)) next.delete(value)
  else next.add(value)
  return next
}
