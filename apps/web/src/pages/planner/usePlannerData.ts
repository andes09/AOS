// apps/web/src/pages/planner/usePlannerData.ts
//
// Composes the roadmap and member queries into everything the planner views
// need: tasks indexed by day, grouped by assignee, and the progress stats.
//
// All four views (week/day/list/board) consume this same output — only their
// layout differs.

import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useApi } from '../../lib/api'
import { compareByTime } from '../../lib/date'
import type {
  Roadmap,
  RoadmapMember,
  RoadmapMembersResponse,
  RoadmapTask,
} from '../../types/roadmap'
import { matchesFilters, type PlannerFilters } from './plannerFilters'

export const ROADMAP_KEY = ['roadmap'] as const
export const MEMBERS_KEY = ['roadmap', 'members'] as const

/** A task plus the milestone context the card needs to render. */
export interface FlatTask extends RoadmapTask {
  milestoneId: string
  milestoneTitle: string
  milestoneIndex: number
}

export interface PlannerStats {
  total: number
  done: number
  pct: number
}

export interface PlannerData {
  roadmap: Roadmap | null
  members: RoadmapMember[]
  membersById: Map<string, RoadmapMember>
  /** ISO date → that day's tasks, chronologically (untimed first). */
  byDate: Map<string, FlatTask[]>
  /** Assignee id (or `null` key for unassigned) → their tasks. */
  byAssignee: Map<string | null, FlatTask[]>
  unscheduled: FlatTask[]
  allTasks: FlatTask[]
  stats: PlannerStats
  /** Earliest scheduled date, for the initial week anchor. */
  firstDate: string | null
  isLoading: boolean
  error: unknown
}

export function usePlannerData(filters: PlannerFilters): PlannerData {
  const { get } = useApi()

  const roadmapQuery = useQuery({
    queryKey: ROADMAP_KEY,
    queryFn: () => get<Roadmap | null>('/api/roadmap'),
  })

  const membersQuery = useQuery({
    queryKey: MEMBERS_KEY,
    queryFn: () => get<RoadmapMembersResponse>('/api/roadmap/members'),
  })

  const roadmap = roadmapQuery.data ?? null
  const members = membersQuery.data?.members ?? []

  return useMemo(() => {
    const byDate = new Map<string, FlatTask[]>()
    const byAssignee = new Map<string | null, FlatTask[]>()
    const unscheduled: FlatTask[] = []
    const allTasks: FlatTask[] = []
    let total = 0
    let done = 0
    let firstDate: string | null = null

    for (const [mi, m] of (roadmap?.milestones ?? []).entries()) {
      for (const t of m.tasks) {
        const flat: FlatTask = {
          ...t,
          milestoneId: m.id,
          milestoneTitle: m.title,
          milestoneIndex: mi,
        }

        // Stats count the whole plan, deliberately ignoring filters — a
        // progress bar that moves when you filter would be lying about scope.
        total += 1
        if (t.status === 'done') done += 1

        if (!matchesFilters(flat, filters)) continue

        allTasks.push(flat)

        const key = t.assigneeId ?? null
        const lane = byAssignee.get(key)
        if (lane) lane.push(flat)
        else byAssignee.set(key, [flat])

        if (t.scheduledDate) {
          const day = byDate.get(t.scheduledDate)
          if (day) day.push(flat)
          else byDate.set(t.scheduledDate, [flat])
          if (!firstDate || t.scheduledDate < firstDate) firstDate = t.scheduledDate
        } else {
          unscheduled.push(flat)
        }
      }
    }

    // Chronological within a day; untimed tasks lead as an all-day band.
    // Ties fall back to plan order so the sort is stable and predictable.
    for (const list of byDate.values()) {
      list.sort(
        (a, b) =>
          compareByTime(a.scheduledTime, b.scheduledTime) ||
          a.milestoneIndex - b.milestoneIndex ||
          a.sortOrder - b.sortOrder,
      )
    }
    for (const list of byAssignee.values()) {
      list.sort(
        (a, b) =>
          (a.scheduledDate ?? '').localeCompare(b.scheduledDate ?? '') ||
          compareByTime(a.scheduledTime, b.scheduledTime) ||
          a.sortOrder - b.sortOrder,
      )
    }

    return {
      roadmap,
      members,
      membersById: new Map(members.map(m => [m.id, m])),
      byDate,
      byAssignee,
      unscheduled,
      allTasks,
      stats: { total, done, pct: total > 0 ? Math.round((done / total) * 100) : 0 },
      firstDate,
      isLoading: roadmapQuery.isLoading || membersQuery.isLoading,
      error: roadmapQuery.error,
    }
  }, [roadmap, members, filters, roadmapQuery.isLoading, roadmapQuery.error, membersQuery.isLoading])
}
