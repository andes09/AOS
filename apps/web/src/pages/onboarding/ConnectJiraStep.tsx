// apps/web/src/pages/onboarding/ConnectJiraStep.tsx

import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useApi } from '../../lib/api'

interface ConnectJiraStepProps {
  onNext: () => void
}

export function ConnectJiraStep({ onNext }: ConnectJiraStepProps) {
  const [searchParams] = useSearchParams()
  const [status, setStatus] = useState<'idle' | 'loading' | 'connected' | 'error'>('idle')
  const [error, setError] = useState<string | null>(null)
  const { get, post } = useApi()

  // Atlassian redirects back to this page with ?code= after the user grants access.
  // We exchange the code with our backend, then show success.
  useEffect(() => {
    const code = searchParams.get('code')
    if (code && status === 'idle') {
      setStatus('loading')
      post<void>('/api/jira/oauth/callback', { code })
        .then(() => setStatus('connected'))
        .catch(err => {
          setStatus('error')
          setError(err instanceof Error ? err.message : 'Failed to connect Jira')
        })
    }
  }, [searchParams])

  async function handleConnect() {
    setStatus('loading')
    setError(null)
    try {
      const data = await get<{ url: string }>('/api/jira/oauth/initiate')
      window.location.href = data.url
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

      {status === 'connected' ? (
        <div>
          <div style={{ color: '#4ade80', fontSize: 14, marginBottom: '1rem' }}>
            ✓ Jira connected successfully
          </div>
          <button onClick={onNext} style={primaryButtonStyle('#6366f1')}>
            Continue →
          </button>
        </div>
      ) : (
        <div>
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
      )}
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
