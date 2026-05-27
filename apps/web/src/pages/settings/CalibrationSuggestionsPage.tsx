// apps/web/src/pages/settings/CalibrationSuggestionsPage.tsx
//
// Calibration Suggestions (M8c). Lists pending RecalibrationProposal rows
// emitted by the override-analyzer and lets the lead approve or dismiss
// each one. Lives under /app/settings/calibration.

import { useEffect, useState, CSSProperties } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '@clerk/clerk-react'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft } from 'lucide-react'
import { useApi, ApiError } from '../../lib/api'
import { useAppRole } from '../../hooks/useAppRole'
import { Card, CardBody, CardHeader } from '../../components/ui/Card'
import { Badge } from '../../components/ui/Badge'
import { Button } from '../../components/ui/Button'
import { Spinner } from '../../components/ui/Spinner'
import { EmptyState } from '../../components/ui/EmptyState'
import type { TeamListItem } from '../../types/multiTeam'

interface ProposalRow {
  id: string
  teamId: string
  kind: 'skill_rating' | 'identifier_skill' | string
  developerId: string | null
  identifierId: string | null
  skill: string | null
  currentValue: number | null
  suggestedValue: number | null
  suggestedSkill: string | null
  evidence: string[]
  status: string
  decidedAt: string | null
  decidedBy: string | null
  createdAt: string
}

// Lightweight developer cache so we can render the dev's name instead of UUID.
interface DeveloperSummary {
  id: string
  name: string | null
}

function formatRating(v: number | null): string {
  if (v === null || v === undefined) return '—'
  return v.toFixed(2)
}

export function CalibrationSuggestionsPage() {
  const { isLoaded, isSignedIn } = useAuth()
  const { get, post } = useApi()
  const { appRole } = useAppRole()
  const isLead = appRole === 'lead' || appRole === 'exec' || appRole === 'admin'

  const [rows, setRows] = useState<ProposalRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [scanning, setScanning] = useState(false)
  const [actingId, setActingId] = useState<string | null>(null)
  const [toast, setToast] = useState<{ message: string; tone: 'success' | 'danger' } | null>(null)
  const [devNames, setDevNames] = useState<Record<string, string>>({})

  const { data: teamsData } = useQuery<{ teams: TeamListItem[] }>({
    queryKey: ['teams-list'],
    queryFn: () => get<{ teams: TeamListItem[] }>('/api/teams'),
    enabled: isLoaded && !!isSignedIn,
  })
  const teams = teamsData?.teams ?? []
  const storedTeamId = typeof window !== 'undefined' ? localStorage.getItem('aos_active_team_id') : null
  const activeTeam =
    (storedTeamId && teams.find(t => t.teamId === storedTeamId)) ||
    teams.find(t => t.isPrimary) ||
    teams[0]
  const teamId = activeTeam?.teamId

  async function fetchProposals() {
    if (!teamId) return
    setLoading(true)
    setError(null)
    try {
      const data = await get<ProposalRow[]>(`/api/recalibration/proposals/${teamId}?status=pending`)
      setRows(data)
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        setError('You need lead access to view calibration suggestions.')
      } else {
        setError(err instanceof Error ? err.message : 'Failed to load suggestions.')
      }
    } finally {
      setLoading(false)
    }
  }

  async function fetchDevelopers() {
    if (!teamId) return
    try {
      const data = await get<DeveloperSummary[] | { developers: DeveloperSummary[] }>(
        `/api/developers?team_id=${teamId}`
      )
      const list = Array.isArray(data) ? data : (data.developers ?? [])
      const map: Record<string, string> = {}
      for (const d of list) map[d.id] = d.name ?? d.id
      setDevNames(map)
    } catch {
      // Non-fatal; we'll fall back to UUIDs.
    }
  }

  useEffect(() => {
    if (!teamId) return
    fetchProposals()
    fetchDevelopers()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [teamId])

  function showToast(message: string, tone: 'success' | 'danger') {
    setToast({ message, tone })
    setTimeout(() => setToast(null), 2500)
  }

  async function handleScan() {
    if (!teamId) return
    setScanning(true)
    try {
      const data = await post<{ inserted: number }>(`/api/recalibration/scan/${teamId}`, {})
      showToast(
        data.inserted > 0
          ? `Found ${data.inserted} new suggestion${data.inserted === 1 ? '' : 's'}.`
          : 'No new suggestions.',
        'success',
      )
      await fetchProposals()
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Scan failed.', 'danger')
    } finally {
      setScanning(false)
    }
  }

  async function handleApprove(id: string) {
    setActingId(id)
    try {
      await post(`/api/recalibration/proposals/${id}/approve`, {})
      setRows(prev => prev.filter(r => r.id !== id))
      showToast('Suggestion applied.', 'success')
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to approve.', 'danger')
    } finally {
      setActingId(null)
    }
  }

  async function handleDismiss(id: string) {
    setActingId(id)
    try {
      await post(`/api/recalibration/proposals/${id}/dismiss`, {})
      setRows(prev => prev.filter(r => r.id !== id))
      showToast('Suggestion dismissed.', 'success')
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to dismiss.', 'danger')
    } finally {
      setActingId(null)
    }
  }

  function describe(p: ProposalRow): string {
    if (p.kind === 'skill_rating') {
      const devLabel = (p.developerId && devNames[p.developerId]) || p.developerId || 'Developer'
      return `${devLabel} — lower ${p.skill} rating from ${formatRating(p.currentValue)} to ${formatRating(p.suggestedValue)} (based on ${p.evidence.length} reassignment${p.evidence.length === 1 ? '' : 's'} away from ${p.skill} tickets)`
    }
    if (p.kind === 'identifier_skill') {
      return `Identifier — reclassify from ${p.skill ?? '—'} to ${p.suggestedSkill ?? '—'} (based on ${p.evidence.length} reassignment${p.evidence.length === 1 ? '' : 's'})`
    }
    return `Unknown proposal kind: ${p.kind}`
  }

  if (!isLead) {
    return (
      <div style={{ maxWidth: 720, margin: '0 auto', fontFamily: 'var(--font-sans)' }}>
        <Card>
          <CardBody>
            <EmptyState
              title="Lead access required"
              description="Calibration Suggestions are available to leads and execs only."
            />
          </CardBody>
        </Card>
      </div>
    )
  }

  return (
    <div style={{ maxWidth: 980, margin: '0 auto', fontFamily: 'var(--font-sans)' }}>
      <div style={{ marginBottom: 16 }}>
        <Link
          to="/app/settings"
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 4,
            color: 'var(--color-text-muted)',
            fontSize: 'var(--text-sm)',
            textDecoration: 'none',
          }}
        >
          <ArrowLeft size={14} /> Settings
        </Link>
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', marginBottom: 16, gap: 12, flexWrap: 'wrap' }}>
        <div>
          <h1 style={{ color: 'var(--color-text-primary)', fontSize: 'var(--text-xl)', fontWeight: 700, margin: 0 }}>
            Calibration Suggestions
          </h1>
          <p style={{ color: 'var(--color-text-muted)', fontSize: 'var(--text-sm)', margin: '4px 0 0' }}>
            Sprint Brain learns from your overrides. Approve a suggestion to apply it.
          </p>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {activeTeam && <Badge variant="default">{activeTeam.teamName}</Badge>}
          <Button size="sm" variant="secondary" onClick={handleScan} disabled={scanning || !teamId}>
            {scanning ? 'Scanning…' : 'Scan now'}
          </Button>
        </div>
      </div>

      <Card>
        <CardHeader>
          <span style={{ color: 'var(--color-text-primary)', fontSize: 'var(--text-base)', fontWeight: 600 }}>
            Pending suggestions
          </span>
        </CardHeader>
        <CardBody style={{ padding: 0 }}>
          {!teamId ? (
            <div style={{ padding: 32, textAlign: 'center', color: 'var(--color-text-muted)', fontSize: 'var(--text-sm)' }}>
              <Spinner size={18} />
              <div style={{ marginTop: 8 }}>Loading team…</div>
            </div>
          ) : loading ? (
            <div style={{ padding: 32, textAlign: 'center' }}>
              <Spinner size={18} />
              <div style={{ marginTop: 8, color: 'var(--color-text-muted)', fontSize: 'var(--text-sm)' }}>
                Loading suggestions…
              </div>
            </div>
          ) : error ? (
            <div style={{ padding: 24, color: 'var(--color-danger)', fontSize: 'var(--text-sm)' }}>
              {error}
            </div>
          ) : rows.length === 0 ? (
            <EmptyState
              title="No suggestions yet"
              description="Sprint Brain learns from your overrides — check back after a few sprints."
            />
          ) : (
            <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
              {rows.map(p => (
                <li
                  key={p.id}
                  style={{
                    padding: '14px 16px',
                    borderTop: '1px solid var(--color-border)',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 8,
                  }}
                >
                  <div style={{ color: 'var(--color-text-primary)', fontSize: 'var(--text-sm)' }}>
                    {describe(p)}
                  </div>
                  {p.evidence.length > 0 && (
                    <div style={{ color: 'var(--color-text-muted)', fontSize: 'var(--text-xs)' }}>
                      Evidence: {p.evidence.map(id => (
                        <span
                          key={id}
                          style={{ fontFamily: 'var(--font-mono)', marginRight: 6 }}
                        >
                          {id.slice(0, 8)}
                        </span>
                      ))}
                    </div>
                  )}
                  <div style={{ display: 'flex', gap: 8 }}>
                    <Button
                      size="sm"
                      variant="primary"
                      onClick={() => handleApprove(p.id)}
                      disabled={actingId === p.id}
                    >
                      {actingId === p.id ? 'Working…' : 'Approve'}
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => handleDismiss(p.id)}
                      disabled={actingId === p.id}
                    >
                      Dismiss
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardBody>
      </Card>

      {toast && (
        <div
          style={{
            position: 'fixed',
            bottom: 24,
            right: 24,
            padding: '10px 14px',
            borderRadius: 'var(--radius-md)',
            background: toast.tone === 'success' ? 'var(--color-success-bg)' : 'var(--color-danger-subtle)',
            color: toast.tone === 'success' ? 'var(--color-success)' : 'var(--color-danger)',
            fontSize: 'var(--text-sm)',
            boxShadow: 'var(--shadow-md)',
            border: '1px solid transparent',
            zIndex: 100,
          } as CSSProperties}
          role="status"
        >
          {toast.message}
        </div>
      )}
    </div>
  )
}
