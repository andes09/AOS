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
  const { get, del } = useApi()

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

  useEffect(() => {
    fetchStatus()
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
            {actionError && (
              <div style={{ color: '#ef4444', fontSize: 13, marginBottom: 8 }}>{actionError}</div>
            )}
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
    </div>
  )
}
