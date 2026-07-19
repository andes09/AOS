import { useMutation, useQueryClient } from '@tanstack/react-query'

import type { RoadmapProject, RoadmapTask, TaskUpdate } from '../types'
import { ROADMAP_KEY } from './useRoadmap'
import { useRoadmapApi } from './useRoadmapApi'

// ─── pure cache-tree helpers ────────────────────────────────────────────────

/** Re-number a task list so sortOrder matches array position (server invariant). */
const renumber = (tasks: RoadmapTask[]): RoadmapTask[] =>
  tasks.map((t, idx) => (t.sortOrder === idx ? t : { ...t, sortOrder: idx }))

/**
 * Apply a TaskUpdate to the cached project tree the same way the server
 * applies it: field merge, plus a sibling reshuffle when sortOrder moves.
 */
function applyTaskUpdate(
  project: RoadmapProject,
  taskId: string,
  patch: TaskUpdate,
): RoadmapProject {
  return {
    ...project,
    milestones: project.milestones.map(milestone => {
      const index = milestone.tasks.findIndex(t => t.id === taskId)
      if (index === -1) return milestone
      const { sortOrder, ...fields } = patch
      let tasks = milestone.tasks.map(t => (t.id === taskId ? { ...t, ...fields } : t))
      if (sortOrder !== undefined) {
        const clamped = Math.max(0, Math.min(sortOrder, tasks.length - 1))
        const [moved] = tasks.splice(index, 1)
        tasks.splice(clamped, 0, moved)
        tasks = renumber(tasks)
      }
      return { ...milestone, tasks }
    }),
  }
}

function removeTask(project: RoadmapProject, taskId: string): RoadmapProject {
  return {
    ...project,
    milestones: project.milestones.map(milestone =>
      milestone.tasks.some(t => t.id === taskId)
        ? { ...milestone, tasks: renumber(milestone.tasks.filter(t => t.id !== taskId)) }
        : milestone,
    ),
  }
}

// ─── hook ───────────────────────────────────────────────────────────────────

/**
 * Task-level mutations with optimistic updates against the useRoadmap cache.
 * The UI updates instantly (check-off, retitle, reschedule, reorder, delete)
 * and rolls back automatically if the server rejects the change.
 */
export function useTaskMutations() {
  const api = useRoadmapApi()
  const queryClient = useQueryClient()

  const snapshotAndApply = async (apply: (p: RoadmapProject) => RoadmapProject) => {
    await queryClient.cancelQueries({ queryKey: ROADMAP_KEY })
    const previous = queryClient.getQueryData<RoadmapProject | null>(ROADMAP_KEY)
    if (previous) queryClient.setQueryData(ROADMAP_KEY, apply(previous))
    return { previous }
  }

  const rollback = (context?: { previous?: RoadmapProject | null }) => {
    if (context?.previous !== undefined) queryClient.setQueryData(ROADMAP_KEY, context.previous)
  }

  const updateTask = useMutation({
    mutationFn: ({ taskId, patch }: { taskId: string; patch: TaskUpdate }) =>
      api.updateTask(taskId, patch),
    onMutate: ({ taskId, patch }) => snapshotAndApply(p => applyTaskUpdate(p, taskId, patch)),
    onError: (_err, _vars, context) => rollback(context),
    onSuccess: (task, { patch }) => {
      // Merge the server's copy of the task (it may normalize, e.g. trim the
      // title). A reorder also reshuffled siblings server-side — our optimistic
      // reshuffle mirrors that logic, but refetch to guarantee convergence.
      queryClient.setQueryData<RoadmapProject | null>(ROADMAP_KEY, current =>
        current
          ? {
              ...current,
              milestones: current.milestones.map(m =>
                m.tasks.some(t => t.id === task.id)
                  ? { ...m, tasks: m.tasks.map(t => (t.id === task.id ? { ...t, ...task } : t)) }
                  : m,
              ),
            }
          : current,
      )
      if (patch.sortOrder !== undefined) {
        queryClient.invalidateQueries({ queryKey: ROADMAP_KEY })
      }
    },
  })

  const deleteTask = useMutation({
    mutationFn: (taskId: string) => api.deleteTask(taskId),
    onMutate: (taskId: string) => snapshotAndApply(p => removeTask(p, taskId)),
    onError: (_err, _vars, context) => rollback(context),
  })

  return {
    /** updateTask.mutate({ taskId, patch }) — see TaskUpdate for patch semantics. */
    updateTask,
    /** deleteTask.mutate(taskId) — removes the task optimistically. */
    deleteTask,
    /** Convenience: flip a task's status (the check-off interaction). */
    setTaskStatus: (taskId: string, status: RoadmapTask['status']) =>
      updateTask.mutate({ taskId, patch: { status } }),
  }
}
