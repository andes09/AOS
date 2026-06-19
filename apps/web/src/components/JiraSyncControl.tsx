import { CSSProperties, useEffect, useRef, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { useApi } from '../lib/api'

interface JiraStatus {
  connected: boolean
  last_synced_at?: string | null
  board_id?: string | null
  board_configured?: boolean
}

function formatRelative(iso: string | null | undefined): string {
  if (!iso) return 'Never synced'
  const then = new Date(iso).getTime()
  const diffMs = Date.now() - then
  if (diffMs < 0) return 'Just now'
  const sec = Math.floor(diffMs / 1000)
  if (sec < 60) return `Synced ${sec}s ago`
  const min = Math.floor(sec / 60)
  if (min < 60) return `Synced ${min}m ago`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `Synced ${hr}h ago`
  return `Synced ${new Date(iso).toLocaleDateString()}`
}

export function JiraSyncControl() {
  const { get, post } = useApi()
  const [status, setStatus] = useState<JiraStatus | null>(null)
  const [syncing, setSyncing] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  async function fetchStatus() {
    try {
      const data = await get<JiraStatus>('/api/integrations/jira/status')
      setStatus(data)
    } catch {
      setStatus({ connected: false })
    }
  }

  useEffect(() => {
    fetchStatus()
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [])

  async function handleSync() {
    if (syncing) return
    setSyncing(true)
    setMessage(null)
    try {
      const org = await post<{ teamId: string }>('/api/organizations', { name: 'My Org' })
      const teamId = org.teamId
      await post(`/api/integrations/jira/sync?team_id=${teamId}`, {})

      // Poll the structured per-team status so we can distinguish running/complete/failed
      // and surface the real error_message instead of timing out blindly.
      let attempts = 0
      const MAX_ATTEMPTS = 100 // 100 * 3s = 5 min ceiling for a stuck "running" state
      pollRef.current = setInterval(async () => {
        attempts++
        try {
          const s = await get<{
            state: 'running' | 'complete' | 'failed' | 'unknown'
            error_code?: string | null
            error_message?: string | null
            tickets_synced?: number
            members_synced?: number
          }>(`/api/integrations/jira/sync-status/${teamId}`)

          if (s.state === 'complete') {
            if (pollRef.current) clearInterval(pollRef.current)
            setSyncing(false)
            if ((s.tickets_synced ?? 0) === 0) {
              setMessage('Sync complete — no tickets found. Check your board has open issues.')
            } else {
              setMessage(null)
            }
            fetchStatus()
            return
          }
          if (s.state === 'failed') {
            if (pollRef.current) clearInterval(pollRef.current)
            setSyncing(false)
            const detail = s.error_message?.trim()
            setMessage(detail ? `Sync failed: ${detail}` : `Sync failed${s.error_code ? ` (${s.error_code})` : ''}`)
            return
          }
          // running or unknown → keep polling, show progress hint if we have one
          if (s.state === 'running' && ((s.tickets_synced ?? 0) > 0 || (s.members_synced ?? 0) > 0)) {
            setMessage(`Syncing — ${s.tickets_synced ?? 0} tickets, ${s.members_synced ?? 0} members`)
          }
        } catch {
          // network blip — keep polling
        }
        if (attempts >= MAX_ATTEMPTS) {
          if (pollRef.current) clearInterval(pollRef.current)
          setSyncing(false)
          setMessage('Sync still running — check back in a minute or refresh')
        }
      }, 3000)
    } catch (err) {
      setSyncing(false)
      setMessage((err as any)?.response?.data?.detail ?? (err instanceof Error ? err.message : 'Sync failed'))
    }
  }

  if (!status?.connected) return null

  const buttonStyle: CSSProperties = {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 6,
    height: 30,
    padding: '0 10px',
    border: '1px solid var(--color-border)',
    borderRadius: 'var(--radius-md)',
    background: 'transparent',
    color: 'var(--color-text-secondary)',
    fontFamily: 'var(--font-sans)',
    fontSize: 'var(--text-xs)',
    fontWeight: 500,
    cursor: syncing ? 'default' : 'pointer',
    opacity: syncing ? 0.7 : 1,
    transition: 'background 0.15s, color 0.15s',
  }

  return (
    <div style={{ display: 'inline-flex', alignItems: 'center', gap: 10 }}>
      <span
        title={status.last_synced_at ?? undefined}
        style={{
          color: message && !syncing ? 'var(--color-danger)' : 'var(--color-text-muted)',
          fontFamily: 'var(--font-sans)',
          fontSize: 'var(--text-xs)',
        }}
      >
        {message ?? formatRelative(status.last_synced_at)}
      </span>
      <button
        onClick={handleSync}
        disabled={syncing}
        title="Sync Jira now"
        style={buttonStyle}
        onMouseEnter={e => {
          if (syncing) return
          e.currentTarget.style.background = 'var(--color-bg-tertiary)'
          e.currentTarget.style.color = 'var(--color-text-primary)'
        }}
        onMouseLeave={e => {
          if (syncing) return
          e.currentTarget.style.background = 'transparent'
          e.currentTarget.style.color = 'var(--color-text-secondary)'
        }}
      >
        <RefreshCw size={13} style={syncing ? { animation: 'spin 1s linear infinite' } : undefined} />
        {syncing ? 'Syncing' : 'Sync'}
      </button>
    </div>
  )
}
