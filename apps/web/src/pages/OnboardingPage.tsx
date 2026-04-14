// apps/web/src/pages/OnboardingPage.tsx

import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { OnboardingLayout } from '../layouts/OnboardingLayout'
import { ConnectJiraStep } from './onboarding/ConnectJiraStep'
import { SelectBoardStep } from './onboarding/SelectBoardStep'
import { useApi } from '../lib/api'
import type { OnboardingStatus } from '../types/onboarding'

const STEPS = ['Connect Jira', 'Select Board', 'Import History', 'Invite Team'] as const
const STORAGE_KEY = 'aos_onboarding_step'

export function OnboardingPage() {
  const navigate = useNavigate()
  const { get, post } = useApi()
  const [step, setStep] = useState<number>(() => {
    const saved = localStorage.getItem(STORAGE_KEY)
    return saved ? parseInt(saved, 10) : 0
  })
  const [connectionId, setConnectionId] = useState<string | null>(null)

  // Step 3 state
  const [sprintCount, setSprintCount] = useState(3)
  const [importStatus, setImportStatus] = useState<OnboardingStatus['importStatus']>('pending')
  const [importedSprints, setImportedSprints] = useState<number | null>(null)
  const [importing, setImporting] = useState(false)
  const [importError, setImportError] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Step 4 state
  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteRole, setInviteRole] = useState('lead')
  const [inviting, setInviting] = useState(false)
  const [inviteLink, setInviteLink] = useState<string | null>(null)
  const [inviteError, setInviteError] = useState<string | null>(null)

  useEffect(() => {
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [])

  function goTo(next: number) {
    localStorage.setItem(STORAGE_KEY, String(next))
    setStep(next)
  }

  function advance(data?: string) {
    if (typeof data === 'string') setConnectionId(data)
    if (step === STEPS.length - 1) {
      localStorage.removeItem(STORAGE_KEY)
      navigate('/app/sprint-planner')
    } else {
      goTo(step + 1)
    }
  }

  function back() { goTo(step - 1) }

  async function handleImport() {
    setImporting(true)
    setImportError(null)
    try {
      await post('/api/onboarding/import-history', { sprintCount })
      setImportStatus('in_progress')
      pollRef.current = setInterval(async () => {
        try {
          const status = await get<{ status: string; importedSprints: number | null }>('/api/onboarding/import-status')
          setImportStatus(status.status as OnboardingStatus['importStatus'])
          setImportedSprints(status.importedSprints)
          if (status.status === 'completed' || status.status === 'failed') {
            if (pollRef.current) clearInterval(pollRef.current)
            setImporting(false)
          }
        } catch {
          if (pollRef.current) clearInterval(pollRef.current)
          setImporting(false)
        }
      }, 3000)
    } catch (err) {
      setImportError(err instanceof Error ? err.message : 'Import failed')
      setImporting(false)
    }
  }

  async function handleInvite() {
    if (!inviteEmail.trim()) return
    setInviting(true)
    setInviteError(null)
    setInviteLink(null)
    try {
      const result = await post<{ inviteLink: string }>('/api/invitations', { email: inviteEmail.trim(), role: inviteRole })
      setInviteLink(result.inviteLink)
      setInviteEmail('')
    } catch (err) {
      setInviteError(err instanceof Error ? err.message : 'Failed to send invite')
    } finally {
      setInviting(false)
    }
  }

  async function handleDone() {
    try { await post('/api/onboarding/complete', {}) } catch { /* best-effort */ }
    localStorage.removeItem(STORAGE_KEY)
    navigate('/app/sprint-planner')
  }

  return (
    <OnboardingLayout>
      {/* Step indicator */}
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: '2rem', flexWrap: 'wrap', gap: 4 }}>
        {STEPS.map((label, i) => (
          <div key={i} style={{ display: 'flex', alignItems: 'center' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <div style={{
                width: 28, height: 28, borderRadius: '50%',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                background: i < step ? '#6366f1' : 'transparent',
                border: i === step ? '2px solid #6366f1' : i < step ? 'none' : '2px solid #2d2f45',
                color: i < step ? '#fff' : i === step ? '#6366f1' : '#64748b',
                fontSize: 11, fontWeight: 700, flexShrink: 0,
              }}>
                {i < step ? '✓' : i + 1}
              </div>
              <span style={{ fontSize: 12, color: i === step ? '#e2e8f0' : '#64748b', whiteSpace: 'nowrap' }}>
                {label}
              </span>
            </div>
            {i < STEPS.length - 1 && (
              <div style={{ width: 24, height: 1, background: '#2d2f45', margin: '0 8px', flexShrink: 0 }} />
            )}
          </div>
        ))}
      </div>

      {step === 0 && <ConnectJiraStep onNext={advance} />}
      {step === 1 && <SelectBoardStep connectionId={connectionId ?? ''} onNext={advance} onBack={back} />}

      {step === 2 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <h2 style={{ color: '#e2e8f0', fontSize: '1.125rem', fontWeight: 700, margin: 0 }}>Import Sprint History</h2>
          <p style={{ color: '#64748b', fontSize: 14, margin: 0 }}>
            Import recent completed sprints to give Sprint Brain historical context for better planning.
          </p>

          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <label style={{ color: '#94a3b8', fontSize: 13 }}>Import last</label>
            <select
              value={sprintCount}
              onChange={e => setSprintCount(Number(e.target.value))}
              disabled={importing}
              style={{ background: '#1e2030', border: '1px solid #2d2f45', borderRadius: 6, color: '#e2e8f0', fontSize: 13, padding: '6px 10px' }}
            >
              {[1, 2, 3, 4, 5, 6].map(n => <option key={n} value={n}>{n}</option>)}
            </select>
            <label style={{ color: '#94a3b8', fontSize: 13 }}>sprints</label>
          </div>

          {importStatus === 'pending' && !importing && (
            <button
              onClick={handleImport}
              style={{ background: '#6366f1', color: '#fff', border: 'none', borderRadius: 8, padding: '0.75rem 1.5rem', fontSize: 14, fontWeight: 600, cursor: 'pointer', alignSelf: 'flex-start' }}
            >
              Import Now
            </button>
          )}

          {(importing || importStatus === 'in_progress') && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <div style={{ width: 16, height: 16, border: '2px solid #6366f1', borderTopColor: 'transparent', borderRadius: '50%', animation: 'spin 1s linear infinite' }} />
              <span style={{ color: '#a5b4fc', fontSize: 14 }}>Importing sprints...</span>
            </div>
          )}

          {importStatus === 'completed' && (
            <div style={{ color: '#4ade80', fontSize: 14 }}>
              ✓ Imported {importedSprints ?? sprintCount} sprint{(importedSprints ?? sprintCount) !== 1 ? 's' : ''} successfully
            </div>
          )}

          {importStatus === 'failed' && (
            <div style={{ color: '#ef4444', fontSize: 14 }}>Import failed. You can skip this step and import manually later.</div>
          )}

          {importError && <div style={{ color: '#ef4444', fontSize: 13 }}>{importError}</div>}

          <div style={{ display: 'flex', gap: 10, marginTop: 8 }}>
            <button onClick={back} style={{ background: 'transparent', color: '#64748b', border: '1px solid #2d2f45', borderRadius: 8, padding: '0.625rem 1.25rem', fontSize: 13, fontWeight: 600, cursor: 'pointer' }}>
              Back
            </button>
            <button
              onClick={() => advance()}
              style={{ background: '#6366f1', color: '#fff', border: 'none', borderRadius: 8, padding: '0.625rem 1.5rem', fontSize: 13, fontWeight: 600, cursor: 'pointer' }}
            >
              {importStatus === 'completed' ? 'Continue' : 'Skip for now'}
            </button>
          </div>
        </div>
      )}

      {step === 3 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <h2 style={{ color: '#e2e8f0', fontSize: '1.125rem', fontWeight: 700, margin: 0 }}>Invite Your Team</h2>
          <p style={{ color: '#64748b', fontSize: 14, margin: 0 }}>
            Send invite links to your team members. They'll join via the link.
          </p>

          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <input
              type="email"
              placeholder="teammate@company.com"
              value={inviteEmail}
              onChange={e => setInviteEmail(e.target.value)}
              style={{ flex: 1, minWidth: 200, background: '#0f1117', border: '1px solid #2d2f45', borderRadius: 6, color: '#e2e8f0', fontSize: 13, padding: '0.5rem 0.75rem' }}
            />
            <select
              value={inviteRole}
              onChange={e => setInviteRole(e.target.value)}
              style={{ background: '#1e2030', border: '1px solid #2d2f45', borderRadius: 6, color: '#e2e8f0', fontSize: 13, padding: '0.5rem 0.75rem' }}
            >
              <option value="lead">Lead</option>
              <option value="exec">Exec</option>
            </select>
            <button
              onClick={handleInvite}
              disabled={inviting || !inviteEmail.trim()}
              style={{ background: inviting || !inviteEmail.trim() ? '#374151' : '#6366f1', color: inviting || !inviteEmail.trim() ? '#64748b' : '#fff', border: 'none', borderRadius: 6, padding: '0.5rem 1.25rem', fontSize: 13, fontWeight: 600, cursor: inviting || !inviteEmail.trim() ? 'not-allowed' : 'pointer' }}
            >
              {inviting ? 'Sending...' : 'Send Invite'}
            </button>
          </div>

          {inviteLink && (
            <div style={{ background: '#0f1117', border: '1px solid #2d2f45', borderRadius: 6, padding: '0.75rem 1rem', fontSize: 13 }}>
              <div style={{ color: '#4ade80', marginBottom: 4, fontWeight: 600 }}>✓ Invite link created</div>
              <div style={{ color: '#6366f1', wordBreak: 'break-all' }}>{inviteLink}</div>
            </div>
          )}

          {inviteError && <div style={{ color: '#ef4444', fontSize: 13 }}>{inviteError}</div>}

          <div style={{ display: 'flex', gap: 10, marginTop: 8, flexWrap: 'wrap' }}>
            <button onClick={back} style={{ background: 'transparent', color: '#64748b', border: '1px solid #2d2f45', borderRadius: 8, padding: '0.625rem 1.25rem', fontSize: 13, fontWeight: 600, cursor: 'pointer' }}>
              Back
            </button>
            <button
              onClick={handleDone}
              style={{ background: 'transparent', color: '#94a3b8', border: '1px solid #2d2f45', borderRadius: 8, padding: '0.625rem 1.25rem', fontSize: 13, fontWeight: 600, cursor: 'pointer' }}
            >
              Skip for now
            </button>
            <button
              onClick={handleDone}
              style={{ background: '#6366f1', color: '#fff', border: 'none', borderRadius: 8, padding: '0.625rem 1.5rem', fontSize: 13, fontWeight: 600, cursor: 'pointer' }}
            >
              Done
            </button>
          </div>
        </div>
      )}
    </OnboardingLayout>
  )
}
