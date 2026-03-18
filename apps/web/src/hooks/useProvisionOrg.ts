import { useState, useEffect } from 'react'
import { useOrganization } from '@clerk/clerk-react'
import { useApi } from '../lib/api'

type Status = 'idle' | 'loading' | 'done' | 'error'

/**
 * Calls POST /api/organizations once after the user has an active Clerk org.
 * Subsequent calls are no-ops (the endpoint is idempotent).
 */
export function useProvisionOrg() {
  const { organization } = useOrganization()
  const api = useApi()
  const [status, setStatus] = useState<Status>('idle')

  useEffect(() => {
    if (!organization || status !== 'idle') return

    let cancelled = false
    setStatus('loading')
    api
      .post('/api/organizations', { name: organization.name })
      .then(() => { if (!cancelled) setStatus('done') })
      .catch(() => { if (!cancelled) setStatus('error') })

    return () => { cancelled = true }
  }, [organization?.id]) // re-run if org switches

  return { provisioned: status === 'done', error: status === 'error' }
}
