import { useMemo } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'

import { parseGithubRedirect } from '../api'
import type { GithubRedirectResult } from '../types'
import { ONBOARDING_STATE_KEY } from './useOnboardingState'
import { useOnboardingApi } from './useOnboardingApi'

/**
 * GitHub repo-access connection for onboarding. `connect.mutate()` sends the
 * browser to GitHub's consent screen; GitHub redirects back to `returnTo`
 * with ?github=connected|error, surfaced here as `redirectResult`.
 */
export function useGithubConnect(returnTo: string = '/onboarding') {
  const api = useOnboardingApi()
  const queryClient = useQueryClient()

  const redirectResult: GithubRedirectResult = useMemo(
    () => parseGithubRedirect(window.location.search),
    [],
  )

  const connect = useMutation({
    mutationFn: async () => {
      const { auth_url } = await api.getGithubConnectUrl(returnTo)
      window.location.href = auth_url
    },
  })

  const disconnect = useMutation({
    mutationFn: () => api.disconnectGithub(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ONBOARDING_STATE_KEY }),
  })

  return { connect, disconnect, redirectResult }
}
