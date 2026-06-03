// apps/web/src/pages/onboarding/ConnectJiraStep.tsx

import { useJiraOAuth, type OAuthResult } from '../../hooks/useJiraOAuth'

interface ConnectJiraStepProps {
  onNext: (result: OAuthResult) => void
}

export function ConnectJiraStep({ onNext }: ConnectJiraStepProps) {
  const { connect, isConnecting, error } = useJiraOAuth('/onboarding', onNext)

  return (
    <div>
      <h2 style={{ color: '#e2e8f0', fontSize: '1.25rem', fontWeight: 700, margin: '0 0 8px' }}>
        Connect Jira
      </h2>
      <p style={{ color: '#94a3b8', fontSize: 14, marginBottom: '1.5rem', lineHeight: 1.6 }}>
        Connect your Atlassian account so Omada can read your team's tickets and sprint history.
      </p>

      {error && (
        <div style={{ color: '#ef4444', fontSize: 13, marginBottom: 12 }}>{error}</div>
      )}
      <button
        onClick={connect}
        disabled={isConnecting}
        style={primaryButtonStyle(isConnecting ? '#374151' : '#6366f1')}
      >
        {isConnecting ? 'Redirecting...' : 'Connect Atlassian Account →'}
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
