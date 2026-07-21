import { useEffect, useState } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import { useApi, ApiError } from '../lib/api'

interface AcceptResult {
  teamId: string
  role: string
  acceptedAt: string
}

export function InviteAcceptPage() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const { post } = useApi()
  const [status, setStatus] = useState<'loading' | 'success' | 'invalid' | 'expired' | 'error'>('loading')
  const [result, setResult] = useState<AcceptResult | null>(null)

  const token = searchParams.get('token')

  useEffect(() => {
    if (!token) {
      setStatus('invalid')
      return
    }
    post<AcceptResult>('/api/invitations/accept', { token })
      .then(data => {
        setResult(data)
        setStatus('success')
      })
      .catch(err => {
        if (err instanceof ApiError) {
          if (err.status === 404) setStatus('invalid')
          else if (err.status === 410) setStatus('expired')
          else setStatus('error')
        } else {
          setStatus('error')
        }
      })
  }, [token])

  return (
    <div style={{
      minHeight: '100vh',
      background: '#0f1117',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontFamily: 'system-ui, sans-serif',
    }}>
      <div style={{
        background: '#1e2030',
        border: '1px solid #2d2f45',
        borderRadius: 12,
        padding: '2.5rem 2rem',
        maxWidth: 400,
        width: '100%',
        textAlign: 'center',
      }}>
        {status === 'loading' && (
          <div style={{ color: '#94a3b8', fontSize: 15 }}>Accepting invitation...</div>
        )}

        {status === 'success' && result && (
          <>
            <div style={{ fontSize: 48, marginBottom: 16 }}>🎉</div>
            <h1 style={{ color: '#e2e8f0', fontSize: '1.25rem', fontWeight: 700, marginBottom: 8 }}>
              Welcome to the team!
            </h1>
            <p style={{ color: '#94a3b8', fontSize: 14, marginBottom: 24 }}>
              You've joined as <strong style={{ color: '#a5b4fc' }}>{result.role}</strong>
            </p>
            <button
              onClick={() => navigate('/app')}
              style={{
                background: '#6366f1',
                color: '#fff',
                border: 'none',
                borderRadius: 8,
                padding: '0.75rem 2rem',
                fontSize: 14,
                fontWeight: 700,
                cursor: 'pointer',
              }}
            >
              Go to Dashboard
            </button>
          </>
        )}

        {status === 'invalid' && (
          <>
            <div style={{ fontSize: 48, marginBottom: 16 }}>❌</div>
            <h1 style={{ color: '#e2e8f0', fontSize: '1.25rem', fontWeight: 700, marginBottom: 8 }}>
              Invalid invitation
            </h1>
            <p style={{ color: '#94a3b8', fontSize: 14 }}>
              This invitation link is invalid or has already been used.
            </p>
          </>
        )}

        {status === 'expired' && (
          <>
            <div style={{ fontSize: 48, marginBottom: 16 }}>⏰</div>
            <h1 style={{ color: '#e2e8f0', fontSize: '1.25rem', fontWeight: 700, marginBottom: 8 }}>
              Invitation expired
            </h1>
            <p style={{ color: '#94a3b8', fontSize: 14 }}>
              This invitation has expired or was revoked. Please ask your team lead to send a new one.
            </p>
          </>
        )}

        {status === 'error' && (
          <>
            <div style={{ fontSize: 48, marginBottom: 16 }}>⚠️</div>
            <h1 style={{ color: '#e2e8f0', fontSize: '1.25rem', fontWeight: 700, marginBottom: 8 }}>
              Something went wrong
            </h1>
            <p style={{ color: '#94a3b8', fontSize: 14 }}>
              Failed to accept the invitation. Please try again or contact support.
            </p>
          </>
        )}
      </div>
    </div>
  )
}
