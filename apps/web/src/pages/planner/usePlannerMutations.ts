// apps/web/src/pages/planner/usePlannerMutations.ts
//
// Every write the planner performs, each with the same optimistic shape:
// cancel in-flight reads → snapshot → apply locally → roll back to the
// snapshot on error → invalidate on settle.
//
// That pattern is lifted unchanged from the original PlannerCalendarPage; it
// is what makes drag-drop feel instant despite a round trip.

import { useParams } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useApi } from '../../lib/api'
import type { Roadmap, RoadmapTask, TaskRescheduleItem } from '../../types/roadmap'
import { addTask, mapTask, mapTasks } from './plannerCache'
import { MEMBERS_KEY, ROADMAP_KEY } from './usePlannerData'

/** Fields a single-task PATCH may carry. Omitted keys mean "leave alone". */
export interface TaskPatch {
  status?: RoadmapTask['status']
  title?: string
  description?: string | null
  scheduledDate?: string | null
  scheduledTime?: string | null
  durationMinutes?: number | null
  assigneeId?: string | null
  feedback?: string | null
}

export interface TaskCreateInput extends TaskPatch {
  title: string
  milestoneId?: string | null
}

export function usePlannerMutations() {
  const { post, patch } = useApi()
  const qc = useQueryClient()
  const { projectId } = useParams<{ projectId: string }>()
  if (!projectId) throw new Error('usePlannerMutations must be used within a /projects/:projectId route')

  const roadmapKey = ROADMAP_KEY(projectId)
  const membersKey = MEMBERS_KEY(projectId)
  const base = `/api/projects/${projectId}/roadmap`

  /** Snapshot + optimistically rewrite the cached roadmap. */
  async function optimistic(apply: (rm: Roadmap) => Roadmap) {
    await qc.cancelQueries({ queryKey: roadmapKey })
    const prev = qc.getQueryData<Roadmap | null>(roadmapKey)
    if (prev) qc.setQueryData(roadmapKey, apply(prev))
    return { prev }
  }

  function rollback(ctx: { prev?: Roadmap | null } | undefined) {
    if (ctx?.prev !== undefined) qc.setQueryData(roadmapKey, ctx.prev)
  }

  /**
   * Lane counts live on the members query, so any write that changes a task's
   * assignee, date, or done-ness invalidates it too — otherwise the sidebar
   * keeps showing a stale "4 scheduled".
   */
  function settleBoth() {
    qc.invalidateQueries({ queryKey: roadmapKey })
    qc.invalidateQueries({ queryKey: membersKey })
  }

  const generate = useMutation({
    mutationFn: () => post<Roadmap>(`${base}/generate`, {}),
    onSuccess: data => qc.setQueryData(roadmapKey, data),
    onSettled: settleBoth,
  })

  // Rebuild the whole plan from the (possibly refined) brief. Destructive: the
  // server replans milestones/tasks, so assignee + time customizations on the
  // current tasks are lost. Gated behind an explicit user action in the UI.
  const regenerate = useMutation({
    mutationFn: () => post<Roadmap>(`${base}/regenerate`, {}),
    onSuccess: data => qc.setQueryData(roadmapKey, data),
    onSettled: settleBoth,
  })

  // Non-destructive re-plan from per-task feedback (Groq). Preserves done and
  // in-progress tasks; only upcoming todo tasks change.
  const adjust = useMutation({
    mutationFn: () => post<Roadmap>(`${base}/adjust`, {}),
    onSuccess: data => qc.setQueryData(roadmapKey, data),
    onSettled: settleBoth,
  })

  const updateTask = useMutation({
    mutationFn: ({ id, patch: body }: { id: string; patch: TaskPatch }) =>
      patch<RoadmapTask>(`${base}/tasks/${id}`, body),
    onMutate: ({ id, patch: body }) =>
      optimistic(rm => mapTask(rm, id, t => ({ ...t, ...body }))),
    onError: (_e, _v, ctx) => rollback(ctx),
    onSettled: settleBoth,
  })

  const createTask = useMutation({
    mutationFn: (input: TaskCreateInput) => post<RoadmapTask>(`${base}/tasks`, input),
    onMutate: async (input: TaskCreateInput) => {
      // Optimistic id is temporary; the settle-time invalidate replaces the row
      // with the server's version, so it never leaks into a later mutation.
      const optimisticTask: RoadmapTask = {
        id: `optimistic-${crypto.randomUUID()}`,
        // The server allocates short_id atomically; the settle-time
        // invalidate replaces this optimistic row with the real one.
        shortId: null,
        title: input.title,
        description: input.description ?? null,
        status: 'todo',
        sortOrder: Number.MAX_SAFE_INTEGER,
        scheduledDate: input.scheduledDate ?? null,
        scheduledTime: input.scheduledTime ?? null,
        durationMinutes: input.durationMinutes ?? null,
        dependsOn: [],
        assigneeId: input.assigneeId ?? null,
        feedback: null,
      }
      return optimistic(rm => addTask(rm, optimisticTask, input.milestoneId))
    },
    onError: (_e, _v, ctx) => rollback(ctx),
    onSettled: settleBoth,
  })

  const rescheduleTasks = useMutation({
    mutationFn: (updates: TaskRescheduleItem[]) =>
      post<{ tasks: RoadmapTask[] }>(`${base}/tasks/reschedule`, { updates }),
    onMutate: (updates: TaskRescheduleItem[]) => optimistic(rm => mapTasks(rm, updates)),
    onError: (_e, _v, ctx) => rollback(ctx),
    onSettled: settleBoth,
  })

  /** Convenience for the card checkbox — the planner's most frequent write. */
  function toggleDone(task: Pick<RoadmapTask, 'id' | 'status'>) {
    updateTask.mutate({
      id: task.id,
      patch: { status: task.status === 'done' ? 'todo' : 'done' },
    })
  }

  return { generate, regenerate, adjust, updateTask, createTask, rescheduleTasks, toggleDone }
}
