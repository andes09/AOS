// apps/web/src/pages/onboarding/SaveAnthropicKeyStep.tsx

import { useState } from 'react'
import { useApi } from '../../lib/api'

interface SaveAnthropicKeyStepProps {
  onNext: () => void
  onBack: () => void
}

function maskKey(key: string): string {
  if (key.length < 12) return key
  return `${key.slice(0, 7)}...${key.slice(-4)}`
}

export function SaveAnthropicKeyStep({ onNext, onBack }: SaveAnthropicKeyStepProps) {
  const [key, setKey] = useState('')
  const [savedMasked, setSavedMasked] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { post } = useApi()

  async function handleSave() {
    if (!key.trim()) return
    setSaving(true)
    setError(null)
    try {
      await post('/api/settings/anthropic-key', { key: key.trim() })
      setSavedMasked(maskKey(key.trim()))
      setKey('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save key')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div>
      <h2 style={{ color: '#e2e8f0', fontSize: '1.25rem', fontWeight: 700, margin: '0 0 8px' }}>
        Anthropic API Key
      </h2>
      <p style={{ color: '#94a3b8', fontSize: 14, marginBottom: '1.5rem', lineHeight: 1.6 }}>
        Omada uses Claude to help generate sprint plans. Paste your Anthropic API key — it is stored encrypted.
      </p>

      {savedMasked ? (
        <div style={{ marginBottom: '1.5rem' }}>
          <div style={{ color: '#4ade80', fontSize: 13, marginBottom: 8 }}>✓ Key saved</div>
          <div style={{
            padding: '0.5rem 0.75rem',
            background: '#0f1117',
            borderRadius: 4,
            fontFamily: 'monospace',
            fontSize: 13,
            color: '#a5b4fc',
            border: '1px solid #2d2f45',
          }}>
            {savedMasked}
          </div>
        </div>
      ) : (
        <div style={{ marginBottom: '1.5rem' }}>
          {error && (
            <div style={{ color: '#ef4444', fontSize: 13, marginBottom: 8 }}>{error}</div>
          )}
          <input
            type="password"
            value={key}
            onChange={e => setKey(e.target.value)}
            placeholder="sk-ant-..."
            style={{
              width: '100%',
              background: '#0f1117',
              border: '1px solid #2d2f45',
              borderRadius: 6,
              padding: '0.625rem 0.75rem',
              color: '#e2e8f0',
              fontSize: 14,
              fontFamily: 'monospace',
              boxSizing: 'border-box',
              marginBottom: 8,
              outline: 'none',
            }}
          />
          <button
            onClick={handleSave}
            disabled={!key.trim() || saving}
            style={{
              width: '100%',
              background: !key.trim() || saving ? '#374151' : '#6366f1',
              color: '#fff',
              border: 'none',
              borderRadius: 6,
              padding: '0.625rem 1.25rem',
              fontSize: 14,
              fontWeight: 600,
              cursor: !key.trim() || saving ? 'default' : 'pointer',
            }}
          >
            {saving ? 'Saving...' : 'Save Key'}
          </button>
        </div>
      )}

      <div style={{ display: 'flex', gap: 8 }}>
        <button onClick={onBack} style={ghostButtonStyle}>← Back</button>
        <button
          onClick={onNext}
          disabled={!savedMasked}
          style={{
            flex: 1,
            background: savedMasked ? '#6366f1' : '#374151',
            color: '#fff',
            border: 'none',
            borderRadius: 6,
            padding: '0.625rem 1.25rem',
            fontSize: 14,
            fontWeight: 600,
            cursor: savedMasked ? 'pointer' : 'default',
          }}
        >
          Finish Setup →
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
