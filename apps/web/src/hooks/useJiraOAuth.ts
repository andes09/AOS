import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useApi } from '../lib/api'

export interface PendingSite { id: string; url: string }

export type OAuthResult =
  | { type: 'single'; connectionId: string }
  | { type: 'multi'; sites: PendingSite[] }

export function useJiraOAuth(returnTo: string, onSuccess?: (result: OAuthResult) => void) {
  const [searchParams, setSearchParams] = useSearchParams()
  const [isConnecting, setIsConnecting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { get } = useApi()

  // Runs exactly once on mount — intentionally empty deps to avoid re-entrant loop.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    const connectionId = searchParams.get('connection_id')
    const pendingSites = searchParams.get('pending_sites')

    if (connectionId) {
      setSearchParams({}, { replace: true })
      onSuccess?.({ type: 'single', connectionId })
    } else if (pendingSites) {
      setSearchParams({}, { replace: true })
      const sites: PendingSite[] = pendingSites.split(',').map(entry => {
        const [id, url] = entry.split('|')
        return { id, url }
      })
      onSuccess?.({ type: 'multi', sites })
    }
  }, [])

  async function connect() {
    setIsConnecting(true)
    setError(null)
    try {
      const data = await get<{ auth_url: string }>(
        `/api/integrations/jira/connect?return_to=${encodeURIComponent(returnTo)}`
      )
      window.location.href = data.auth_url
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to initiate Jira connection')
      setIsConnecting(false)
    }
  }

  return { connect, isConnecting, error }
}
