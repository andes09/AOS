import { useState, useEffect, useRef } from 'react'
import { useOrganization } from '@clerk/clerk-react'
import { useApi } from '../lib/api'

type Status = 'idle' | 'loading' | 'done' | 'error'

/**
 * Calls POST /api/organizations once after the user has an active Clerk org.
 * Re-provisions if the active org switches.
 * Returns onboardingCompleted=false when the user still needs to walk the onboarding flow
 * (either brand new, or started but never finished).
 */
export function useProvisionOrg() {
  const { organization } = useOrganization()
  const api = useApi()
  const [status, setStatus] = useState<Status>('idle')
  const [onboardingCompleted, setOnboardingCompleted] = useState(true)
  const provisionedOrgId = useRef<string | null>(null)

  useEffect(() => {
    if (!organization) return

    if (provisionedOrgId.current === organization.id) return

    if (provisionedOrgId.current !== null) {
      provisionedOrgId.current = null
    }

    let cancelled = false
    setStatus('loading')
    api
      .post<{ orgId: string; teamId: string; isNew: boolean; onboardingCompleted: boolean }>(
        '/api/organizations',
        { name: organization.name },
      )
      .then((res) => {
        if (!cancelled) {
          provisionedOrgId.current = organization.id
          setOnboardingCompleted(res.onboardingCompleted)
          setStatus('done')
        }
      })
      .catch(() => { if (!cancelled) setStatus('error') })

    return () => { cancelled = true }
  }, [organization?.id])

  return { provisioned: status === 'done', onboardingCompleted, error: status === 'error' }
}
