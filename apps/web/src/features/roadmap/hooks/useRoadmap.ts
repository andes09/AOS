import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { RoadmapApiError } from '../api'
import type { RoadmapMilestone, RoadmapProject, RoadmapState } from '../types'
import { useRoadmapApi } from './useRoadmapApi'

export const ROADMAP_KEY = ['roadmap']

/**
 * Single source of truth for the roadmap. Wraps GET /api/roadmap plus the
 * generation endpoints; generate/regenerate responses are the full new
 * project, so the cache is updated in one round-trip — no refetch needed.
 *
 * Generation is a synchronous (long) HTTP call, so "generating" is simply the
 * mutation being in flight; when it resolves, `state` flips to `ready` with
 * the fresh tree already in place. While it's in flight the query keeps
 * refetching on `pollIntervalMs` (default 5s) so a roadmap generated in
 * another tab — or by the tail end of onboarding — shows up without a reload.
 */
export function useRoadmap(options: { pollIntervalMs?: number } = {}) {
  const api = useRoadmapApi()
  const queryClient = useQueryClient()
  const pollIntervalMs = options.pollIntervalMs ?? 5000

  const query = useQuery<RoadmapProject | null>({
    queryKey: ROADMAP_KEY,
    queryFn: async () => {
      try {
        return await api.getRoadmap()
      } catch (err) {
        // Direct navigation can beat org provisioning; the API signals this
        // with 409 org_not_provisioned. Provision once and retry.
        if (err instanceof RoadmapApiError && err.status === 409) {
          await api.provisionOrganization()
          return api.getRoadmap()
        }
        throw err
      }
    },
    // While nothing exists yet, poll so generation finishing elsewhere
    // (another tab, onboarding hand-off) lands without a manual refresh.
    refetchInterval: q => (q.state.data == null ? pollIntervalMs : false),
  })

  const setProject = (project: RoadmapProject) => queryClient.setQueryData(ROADMAP_KEY, project)

  const generate = useMutation({
    mutationFn: () => api.generate(),
    onSuccess: setProject,
  })

  const regenerate = useMutation({
    mutationFn: () => api.regenerate(),
    onSuccess: setProject,
  })

  const regenerateMilestone = useMutation({
    mutationFn: (milestoneId: string) => api.regenerateMilestone(milestoneId),
    onSuccess: (milestone: RoadmapMilestone) => {
      queryClient.setQueryData<RoadmapProject | null>(ROADMAP_KEY, current =>
        current
          ? {
              ...current,
              milestones: current.milestones.map(m => (m.id === milestone.id ? milestone : m)),
            }
          : current,
      )
    },
  })

  const project = query.data ?? null
  const isGenerating = generate.isPending || regenerate.isPending
  const mutationError = generate.error ?? regenerate.error ?? regenerateMilestone.error

  const state: RoadmapState = query.isLoading
    ? { status: 'loading' }
    : isGenerating
      ? { status: 'generating', project }
      : (query.error ?? mutationError)
        ? { status: 'error', error: (query.error ?? mutationError) as Error, project }
        : project
          ? { status: 'ready', project }
          : { status: 'empty' }

  return {
    /** The derived state union — render from this. */
    state,
    /** The raw project tree (null while loading / empty). */
    project,
    isLoading: query.isLoading,
    error: (query.error ?? mutationError) as Error | null,
    refresh: query.refetch,
    /** POST /generate — first-time generation from the onboarding brief. */
    generate,
    /** POST /regenerate — throw the plan away and replan everything. */
    regenerate,
    /** POST /milestones/{id}/regenerate — replan one milestone's tasks. */
    regenerateMilestone,
    /** The id passed to the in-flight milestone regenerate, for a per-milestone spinner. */
    regeneratingMilestoneId: regenerateMilestone.isPending
      ? (regenerateMilestone.variables ?? null)
      : null,
  }
}
