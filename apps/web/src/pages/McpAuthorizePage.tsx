// The OAuth consent screen for the Omada MCP server (see
// src/mcp_server/oauth_provider.py's `authorize()`, which redirects here).
// Modeled on InviteAcceptPage.tsx: a Clerk-gated page that POSTs to a backend
// endpoint via useApi()'s auto-attached JWT — that POST is the one point
// where Clerk's login satisfies the MCP client's OAuth flow.

import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useApi, ApiError } from '../lib/api'

interface ConsentResult {
  redirectUrl: string
}

export function McpAuthorizePage() {
  const [searchParams] = useSearchParams()
  const { post } = useApi()
  const [status, setStatus] = useState<'idle' | 'loading' | 'error'>('idle')
  const [error, setError] = useState<string | null>(null)

  const clientId = searchParams.get('client_id')
  const clientName = searchParams.get('client_name') || 'An MCP client'
  const redirectUri = searchParams.get('redirect_uri')
  const codeChallenge = searchParams.get('code_challenge')
  const scope = searchParams.get('scope') || undefined
  const state = searchParams.get('state') || undefined

  const missingParams = !clientId || !redirectUri || !codeChallenge

  const approve = async () => {
    setStatus('loading')
    setError(null)
    try {
      const result = await post<ConsentResult>('/api/mcp/oauth/consent', {
        clientId, redirectUri, codeChallenge, scope, state,
      })
      window.location.href = result.redirectUrl
    } catch (e) {
      setStatus('error')
      if (e instanceof ApiError && e.status === 409) {
        setError('Your account has no developer profile in this organization yet — ask a team lead to add you before connecting an agent.')
      } else {
        setError(e instanceof Error ? e.message : 'Something went wrong. Please try again.')
      }
    }
  }

  const deny = () => {
    if (!redirectUri) return
    const url = new URL(redirectUri)
    url.searchParams.set('error', 'access_denied')
    if (state) url.searchParams.set('state', state)
    window.location.href = url.toString()
  }

  return (
    <div style={{
      minHeight: '100vh',
      background: 'var(--color-bg-primary, #0f1117)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontFamily: 'system-ui, sans-serif',
      padding: '1rem',
    }}>
      <div style={{
        background: 'var(--color-bg-elevated, #1e2030)',
        border: '1px solid var(--color-border, #2d2f45)',
        borderRadius: 12,
        padding: '2.5rem 2rem',
        maxWidth: 440,
        width: '100%',
        textAlign: 'center',
      }}>
        {missingParams ? (
          <>
            <div style={{ fontSize: 48, marginBottom: 16 }}>⚠️</div>
            <h1 style={{ color: 'var(--color-text-primary, #e2e8f0)', fontSize: '1.15rem', fontWeight: 700, marginBottom: 8 }}>
              Invalid authorization request
            </h1>
            <p style={{ color: 'var(--color-text-secondary, #94a3b8)', fontSize: 14 }}>
              This link is missing required parameters. Please restart the connection from your MCP client.
            </p>
          </>
        ) : (
          <>
            <div style={{ fontSize: 40, marginBottom: 16 }}>🔗</div>
            <h1 style={{ color: 'var(--color-text-primary, #e2e8f0)', fontSize: '1.15rem', fontWeight: 700, marginBottom: 8 }}>
              <strong>{clientName}</strong> wants access to your Omada roadmap
            </h1>
            <p style={{ color: 'var(--color-text-secondary, #94a3b8)', fontSize: 14, marginBottom: 24 }}>
              It will be able to read your roadmap and tasks, claim and complete tasks on your behalf, and
              (if you're a lead or above) trigger AI replanning of a milestone.
            </p>

            {error && (
              <p style={{ color: '#f87171', fontSize: 13, marginBottom: 16 }}>{error}</p>
            )}

            <div style={{ display: 'flex', gap: 10, justifyContent: 'center' }}>
              <button
                onClick={deny}
                disabled={status === 'loading'}
                style={{
                  background: 'transparent',
                  color: 'var(--color-text-secondary, #94a3b8)',
                  border: '1px solid var(--color-border, #2d2f45)',
                  borderRadius: 8,
                  padding: '0.65rem 1.5rem',
                  fontSize: 14,
                  fontWeight: 600,
                  cursor: 'pointer',
                }}
              >
                Deny
              </button>
              <button
                onClick={approve}
                disabled={status === 'loading'}
                style={{
                  background: '#6366f1',
                  color: '#fff',
                  border: 'none',
                  borderRadius: 8,
                  padding: '0.65rem 1.5rem',
                  fontSize: 14,
                  fontWeight: 700,
                  cursor: status === 'loading' ? 'default' : 'pointer',
                  opacity: status === 'loading' ? 0.7 : 1,
                }}
              >
                {status === 'loading' ? 'Connecting…' : 'Approve'}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
