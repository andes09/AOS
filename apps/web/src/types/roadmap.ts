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
  /**
   * Wall-clock start, `HH:MM` (24h), or null for an all-day task.
   * Naive by design — see the header of lib/date.ts.
   */
  scheduledTime: string | null
  /** Null means "no explicit duration"; the card renders compact. */
  durationMinutes: number | null
  /** Owning developer. Null renders in the neutral unassigned lane. */
  assigneeId: string | null
}

/** A person in the org — one sidebar lane. GET /api/roadmap/members. */
export interface RoadmapMember {
  id: string
  name: string
  /** Free-text job title, not a permission level. */
  role: string | null
  email: string | null
  /** Index into the lane palette; see lib/laneColors.ts. */
  colorIndex: number
  avatarUrl: string | null
  initials: string
  isActive: boolean
  /** Open (not-done) tasks that have a date. Drives the "N scheduled" count. */
  scheduledCount: number
}

export interface RoadmapMembersResponse {
  members: RoadmapMember[]
}

/** One entry in a bulk POST /api/roadmap/tasks/reschedule. */
export interface TaskRescheduleItem {
  id: string
  scheduledDate?: string | null
  scheduledTime?: string | null
  assigneeId?: string | null
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

/** Readiness signal for the planner's "?" badge (GET /api/roadmap/status). */
export interface RoadmapStatus {
  hasRoadmap: boolean
  needsMoreInfo: boolean
  missingFields: string[]
}

export interface ProjectChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  createdAt: string | null
}
