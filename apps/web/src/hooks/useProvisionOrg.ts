import { useState, useEffect, useRef } from 'react'
import { useOrganization } from '@clerk/clerk-react'
import { useApi } from '../lib/api'

type Status = 'idle' | 'loading' | 'done' | 'error'

/**
 * Calls POST /api/organizations once after the user has an active Clerk org.
 * Re-provisions if the active org switches.
 */
export function useProvisionOrg() {
  const { organization } = useOrganization()
  const api = useApi()
  const [status, setStatus] = useState<Status>('idle')
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
      .post('/api/organizations', { name: organization.name })
      .then(() => {
        if (!cancelled) {
          provisionedOrgId.current = organization.id
          setStatus('done')
        }
      })
      .catch(() => { if (!cancelled) setStatus('error') })

    // On cleanup (Strict Mode re-run or org switch), cancel the in-flight request
    return () => { cancelled = true }
  }, [organization?.id])

  return { provisioned: status === 'done', error: status === 'error' }
}
