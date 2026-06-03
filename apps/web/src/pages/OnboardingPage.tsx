// apps/web/src/pages/OnboardingPage.tsx

import { CSSProperties, useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { OnboardingLayout } from '../layouts/OnboardingLayout'
import { ConnectJiraStep } from './onboarding/ConnectJiraStep'
import { SelectBoardStep } from './onboarding/SelectBoardStep'
import { Button } from '../components/ui/Button'
import { Card, CardBody } from '../components/ui/Card'
import { Select } from '../components/ui/Select'
import { Input } from '../components/ui/Input'
import { Alert } from '../components/ui/Alert'
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

  const [sprintCount, setSprintCount] = useState(3)
  const [importStatus, setImportStatus] = useState<OnboardingStatus['importStatus']>('pending')
  const [importedSprints, setImportedSprints] = useState<number | null>(null)
  const [importing, setImporting] = useState(false)
  const [importError, setImportError] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

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
        {STEPS.map((label, i) => {
          const isDone = i < step
          const isCurrent = i === step

          const circleStyle: CSSProperties = {
            width: 28,
            height: 28,
            borderRadius: '50%',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontFamily: 'var(--font-sans)',
            fontWeight: 700,
            fontSize: 'var(--text-xs)',
            flexShrink: 0,
            background: isDone ? 'var(--color-accent)' : 'transparent',
            border: isCurrent
              ? '2px solid var(--color-accent)'
              : isDone
              ? 'none'
              : '2px solid var(--color-border)',
            color: isDone ? '#ffffff' : isCurrent ? 'var(--color-accent)' : 'var(--color-text-muted)',
          }

          return (
            <div key={i} style={{ display: 'flex', alignItems: 'center' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <div style={circleStyle}>
                  {isDone ? '✓' : i + 1}
                </div>
                <span style={{
                  fontFamily: 'var(--font-sans)',
                  fontSize: 'var(--text-xs)',
                  color: isCurrent ? 'var(--color-text-primary)' : 'var(--color-text-muted)',
                  whiteSpace: 'nowrap',
                }}>
                  {label}
                </span>
              </div>
              {i < STEPS.length - 1 && (
                <div style={{ width: 24, height: 1, background: 'var(--color-border)', margin: '0 8px', flexShrink: 0 }} />
              )}
            </div>
          )
        })}
      </div>

      {step === 0 && <ConnectJiraStep onNext={advance} />}
      {step === 1 && <SelectBoardStep connectionId={connectionId ?? ''} onNext={advance} onBack={back} />}

      {step === 2 && (
        <Card style={{ maxWidth: 560 }}>
          <CardBody style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: 16 }}>
            <h2 style={{ color: 'var(--color-text-primary)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-lg)', fontWeight: 700, margin: 0 }}>
              Import Sprint History
            </h2>
            <p style={{ color: 'var(--color-text-muted)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)', margin: 0 }}>
              Import recent completed sprints to give Omada historical context for better sprint planning.
            </p>

            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <label style={{ color: 'var(--color-text-secondary)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)' }}>Import last</label>
              <Select
                value={sprintCount}
                onChange={e => setSprintCount(Number(e.target.value))}
                disabled={importing}
                containerStyle={{ width: 80 }}
              >
                {[1, 2, 3, 4, 5, 6].map(n => <option key={n} value={n}>{n}</option>)}
              </Select>
              <label style={{ color: 'var(--color-text-secondary)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)' }}>sprints</label>
            </div>

            {importStatus === 'pending' && !importing && (
              <Button variant="primary" onClick={handleImport} style={{ alignSelf: 'flex-start' }}>
                Import Now
              </Button>
            )}

            {(importing || importStatus === 'in_progress') && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <div style={{ width: 16, height: 16, border: '2px solid var(--color-accent)', borderTopColor: 'transparent', borderRadius: '50%', animation: 'spin 1s linear infinite' }} />
                <span style={{ color: 'var(--color-accent)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)' }}>Importing sprints...</span>
              </div>
            )}

            {importStatus === 'completed' && (
              <div style={{ color: 'var(--color-success)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)' }}>
                Imported {importedSprints ?? sprintCount} sprint{(importedSprints ?? sprintCount) !== 1 ? 's' : ''} successfully
              </div>
            )}

            {importStatus === 'failed' && (
              <Alert variant="danger">Import failed. You can skip this step and import manually later.</Alert>
            )}

            {importError && <Alert variant="danger">{importError}</Alert>}

            <div style={{ display: 'flex', gap: 10, marginTop: 8 }}>
              <Button variant="ghost" size="sm" onClick={back}>Back</Button>
              <Button variant="primary" size="sm" onClick={() => advance()}>
                {importStatus === 'completed' ? 'Continue' : 'Skip for now'}
              </Button>
            </div>
          </CardBody>
        </Card>
      )}

      {step === 3 && (
        <Card style={{ maxWidth: 560 }}>
          <CardBody style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: 16 }}>
            <h2 style={{ color: 'var(--color-text-primary)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-lg)', fontWeight: 700, margin: 0 }}>
              Invite Your Team
            </h2>
            <p style={{ color: 'var(--color-text-muted)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)', margin: 0 }}>
              Send invite links to your team members. They'll join via the link.
            </p>

            <div style={{
              background: 'var(--color-bg-secondary)',
              border: '1px solid var(--color-border)',
              borderRadius: 'var(--radius-md)',
              padding: '10px 12px',
              color: 'var(--color-text-secondary)',
              fontFamily: 'var(--font-sans)',
              fontSize: 'var(--text-xs)',
              lineHeight: 1.5,
            }}>
              Omada shows individual velocity trends to developers first. Team leads see team-level trends. Individual data is never used for performance reviews.
            </div>

            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'flex-end' }}>
              <Input
                type="email"
                placeholder="teammate@company.com"
                value={inviteEmail}
                onChange={e => setInviteEmail(e.target.value)}
                containerStyle={{ flex: 1, minWidth: 200 }}
              />
              <Select
                value={inviteRole}
                onChange={e => setInviteRole(e.target.value)}
                containerStyle={{ width: 90 }}
              >
                <option value="lead">Lead</option>
                <option value="exec">Exec</option>
              </Select>
              <Button
                variant="primary"
                size="sm"
                onClick={handleInvite}
                disabled={inviting || !inviteEmail.trim()}
              >
                {inviting ? 'Sending...' : 'Send Invite'}
              </Button>
            </div>

            {inviteLink && (
              <Alert variant="success" title="Invite link created">
                <span style={{ wordBreak: 'break-all', color: 'var(--color-accent)' }}>{inviteLink}</span>
              </Alert>
            )}

            {inviteError && <Alert variant="danger">{inviteError}</Alert>}

            <div style={{ display: 'flex', gap: 10, marginTop: 8, flexWrap: 'wrap' }}>
              <Button variant="ghost" size="sm" onClick={back}>Back</Button>
              <Button variant="ghost" size="sm" onClick={handleDone}>Skip for now</Button>
              <Button variant="primary" size="sm" onClick={handleDone}>Done</Button>
            </div>
          </CardBody>
        </Card>
      )}
    </OnboardingLayout>
  )
}
