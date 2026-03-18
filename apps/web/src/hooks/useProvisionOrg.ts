import { useState, useEffect, useRef } from 'react'
import { useOrganization } from '@clerk/clerk-react'
import { useApi } from '../lib/api'

type Status = 'idle' | 'loading' | 'done' | 'error'

/**
 * Calls POST /api/organizations once after the user has an active Clerk org.
 * Re-provisions if the active org switches.
 * Returns isNew=true when the org was just created (first-time user).
 */
export function useProvisionOrg() {
  const { organization } = useOrganization()
  const api = useApi()
  const [status, setStatus] = useState<Status>('idle')
  const [isNew, setIsNew] = useState(false)
  const provisionedOrgId = useRef<string | null>(null)

  useEffect(() => {
    if (!organization) return

    // Already provisioned for this org — nothing to do
    if (provisionedOrgId.current === organization.id) return

    // Org switched — reset ref so we re-provision for the new org
    if (provisionedOrgId.current !== null) {
      provisionedOrgId.current = null
    }

    let cancelled = false
    setStatus('loading')
    api
      .post<{ orgId: string; teamId: string; isNew: boolean }>('/api/organizations', { name: organization.name })
      .then((res) => {
        if (!cancelled) {
          provisionedOrgId.current = organization.id
          setIsNew(res.isNew)
          setStatus('done')
        }
      })
      .catch(() => { if (!cancelled) setStatus('error') })

    return () => { cancelled = true }
  }, [organization?.id])

  return { provisioned: status === 'done', isNew, error: status === 'error' }
}
