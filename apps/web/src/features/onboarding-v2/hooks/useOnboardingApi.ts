import { useMemo } from 'react'
import { useAuth } from '@clerk/clerk-react'

import { createOnboardingApi } from '../api'

const testMode = import.meta.env.VITE_TEST_MODE === 'true'

/** Memoized onboarding API client bound to the Clerk session token. */
export function useOnboardingApi() {
  const { getToken } = useAuth()
  return useMemo(
    () =>
      createOnboardingApi(async () => {
        const token = await getToken()
        // Playwright runs without a Clerk session and mocks the API routes;
        // a dummy token lets the client issue the (intercepted) requests.
        if (!token && testMode) return 'test-token'
        return token
      }),
    [getToken],
  )
}
