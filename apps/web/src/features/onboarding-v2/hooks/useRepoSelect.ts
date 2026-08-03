import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import type { GithubRepo } from '../types'
import { ONBOARDING_STATE_KEY } from './useOnboardingState'
import { useOnboardingApi } from './useOnboardingApi'

/**
 * The repo-select onboarding step: lists repos the org's GitHub connection
 * can access (finally wiring up `listGithubRepos`, previously dead code —
 * see docs/plans/2026-07-20-import-artifacts.md) and lets the user pick one
 * or skip.
 */
export function useRepoSelect() {
  const api = useOnboardingApi()
  const queryClient = useQueryClient()
  const [page, setPage] = useState(1)

  const repos = useQuery<GithubRepo[]>({
    queryKey: ['onboarding-v2-github-repos', page],
    queryFn: () => api.listGithubRepos(page),
  })

  const selectRepo = useMutation({
    mutationFn: (repoFullName: string) => api.setRepo(repoFullName),
    onSuccess: state => queryClient.setQueryData(ONBOARDING_STATE_KEY, state),
  })

  const skip = useMutation({
    mutationFn: () => api.skipRepo(),
    onSuccess: state => queryClient.setQueryData(ONBOARDING_STATE_KEY, state),
  })

  const createRepo = useMutation({
    mutationFn: ({ name, isPrivate }: { name: string; isPrivate: boolean }) =>
      api.createRepo(name, isPrivate),
    onSuccess: state => queryClient.setQueryData(ONBOARDING_STATE_KEY, state),
  })

  return { repos, page, setPage, selectRepo, skip, createRepo }
}
