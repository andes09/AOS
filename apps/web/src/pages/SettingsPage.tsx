import { useState, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useApi } from '../lib/api'

interface JiraStatus {
  connected: boolean
  cloud_url?: string
  last_synced_at?: string | null
}

export function SettingsPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [status, setStatus] = useState<JiraStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [actionError, setActionError] = useState<string | null>(null)
  const [actionLoading, setActionLoading] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [syncMessage, setSyncMessage] = useState<string | null>(null)
  const [anthropicKey, setAnthropicKey] = useState('')
  const [anthropicConfigured, setAnthropicConfigured] = useState<boolean | null>(null)
  const [anthropicSaving, setAnthropicSaving] = useState(false)
  const [anthropicMessage, setAnthropicMessage] = useState<string | null>(null)
  const { get, del, post } = useApi()

  async function fetchStatus() {
    try {
      const data = await get<JiraStatus>('/api/integrations/jira/status')
      setStatus(data)
    } catch {
      setStatus({ connected: false })
    } finally {
      setLoading(false)
    }
  }

  async function fetchAnthropicStatus() {
    try {
      const data = await get<{ configured: boolean }>('/api/settings/anthropic-key/status')
      setAnthropicConfigured(data.configured)
    } catch {
      setAnthropicConfigured(false)
    }
  }

  useEffect(() => {
    fetchStatus()
    fetchAnthropicStatus()
    // If we just returned from an OAuth flow, strip the connection_id param
    if (searchParams.get('connection_id')) {
      setSearchParams({}, { replace: true })
    }
  }, [])

  async function handleDisconnect() {
    setActionLoading(true)
    setActionError(null)
    try {
      await del('/api/integrations/jira/disconnect')
      await fetchStatus()
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Failed to disconnect')
    } finally {
      setActionLoading(false)
    }
  }

  async function handleSync() {
    setSyncing(true)
    setSyncMessage(null)
    try {
      const org = await post<{ teamId: string }>('/api/organizations', { name: 'My Org' })
      await post(`/api/integrations/jira/sync?team_id=${org.teamId}`, {})
      setSyncMessage('Sync queued — data will update shortly.')
      setTimeout(() => {
        fetchStatus()
        setSyncMessage(null)
      }, 3000)
    } catch (err) {
      setSyncMessage(err instanceof Error ? err.message : String(err) || 'Sync failed')
    } finally {
      setSyncing(false)
    }
  }

  async function handleConnect() {
    setActionLoading(true)
    setActionError(null)
    try {
      const data = await get<{ auth_url: string }>('/api/integrations/jira/connect')
      window.location.href = data.auth_url
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Failed to initiate connection')
      setActionLoading(false)
    }
  }

  async function handleSaveAnthropicKey() {
    if (!anthropicKey.trim()) return
    setAnthropicSaving(true)
    setAnthropicMessage(null)
    try {
      await post('/api/settings/anthropic-key', { key: anthropicKey.trim() })
      setAnthropicMessage('API key saved.')
      setAnthropicKey('')
      setAnthropicConfigured(true)
    } catch (err) {
      setAnthropicMessage(err instanceof Error ? err.message : 'Failed to save key')
    } finally {
      setAnthropicSaving(false)
    }
  }

  return (
    <div style={{ maxWidth: 640, margin: '0 auto', padding: '2rem 1.5rem' }}>
      <h1 style={{ color: '#e2e8f0', fontSize: '1.5rem', fontWeight: 700, marginBottom: '2rem' }}>
        Settings
      </h1>

      {/* Jira Connection Card */}
      <div style={{
        background: '#1e2030',
        border: '1px solid #2d2f45',
        borderRadius: 8,
        padding: '1.25rem 1.5rem',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1rem' }}>
          <h2 style={{ color: '#e2e8f0', fontSize: '1rem', fontWeight: 600, margin: 0 }}>
            Jira Connection
          </h2>
          {!loading && status && (
            <span style={{
              fontSize: 12,
              fontWeight: 600,
              padding: '2px 10px',
              borderRadius: 999,
              background: status.connected ? '#14532d' : '#1e293b',
              color: status.connected ? '#4ade80' : '#64748b',
              border: `1px solid ${status.connected ? '#166534' : '#2d2f45'}`,
            }}>
              {status.connected ? 'Connected' : 'Not connected'}
            </span>
          )}
        </div>

        {loading ? (
          <div style={{ color: '#64748b', fontSize: 14 }}>Loading...</div>
        ) : status?.connected ? (
          <div>
            <div style={{ color: '#94a3b8', fontSize: 13, marginBottom: 4 }}>
              {status.cloud_url}
            </div>
            <div style={{ color: '#64748b', fontSize: 12, marginBottom: '1rem' }}>
              Last synced:{' '}
              {status.last_synced_at
                ? new Date(status.last_synced_at).toLocaleString()
                : 'Never'}
            </div>
            {syncMessage && (
              <div style={{ color: syncMessage.includes('failed') ? '#ef4444' : '#4ade80', fontSize: 13, marginBottom: 8 }}>{syncMessage}</div>
            )}
            {actionError && (
              <div style={{ color: '#ef4444', fontSize: 13, marginBottom: 8 }}>{actionError}</div>
            )}
            <div style={{ display: 'flex', gap: 8 }}>
            <button
              onClick={handleSync}
              disabled={syncing}
              style={{
                background: syncing ? '#374151' : '#1e3a5f',
                color: syncing ? '#64748b' : '#60a5fa',
                border: '1px solid #1d4ed8',
                borderRadius: 6,
                padding: '0.5rem 1rem',
                fontSize: 13,
                fontWeight: 600,
                cursor: syncing ? 'not-allowed' : 'pointer',
              }}
            >
              {syncing ? 'Syncing...' : 'Sync Now'}
            </button>
            <button
              onClick={handleDisconnect}
              disabled={actionLoading}
              style={{
                background: 'transparent',
                color: '#ef4444',
                border: '1px solid #ef4444',
                borderRadius: 6,
                padding: '0.5rem 1rem',
                fontSize: 13,
                fontWeight: 600,
                cursor: actionLoading ? 'not-allowed' : 'pointer',
                opacity: actionLoading ? 0.6 : 1,
              }}
            >
              {actionLoading ? 'Disconnecting...' : 'Disconnect'}
            </button>
            </div>
          </div>
        ) : (
          <div>
            <p style={{ color: '#64748b', fontSize: 13, marginBottom: '1rem', margin: '0 0 1rem' }}>
              Connect your Atlassian account to enable sprint syncing.
            </p>
            {actionError && (
              <div style={{ color: '#ef4444', fontSize: 13, marginBottom: 8 }}>{actionError}</div>
            )}
            <button
              onClick={handleConnect}
              disabled={actionLoading}
              style={{
                background: actionLoading ? '#374151' : '#6366f1',
                color: '#fff',
                border: 'none',
                borderRadius: 6,
                padding: '0.5rem 1.25rem',
                fontSize: 13,
                fontWeight: 600,
                cursor: actionLoading ? 'not-allowed' : 'pointer',
              }}
            >
              {actionLoading ? 'Redirecting...' : 'Connect Jira'}
            </button>
          </div>
        )}
      </div>
      {/* Anthropic API Key Card */}
      <div style={{
        background: '#1e2030',
        border: '1px solid #2d2f45',
        borderRadius: 8,
        padding: '1.25rem 1.5rem',
        marginTop: '1.25rem',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1rem' }}>
          <h2 style={{ color: '#e2e8f0', fontSize: '1rem', fontWeight: 600, margin: 0 }}>
            Anthropic API Key
          </h2>
          {anthropicConfigured !== null && (
            <span style={{
              fontSize: 12,
              fontWeight: 600,
              padding: '2px 10px',
              borderRadius: 999,
              background: anthropicConfigured ? '#14532d' : '#1e293b',
              color: anthropicConfigured ? '#4ade80' : '#64748b',
              border: `1px solid ${anthropicConfigured ? '#166534' : '#2d2f45'}`,
            }}>
              {anthropicConfigured ? 'Configured' : 'Not configured'}
            </span>
          )}
        </div>
        <p style={{ color: '#64748b', fontSize: 13, margin: '0 0 1rem' }}>
          Required for Sprint Brain AI planning and Retrospective generation.
        </p>
        <div style={{ display: 'flex', gap: 8 }}>
          <input
            type="password"
            placeholder="sk-ant-..."
            value={anthropicKey}
            onChange={e => setAnthropicKey(e.target.value)}
            style={{
              flex: 1,
              background: '#0f1117',
              border: '1px solid #2d2f45',
              borderRadius: 6,
              padding: '0.5rem 0.75rem',
              color: '#e2e8f0',
              fontSize: 13,
              outline: 'none',
            }}
          />
          <button
            onClick={handleSaveAnthropicKey}
            disabled={anthropicSaving || !anthropicKey.trim()}
            style={{
              background: anthropicSaving || !anthropicKey.trim() ? '#374151' : '#6366f1',
              color: anthropicSaving || !anthropicKey.trim() ? '#64748b' : '#fff',
              border: 'none',
              borderRadius: 6,
              padding: '0.5rem 1.25rem',
              fontSize: 13,
              fontWeight: 600,
              cursor: anthropicSaving || !anthropicKey.trim() ? 'not-allowed' : 'pointer',
              whiteSpace: 'nowrap',
            }}
          >
            {anthropicSaving ? 'Saving...' : 'Save Key'}
          </button>
        </div>
        {anthropicMessage && (
          <div style={{ color: anthropicMessage === 'API key saved.' ? '#4ade80' : '#ef4444', fontSize: 13, marginTop: 8 }}>
            {anthropicMessage}
          </div>
        )}
      </div>
    </div>
  )
}
