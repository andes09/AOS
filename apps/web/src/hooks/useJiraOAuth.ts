import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useApi } from '../lib/api'

export function useJiraOAuth(returnTo: string, onSuccess?: (connectionId: string) => void) {
  const [searchParams, setSearchParams] = useSearchParams()
  const [isConnecting, setIsConnecting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { get } = useApi()

  // Runs exactly once on mount — intentionally empty deps to avoid re-entrant loop.
  // ?connection_id  → single active connection (single-site OAuth)
  // ?pending_sites  → comma-separated "id|url" pairs (multi-site OAuth);
  //                   we extract just the IDs and join them so SelectBoardStep
  //                   can fetch boards from all sites at once.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    const connectionId = searchParams.get('connection_id')
    const pendingSites = searchParams.get('pending_sites')

    if (connectionId) {
      setSearchParams({}, { replace: true })
      onSuccess?.(connectionId)
    } else if (pendingSites) {
      setSearchParams({}, { replace: true })
      const ids = pendingSites.split(',').map(entry => entry.split('|')[0]).join(',')
      onSuccess?.(ids)
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
