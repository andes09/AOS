import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { PROJECTS_KEY } from '../../projects/hooks/useProjects'
import { OnboardingApiError } from '../api'
import type { OnboardingState, PlanSource, ProjectPurpose, TechExperience } from '../types'
import { useOnboardingApi } from './useOnboardingApi'

export const ONBOARDING_STATE_KEY = ['onboarding-v2-state']

/**
 * Single source of truth for the onboarding flow. Wraps GET /state and the
 * step mutations; every mutation response is the full new state, so the cache
 * is updated in one round-trip.
 */
export function useOnboardingState() {
  const api = useOnboardingApi()
  const queryClient = useQueryClient()

  const query = useQuery<OnboardingState>({
    queryKey: ONBOARDING_STATE_KEY,
    queryFn: async () => {
      try {
        return await api.getState()
      } catch (err) {
        // Direct navigation to /onboarding can beat org provisioning; the API
        // signals this with 409 org_not_provisioned. Provision once and retry.
        if (err instanceof OnboardingApiError && err.status === 409) {
          await api.provisionOrganization()
          return api.getState()
        }
        throw err
      }
    },
  })

  const setState = (state: OnboardingState) =>
    queryClient.setQueryData(ONBOARDING_STATE_KEY, state)

  const skipGithub = useMutation({
    mutationFn: () => api.skipGithub(),
    onSuccess: setState,
  })

  const saveProfile = useMutation({
    mutationFn: (profile: { name: string; phone: string }) => api.saveProfile(profile),
    onSuccess: setState,
  })

  const savePurpose = useMutation({
    mutationFn: (purpose: ProjectPurpose) => api.savePurpose(purpose),
    onSuccess: setState,
  })

  const saveTechStack = useMutation({
    mutationFn: ({ stack, experience }: { stack: string[]; experience: TechExperience }) =>
      api.saveTechStack(stack, experience),
    onSuccess: setState,
  })

  const savePlanSource = useMutation({
    mutationFn: (source: PlanSource) => api.savePlanSource(source),
    onSuccess: setState,
  })

  const complete = useMutation({
    mutationFn: () => api.completeOnboarding(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ONBOARDING_STATE_KEY })
      // Onboarding may have just created the org's first project — the
      // project hub's list would otherwise still read as empty.
      queryClient.invalidateQueries({ queryKey: PROJECTS_KEY })
    },
  })

  return {
    /** The derived flow state, or undefined while loading. */
    state: query.data,
    isLoading: query.isLoading,
    error: query.error,
    refresh: query.refetch,
    skipGithub,
    saveProfile,
    savePurpose,
    saveTechStack,
    savePlanSource,
    complete,
  }
}
