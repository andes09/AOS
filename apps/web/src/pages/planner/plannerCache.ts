// apps/web/src/pages/planner/plannerCache.ts
//
// Immutable transforms over the cached Roadmap, used by every optimistic
// mutation. Pure and dependency-free so they can be unit-tested directly.
//
// `mapTask` was moved here unchanged from PlannerCalendarPage — it's the
// load-bearing primitive behind every optimistic update in the planner, and
// it already works.

import type { Roadmap, RoadmapTask, TaskRescheduleItem } from '../../types/roadmap'

/** Apply `fn` to one task, leaving the rest of the tree structurally shared. */
export function mapTask(
  rm: Roadmap,
  taskId: string,
  fn: (t: RoadmapTask) => RoadmapTask,
): Roadmap {
  return {
    ...rm,
    milestones: rm.milestones.map(m => ({
      ...m,
      tasks: m.tasks.map(t => (t.id === taskId ? fn(t) : t)),
    })),
  }
}


/**
 * Apply a batch of partial updates in one pass.
 *
 * Used by the drag-drop reschedule path. Doing this as N sequential `mapTask`
 * calls would rebuild the whole tree N times and make the optimistic update
 * visibly janky on a multi-select drag.
 */
export function mapTasks(rm: Roadmap, updates: TaskRescheduleItem[]): Roadmap {
  if (updates.length === 0) return rm
  const byId = new Map(updates.map(u => [u.id, u]))
  return {
    ...rm,
    milestones: rm.milestones.map(m => ({
      ...m,
      tasks: m.tasks.map(t => {
        const u = byId.get(t.id)
        if (!u) return t
        const next = { ...t }
        // Mirror the API's omitted-vs-null contract: a key that isn't present
        // means "leave alone", an explicit null means "clear".
        if ('scheduledDate' in u) next.scheduledDate = u.scheduledDate ?? null
        if ('scheduledTime' in u) next.scheduledTime = u.scheduledTime ?? null
        if ('assigneeId' in u) next.assigneeId = u.assigneeId ?? null
        return next
      }),
    })),
  }
}

/**
 * Append a task to a milestone, or to the last one when `milestoneId` is
 * omitted — mirroring what the server does so the optimistic placement matches
 * where the row actually lands.
 */
export function addTask(rm: Roadmap, task: RoadmapTask, milestoneId?: string | null): Roadmap {
  if (rm.milestones.length === 0) return rm
  const targetId =
    milestoneId ??
    rm.milestones.reduce((a, b) => (b.sortOrder > a.sortOrder ? b : a)).id
  return {
    ...rm,
    milestones: rm.milestones.map(m =>
      m.id === targetId ? { ...m, tasks: [...m.tasks, task] } : m,
    ),
  }
}
