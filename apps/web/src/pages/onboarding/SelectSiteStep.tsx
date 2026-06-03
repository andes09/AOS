// apps/web/src/pages/onboarding/SelectSiteStep.tsx

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useApi } from '../../lib/api'

interface SelectSiteStepProps {
  connectionIds: string[]
  onNext: (connectionId: string) => void
  onBack: () => void
}

export function SelectSiteStep({ connectionIds, onNext, onBack }: SelectSiteStepProps) {
  const [selected, setSelected] = useState<string | null>(null)
  const [activating, setActivating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { get, post } = useApi()

  const { data: sites, isLoading } = useQuery({
    queryKey: ['jira-sites', connectionIds.join(',')],
    queryFn: () => get<Array<{ id: string; url: string }>>(
      `/api/integrations/jira/sites?connection_ids=${connectionIds.join(',')}`
    ),
    enabled: connectionIds.length > 0,
  })

  async function handleSelect() {
    if (!selected) return
    setActivating(true)
    setError(null)
    try {
      await post('/api/integrations/jira/activate', { connection_id: selected })
      onNext(selected)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to select site')
      setActivating(false)
    }
  }

  return (
    <div>
      <h2 style={{ color: '#e2e8f0', fontSize: '1.25rem', fontWeight: 700, margin: '0 0 8px' }}>
        Select Jira Site
      </h2>
      <p style={{ color: '#94a3b8', fontSize: 14, marginBottom: '1.5rem', lineHeight: 1.6 }}>
        Your Atlassian account has access to multiple sites. Choose the one Omada should use.
      </p>

      {isLoading && (
        <div style={{ color: '#64748b', fontSize: 14, marginBottom: '1.5rem' }}>Loading sites...</div>
      )}

      {error && (
        <div style={{ color: '#ef4444', fontSize: 13, marginBottom: 12 }}>{error}</div>
      )}

      {sites && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: '1.5rem' }}>
          {sites.map(site => (
            <div
              key={site.id}
              onClick={() => setSelected(site.id)}
              style={{
                padding: '0.75rem 1rem',
                borderRadius: 6,
                border: `2px solid ${selected === site.id ? '#6366f1' : '#2d2f45'}`,
                background: selected === site.id ? '#2d2f45' : 'transparent',
                cursor: 'pointer',
                transition: 'border-color 0.15s, background 0.15s',
              }}
            >
              <div style={{ color: '#e2e8f0', fontSize: 14, fontWeight: 600 }}>
                {site.url.replace('https://', '')}
              </div>
            </div>
          ))}
        </div>
      )}

      <div style={{ display: 'flex', gap: 8 }}>
        <button onClick={onBack} style={ghostButtonStyle}>← Back</button>
        <button
          onClick={handleSelect}
          disabled={!selected || activating}
          style={primaryButtonStyle(!selected || activating ? '#374151' : '#6366f1')}
        >
          {activating ? 'Connecting...' : 'Continue →'}
        </button>
      </div>
    </div>
  )
}

const ghostButtonStyle: React.CSSProperties = {
  background: 'transparent',
  color: '#94a3b8',
  border: '1px solid #2d2f45',
  borderRadius: 6,
  padding: '0.625rem 1rem',
  fontSize: 14,
  cursor: 'pointer',
}

function primaryButtonStyle(bg: string): React.CSSProperties {
  return {
    flex: 1,
    background: bg,
    color: '#fff',
    border: 'none',
    borderRadius: 6,
    padding: '0.625rem 1.25rem',
    fontSize: 14,
    fontWeight: 600,
    cursor: 'pointer',
  }
}
