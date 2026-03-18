// apps/web/src/pages/onboarding/ConnectJiraStep.tsx

import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useApi } from '../../lib/api'

interface ConnectJiraStepProps {
  onNext: (connectionId: string) => void
}

export function ConnectJiraStep({ onNext }: ConnectJiraStepProps) {
  const [searchParams, setSearchParams] = useSearchParams()
  const [status, setStatus] = useState<'idle' | 'loading' | 'error'>('idle')
  const [error, setError] = useState<string | null>(null)
  const { get } = useApi()

  // Backend redirects back here with ?connection_id= after successful OAuth.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    const connectionId = searchParams.get('connection_id')
    if (connectionId) {
      setSearchParams({}, { replace: true }) // strip param from URL
      onNext(connectionId)
    }
  }, [])

  async function handleConnect() {
    setStatus('loading')
    setError(null)
    try {
      const data = await get<{ auth_url: string }>('/api/integrations/jira/connect')
      window.location.href = data.auth_url
    } catch (err) {
      setStatus('error')
      setError(err instanceof Error ? err.message : 'Failed to initiate Jira connection')
    }
  }

  return (
    <div>
      <h2 style={{ color: '#e2e8f0', fontSize: '1.25rem', fontWeight: 700, margin: '0 0 8px' }}>
        Connect Jira
      </h2>
      <p style={{ color: '#94a3b8', fontSize: 14, marginBottom: '1.5rem', lineHeight: 1.6 }}>
        Connect your Atlassian account so Sprint Brain can read your team's tickets and sprint history.
      </p>

      {error && (
        <div style={{ color: '#ef4444', fontSize: 13, marginBottom: 12 }}>{error}</div>
      )}
      <button
        onClick={handleConnect}
        disabled={status === 'loading'}
        style={primaryButtonStyle(status === 'loading' ? '#374151' : '#6366f1')}
      >
        {status === 'loading' ? 'Redirecting...' : 'Connect Atlassian Account →'}
      </button>
    </div>
  )
}

function primaryButtonStyle(bg: string): React.CSSProperties {
  return {
    background: bg,
    color: '#fff',
    border: 'none',
    borderRadius: 6,
    padding: '0.625rem 1.25rem',
    fontSize: 14,
    fontWeight: 600,
    cursor: 'pointer',
    width: '100%',
  }
}
