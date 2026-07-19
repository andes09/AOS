// Roadmap API contract types.
// These mirror the JSON shapes served by /api/roadmap/* — see
// apps/api/src/routers/roadmap.py (_task_json / _milestone_json / _project_json).

/** Matches TaskStatus in apps/api/src/models/task.py. */
export type TaskStatus = 'todo' | 'in_progress' | 'done'

export type RoadmapTask = {
  id: string
  title: string
  description: string | null
  status: TaskStatus
  /** Position within the milestone, 0-based and contiguous. */
  sortOrder: number
  /** Calendar day this task is planned for ("YYYY-MM-DD"), or null if unscheduled. */
  scheduledDate: string | null
}

export type RoadmapMilestone = {
  id: string
  title: string
  description: string | null
  /** Position within the project, 0-based. */
  sortOrder: number
  /** Ordered by sortOrder, server-side. */
  tasks: RoadmapTask[]
}

export type RoadmapProject = {
  id: string
  name: string
  summary: string | null
  purpose: string | null
  /** Ordered by sortOrder, server-side. */
  milestones: RoadmapMilestone[]
}

/**
 * PATCH /api/roadmap/tasks/{id} body. All fields optional; only the ones you
 * send change. `scheduledDate: null` explicitly unschedules; `description:
 * null` explicitly clears. `sortOrder` moves the task within its milestone
 * (0-based target index) — the server reshuffles siblings to stay contiguous.
 */
export type TaskUpdate = {
  status?: TaskStatus
  title?: string
  description?: string | null
  scheduledDate?: string | null
  sortOrder?: number
}

/**
 * The one derived state a roadmap UI renders from. Discriminate on `status`:
 *
 *   loading ──▶ empty ──generate()──▶ generating ──▶ ready
 *                                         │            │
 *                                         ▼            │ regenerate()
 *                                       error ◀────────┘   (back to generating)
 *
 * `generating` keeps the previous project (if any) so a regenerate can render
 * the stale tree dimmed instead of a blank screen.
 */
export type RoadmapState =
  | { status: 'loading' }
  | { status: 'empty' }
  | { status: 'generating'; project: RoadmapProject | null }
  | { status: 'ready'; project: RoadmapProject }
  | { status: 'error'; error: Error; project: RoadmapProject | null }
