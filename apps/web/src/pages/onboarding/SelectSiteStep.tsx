// apps/web/src/pages/onboarding/SelectSiteStep.tsx

import { useState } from 'react'
import { useApi } from '../../lib/api'

export interface PendingSite {
  id: string
  url: string
}

interface SelectSiteStepProps {
  sites: PendingSite[]
  onNext: (connectionId: string) => void
}

export function SelectSiteStep({ sites, onNext }: SelectSiteStepProps) {
  const [selected, setSelected] = useState<string | null>(null)
  const [activating, setActivating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { post } = useApi()

  async function handleContinue() {
    if (!selected) return
    setActivating(true)
    setError(null)
    try {
      await post('/api/integrations/jira/activate', { connection_id: selected })
      onNext(selected)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to connect site')
      setActivating(false)
    }
  }

  return (
    <div>
      <h2 style={{ color: 'var(--color-text-primary)', fontSize: '1.25rem', fontWeight: 700, margin: '0 0 8px' }}>
        Choose a Jira Site
      </h2>
      <p style={{ color: 'var(--color-text-secondary)', fontSize: 14, marginBottom: '1.5rem', lineHeight: 1.6 }}>
        Your Atlassian account has access to multiple sites. Pick the one you want Omada to use.
      </p>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: '1.5rem' }}>
        {sites.map(site => (
          <div
            key={site.id}
            onClick={() => setSelected(site.id)}
            style={{
              padding: '0.75rem 1rem',
              borderRadius: 6,
              border: `2px solid ${selected === site.id ? 'var(--color-accent)' : 'var(--color-border)'}`,
              background: selected === site.id ? 'var(--color-accent-subtle)' : 'transparent',
              cursor: 'pointer',
              transition: 'border-color 0.15s, background 0.15s',
            }}
          >
            <div style={{ color: 'var(--color-text-primary)', fontSize: 14, fontWeight: 600 }}>
              {site.url.replace('https://', '')}
            </div>
          </div>
        ))}
      </div>

      {error && (
        <div style={{ color: 'var(--color-danger)', fontSize: 13, marginBottom: 12 }}>{error}</div>
      )}

      <button
        onClick={handleContinue}
        disabled={!selected || activating}
        style={{
          width: '100%',
          background: !selected || activating ? 'var(--color-bg-secondary)' : 'var(--color-accent)',
          color: !selected || activating ? 'var(--color-text-muted)' : '#fff',
          border: 'none',
          borderRadius: 6,
          padding: '0.625rem 1.25rem',
          fontSize: 14,
          fontWeight: 600,
          cursor: !selected || activating ? 'not-allowed' : 'pointer',
          transition: 'background 0.15s',
        }}
      >
        {activating ? 'Connecting...' : 'Continue →'}
      </button>
    </div>
  )
}
