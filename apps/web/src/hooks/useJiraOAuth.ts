import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useApi } from '../lib/api'

export function useJiraOAuth(returnTo: string, onSuccess?: (connectionId: string) => void) {
  const [searchParams, setSearchParams] = useSearchParams()
  const [isConnecting, setIsConnecting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { get } = useApi()

  // Backend redirects back here with ?connection_id= after successful OAuth.
  // Dependency array is intentionally empty — this must run exactly once on mount.
  // Adding searchParams/onSuccess as deps would cause a re-entrant loop on each render.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    const connectionId = searchParams.get('connection_id')
    if (connectionId) {
      setSearchParams({}, { replace: true })
      onSuccess?.(connectionId)
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
