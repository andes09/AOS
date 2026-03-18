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

    // Reset status when org switches so the new org gets provisioned
    if (provisionedOrgId.current !== null && provisionedOrgId.current !== organization.id) {
      setStatus('idle')
    }

    if (status !== 'idle') return

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

    return () => { cancelled = true }
  }, [organization?.id, status]) // include status so effect re-runs after reset

  return { provisioned: status === 'done', error: status === 'error' }
}
