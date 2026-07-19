// apps/web/src/pages/planner/usePlannerMutations.ts
//
// Every write the planner performs, each with the same optimistic shape:
// cancel in-flight reads → snapshot → apply locally → roll back to the
// snapshot on error → invalidate on settle.
//
// That pattern is lifted unchanged from the original PlannerCalendarPage; it
// is what makes drag-drop feel instant despite a round trip.

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useApi } from '../../lib/api'
import type { Roadmap, RoadmapTask, TaskRescheduleItem } from '../../types/roadmap'
import { addTask, mapTask, mapTasks, removeTask } from './plannerCache'
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
}

export interface TaskCreateInput extends TaskPatch {
  title: string
  milestoneId?: string | null
}

export function usePlannerMutations() {
  const { post, patch, del } = useApi()
  const qc = useQueryClient()

  /** Snapshot + optimistically rewrite the cached roadmap. */
  async function optimistic(apply: (rm: Roadmap) => Roadmap) {
    await qc.cancelQueries({ queryKey: ROADMAP_KEY })
    const prev = qc.getQueryData<Roadmap | null>(ROADMAP_KEY)
    if (prev) qc.setQueryData(ROADMAP_KEY, apply(prev))
    return { prev }
  }

  function rollback(ctx: { prev?: Roadmap | null } | undefined) {
    if (ctx?.prev !== undefined) qc.setQueryData(ROADMAP_KEY, ctx.prev)
  }

  /**
   * Lane counts live on the members query, so any write that changes a task's
   * assignee, date, or done-ness invalidates it too — otherwise the sidebar
   * keeps showing a stale "4 scheduled".
   */
  function settleBoth() {
    qc.invalidateQueries({ queryKey: ROADMAP_KEY })
    qc.invalidateQueries({ queryKey: MEMBERS_KEY })
  }

  const generate = useMutation({
    mutationFn: () => post<Roadmap>('/api/roadmap/generate', {}),
    onSuccess: data => qc.setQueryData(ROADMAP_KEY, data),
    onSettled: settleBoth,
  })

  const updateTask = useMutation({
    mutationFn: ({ id, patch: body }: { id: string; patch: TaskPatch }) =>
      patch<RoadmapTask>(`/api/roadmap/tasks/${id}`, body),
    onMutate: ({ id, patch: body }) =>
      optimistic(rm => mapTask(rm, id, t => ({ ...t, ...body }))),
    onError: (_e, _v, ctx) => rollback(ctx),
    onSettled: settleBoth,
  })

  const deleteTask = useMutation({
    mutationFn: (id: string) => del<void>(`/api/roadmap/tasks/${id}`),
    onMutate: (id: string) => optimistic(rm => removeTask(rm, id)),
    onError: (_e, _v, ctx) => rollback(ctx),
    onSettled: settleBoth,
  })

  const createTask = useMutation({
    mutationFn: (input: TaskCreateInput) => post<RoadmapTask>('/api/roadmap/tasks', input),
    onMutate: async (input: TaskCreateInput) => {
      // Optimistic id is temporary; the settle-time invalidate replaces the row
      // with the server's version, so it never leaks into a later mutation.
      const optimisticTask: RoadmapTask = {
        id: `optimistic-${crypto.randomUUID()}`,
        title: input.title,
        description: input.description ?? null,
        status: 'todo',
        sortOrder: Number.MAX_SAFE_INTEGER,
        scheduledDate: input.scheduledDate ?? null,
        scheduledTime: input.scheduledTime ?? null,
        durationMinutes: input.durationMinutes ?? null,
        assigneeId: input.assigneeId ?? null,
      }
      return optimistic(rm => addTask(rm, optimisticTask, input.milestoneId))
    },
    onError: (_e, _v, ctx) => rollback(ctx),
    onSettled: settleBoth,
  })

  const rescheduleTasks = useMutation({
    mutationFn: (updates: TaskRescheduleItem[]) =>
      post<{ tasks: RoadmapTask[] }>('/api/roadmap/tasks/reschedule', { updates }),
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

  return { generate, updateTask, deleteTask, createTask, rescheduleTasks, toggleDone }
}
