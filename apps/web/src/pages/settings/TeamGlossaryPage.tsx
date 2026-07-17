// apps/web/src/pages/settings/TeamGlossaryPage.tsx

import { useEffect, useMemo, useState, CSSProperties } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '@clerk/clerk-react'
import { useQuery } from '@tanstack/react-query'
import { Trash2, Check, X as XIcon, ArrowLeft } from 'lucide-react'
import { useApi, ApiError } from '../../lib/api'
import { useAppRole } from '../../hooks/useAppRole'
import { Card, CardBody, CardHeader } from '../../components/ui/Card'
import { Badge } from '../../components/ui/Badge'
import { Button } from '../../components/ui/Button'
import { Input } from '../../components/ui/Input'
import { Spinner } from '../../components/ui/Spinner'
import { EmptyState } from '../../components/ui/EmptyState'
import { Table, type TableColumn } from '../../components/ui/Table'
import type { TeamListItem } from '../../types/multiTeam'

interface IdentifierRow {
  id: string
  teamId: string
  token: string
  normalizedToken: string
  skill: string
  domain: string | null
  confidence: number
  source: string
  occurrenceCount: number
  firstSeenAt: string
  lastSeenAt: string
}

type EditableField = 'skill' | 'domain'

interface InlineEditState {
  id: string
  field: EditableField
  value: string
}

function confidenceBadge(confidence: number) {
  if (confidence >= 0.8) {
    return <Badge variant="success">{(confidence * 100).toFixed(0)}%</Badge>
  }
  if (confidence >= 0.6) {
    return <Badge variant="warning">{(confidence * 100).toFixed(0)}%</Badge>
  }
  return (
    <Badge variant="danger">
      {(confidence * 100).toFixed(0)}% · needs review
    </Badge>
  )
}

function formatDate(iso: string): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}

export function TeamGlossaryPage() {
  const { isLoaded, isSignedIn } = useAuth()
  const { get, patch, del } = useApi()
  const { appRole } = useAppRole()
  const isLead = appRole === 'lead' || appRole === 'exec' || appRole === 'admin'

  const [rows, setRows] = useState<IdentifierRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [lowOnly, setLowOnly] = useState(false)
  const [edit, setEdit] = useState<InlineEditState | null>(null)
  const [saving, setSaving] = useState(false)
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null)
  const [toast, setToast] = useState<{ message: string; tone: 'success' | 'danger' } | null>(null)

  // Resolve the active team UUID via /api/teams (matches VelocityMirror's pattern).
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

  async function fetchIdentifiers(low: boolean) {
    if (!teamId) return
    setLoading(true)
    setError(null)
    try {
      const query = low ? '?low_confidence_only=true' : ''
      const data = await get<IdentifierRow[]>(`/api/identifiers/${teamId}${query}`)
      setRows(data)
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        setError('You need lead access to view the team glossary.')
      } else {
        setError(err instanceof Error ? err.message : 'Failed to load identifiers.')
      }
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (!teamId) return
    fetchIdentifiers(lowOnly)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [teamId, lowOnly])

  function showToast(message: string, tone: 'success' | 'danger') {
    setToast({ message, tone })
    setTimeout(() => setToast(null), 2500)
  }

  function startEdit(row: IdentifierRow, field: EditableField) {
    setEdit({ id: row.id, field, value: (row[field] ?? '') as string })
  }

  function cancelEdit() {
    setEdit(null)
  }

  async function commitEdit() {
    if (!edit) return
    const current = rows.find(r => r.id === edit.id)
    if (!current) {
      setEdit(null)
      return
    }
    const trimmed = edit.value.trim()
    // No-op if nothing changed
    const previous = (current[edit.field] ?? '') as string
    if (trimmed === previous) {
      setEdit(null)
      return
    }
    // Skill cannot be empty; domain may be cleared.
    if (edit.field === 'skill' && !trimmed) {
      showToast('Skill cannot be empty.', 'danger')
      return
    }
    setSaving(true)
    try {
      const body: { skill?: string; domain?: string | null } = {}
      if (edit.field === 'skill') body.skill = trimmed
      else body.domain = trimmed || null
      const updated = await patch<IdentifierRow>(`/api/identifiers/${edit.id}`, body)
      setRows(prev => prev.map(r => (r.id === updated.id ? updated : r)))
      showToast('Saved.', 'success')
      setEdit(null)
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to save.', 'danger')
    } finally {
      setSaving(false)
    }
  }

  async function confirmDelete(id: string) {
    setSaving(true)
    try {
      await del(`/api/identifiers/${id}`)
      setRows(prev => prev.filter(r => r.id !== id))
      showToast('Identifier removed.', 'success')
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Delete failed.', 'danger')
    } finally {
      setSaving(false)
      setPendingDeleteId(null)
    }
  }

  const filtered = useMemo(() => {
    if (!search.trim()) return rows
    const q = search.trim().toLowerCase()
    return rows.filter(r =>
      r.token.toLowerCase().includes(q) ||
      r.skill.toLowerCase().includes(q) ||
      (r.domain ?? '').toLowerCase().includes(q),
    )
  }, [rows, search])

  const tdCellStyle: CSSProperties = {
    cursor: 'text',
    padding: '2px 4px',
    borderRadius: 4,
    minHeight: 22,
    display: 'inline-block',
  }

  function renderEditable(row: IdentifierRow, field: EditableField) {
    const isEditing = edit?.id === row.id && edit.field === field
    const value = (row[field] ?? '') as string
    if (!isEditing) {
      return (
        <span
          onClick={() => startEdit(row, field)}
          style={tdCellStyle}
          title="Click to edit"
        >
          {value || <span style={{ color: 'var(--color-text-muted)' }}>—</span>}
        </span>
      )
    }
    return (
      <span style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}>
        <input
          autoFocus
          value={edit.value}
          onChange={e => setEdit({ ...edit, value: e.target.value })}
          onKeyDown={e => {
            if (e.key === 'Enter') {
              e.preventDefault()
              commitEdit()
            } else if (e.key === 'Escape') {
              e.preventDefault()
              cancelEdit()
            }
          }}
          disabled={saving}
          style={{
            background: 'var(--color-bg-elevated)',
            border: '1px solid var(--color-accent)',
            borderRadius: 'var(--radius-sm)',
            color: 'var(--color-text-primary)',
            font: 'inherit',
            fontSize: 'var(--text-sm)',
            padding: '2px 6px',
            outline: 'none',
            width: 140,
          }}
        />
        <button
          onClick={commitEdit}
          disabled={saving}
          aria-label="Save"
          style={iconBtnStyle('var(--color-success)')}
        >
          <Check size={14} />
        </button>
        <button
          onClick={cancelEdit}
          disabled={saving}
          aria-label="Cancel"
          style={iconBtnStyle('var(--color-text-muted)')}
        >
          <XIcon size={14} />
        </button>
      </span>
    )
  }

  const columns: TableColumn<IdentifierRow>[] = [
    {
      key: 'token',
      header: 'Token',
      render: r => (
        <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--color-text-primary)' }}>
          {r.token}
        </span>
      ),
    },
    {
      key: 'skill',
      header: 'Skill',
      render: r => renderEditable(r, 'skill'),
    },
    {
      key: 'domain',
      header: 'Domain',
      render: r => renderEditable(r, 'domain'),
    },
    {
      key: 'confidence',
      header: 'Confidence',
      render: r => confidenceBadge(r.confidence),
    },
    {
      key: 'occurrenceCount',
      header: 'Occurrences',
      align: 'right',
      render: r => <span>{r.occurrenceCount}</span>,
    },
    {
      key: 'firstSeenAt',
      header: 'First seen',
      render: r => <span style={{ color: 'var(--color-text-secondary)' }}>{formatDate(r.firstSeenAt)}</span>,
    },
    {
      key: 'lastSeenAt',
      header: 'Last seen',
      render: r => <span style={{ color: 'var(--color-text-secondary)' }}>{formatDate(r.lastSeenAt)}</span>,
    },
    {
      key: 'actions',
      header: '',
      align: 'right',
      render: r => {
        const isPending = pendingDeleteId === r.id
        if (isPending) {
          return (
            <span style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}>
              <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-muted)' }}>Delete?</span>
              <Button size="sm" variant="danger" onClick={() => confirmDelete(r.id)} disabled={saving}>
                Yes
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setPendingDeleteId(null)} disabled={saving}>
                No
              </Button>
            </span>
          )
        }
        return (
          <button
            onClick={() => setPendingDeleteId(r.id)}
            aria-label="Delete identifier"
            style={iconBtnStyle('var(--color-danger)')}
          >
            <Trash2 size={14} />
          </button>
        )
      },
    },
  ]

  if (!isLead) {
    return (
      <div style={{ maxWidth: 720, margin: '0 auto', fontFamily: 'var(--font-sans)' }}>
        <Card>
          <CardBody>
            <EmptyState
              title="Lead access required"
              description="The Team Glossary is available to leads and execs only."
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
            Team Glossary
          </h1>
          <p style={{ color: 'var(--color-text-muted)', fontSize: 'var(--text-sm)', margin: '4px 0 0' }}>
            Identifiers your team has used in past tickets, mapped to skills and domains.
          </p>
        </div>
        {activeTeam && (
          <Badge variant="default">{activeTeam.teamName}</Badge>
        )}
      </div>

      <Card>
        <CardHeader>
          <div style={{ display: 'flex', gap: 12, alignItems: 'center', flex: 1, flexWrap: 'wrap' }}>
            <Input
              type="text"
              placeholder="Search token, skill, or domain"
              value={search}
              onChange={e => setSearch(e.target.value)}
              containerStyle={{ flex: 1, minWidth: 200, maxWidth: 320 }}
            />
            <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={lowOnly}
                onChange={e => setLowOnly(e.target.checked)}
              />
              <span style={{ color: 'var(--color-text-primary)', fontSize: 'var(--text-sm)' }}>
                Show low-confidence only
              </span>
            </label>
          </div>
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
                Loading identifiers…
              </div>
            </div>
          ) : error ? (
            <div style={{ padding: 24, color: 'var(--color-danger)', fontSize: 'var(--text-sm)' }}>
              {error}
            </div>
          ) : rows.length === 0 ? (
            <EmptyState
              title="No identifiers yet"
              description="They're learned automatically from your project activity."
            />
          ) : (
            <Table
              columns={columns}
              data={filtered}
              rowKey={r => r.id}
              emptyState={
                <span style={{ color: 'var(--color-text-muted)', fontSize: 'var(--text-sm)' }}>
                  No identifiers match your filters.
                </span>
              }
            />
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
          }}
          role="status"
        >
          {toast.message}
        </div>
      )}
    </div>
  )
}

function iconBtnStyle(color: string): CSSProperties {
  return {
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    width: 22,
    height: 22,
    borderRadius: 4,
    border: '1px solid var(--color-border)',
    background: 'transparent',
    color,
    cursor: 'pointer',
    padding: 0,
  }
}
