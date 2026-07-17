// Roadmap (personal day-by-day plan) — mirrors /api/roadmap payloads.
// See apps/api/src/routers/roadmap.py.

export type RoadmapTaskStatus = 'todo' | 'in_progress' | 'done'

export interface RoadmapTask {
  id: string
  title: string
  description: string | null
  status: RoadmapTaskStatus
  sortOrder: number
  /** Calendar day, ISO `YYYY-MM-DD`, or null if unscheduled. */
  scheduledDate: string | null
}

export interface RoadmapMilestone {
  id: string
  title: string
  description: string | null
  sortOrder: number
  tasks: RoadmapTask[]
}

export interface Roadmap {
  id: string
  name: string
  summary: string | null
  purpose: string | null
  milestones: RoadmapMilestone[]
}
