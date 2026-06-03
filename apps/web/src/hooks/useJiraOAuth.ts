import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useApi } from '../lib/api'

export type OAuthResult =
  | { type: 'single'; connectionId: string }
  | { type: 'multi'; connectionIds: string[] }

export function useJiraOAuth(returnTo: string, onSuccess?: (result: OAuthResult) => void) {
  const [searchParams, setSearchParams] = useSearchParams()
  const [isConnecting, setIsConnecting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { get } = useApi()

  // Backend redirects back here with ?connection_id= (single site) or
  // ?connection_ids= (multiple sites). Runs exactly once on mount — adding
  // searchParams/onSuccess as deps would cause a re-entrant loop.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    const connectionId = searchParams.get('connection_id')
    const connectionIds = searchParams.get('connection_ids')
    if (connectionId) {
      setSearchParams({}, { replace: true })
      onSuccess?.({ type: 'single', connectionId })
    } else if (connectionIds) {
      setSearchParams({}, { replace: true })
      onSuccess?.({ type: 'multi', connectionIds: connectionIds.split(',') })
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
