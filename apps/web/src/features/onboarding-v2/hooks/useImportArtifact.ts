import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import type { ImportArtifactState, OnboardingState } from '../types'
import { ONBOARDING_STATE_KEY } from './useOnboardingState'
import { useOnboardingApi } from './useOnboardingApi'

export const IMPORT_ARTIFACT_KEY = ['onboarding-v2-import-artifact']

/**
 * The import-a-plan sub-flow: analyze pasted text/files into a project brief
 * + proposed roadmap, review each milestone, then apply the accepted subset.
 *
 * Per-milestone accept/reject state lives here as plain React state — it is
 * NOT round-tripped to the server per toggle, only the final decision is
 * sent on `apply()` (see docs/plans/2026-07-20-import-artifacts.md). Every
 * milestone defaults to accepted.
 */
export function useImportArtifact() {
  const api = useOnboardingApi()
  const queryClient = useQueryClient()
  const [rejected, setRejected] = useState<Set<number>>(new Set())

  const query = useQuery<ImportArtifactState>({
    queryKey: IMPORT_ARTIFACT_KEY,
    queryFn: () => api.getImportState(),
  })

  const setImportState = (state: ImportArtifactState) => {
    queryClient.setQueryData(IMPORT_ARTIFACT_KEY, state)
  }

  const analyze = useMutation({
    mutationFn: (input: { text?: string; files?: File[] }) => {
      const formData = new FormData()
      if (input.text && input.text.trim()) formData.append('text', input.text)
      for (const file of input.files ?? []) formData.append('files', file)
      return api.analyzeImport(formData)
    },
    onSuccess: state => {
      setImportState(state)
      setRejected(new Set()) // every newly-analyzed milestone starts accepted
      // Analyzing updates session.import_analyzed_at/proposed_roadmap, which
      // the overall onboarding state also surfaces (state.importArtifact) —
      // keep that in sync too.
      queryClient.invalidateQueries({ queryKey: ONBOARDING_STATE_KEY })
    },
  })

  const milestones = query.data?.milestones ?? []

  const toggleMilestone = (index: number) => {
    setRejected(prev => {
      const next = new Set(prev)
      if (next.has(index)) next.delete(index)
      else next.add(index)
      return next
    })
  }

  const isAccepted = (index: number) => !rejected.has(index)
  const acceptedCount = milestones.length - rejected.size

  const apply = useMutation({
    mutationFn: (briefOverrides?: Record<string, unknown>) => {
      const acceptedMilestoneIndexes = milestones
        .map((_, index) => index)
        .filter(index => isAccepted(index))
      return api.applyImport({ acceptedMilestoneIndexes, briefOverrides })
    },
    onSuccess: (state: OnboardingState) => {
      queryClient.setQueryData(ONBOARDING_STATE_KEY, state)
    },
  })

  return {
    /** The analyzed brief + proposed roadmap, or undefined before analysis. */
    importState: query.data,
    isLoading: query.isLoading,
    milestones,
    analyze,
    apply,
    isAccepted,
    toggleMilestone,
    acceptedCount,
  }
}
