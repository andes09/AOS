// apps/web/src/pages/DependencyRadarPage.tsx

import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '@clerk/clerk-react'
import { useApi, ApiError } from '../lib/api'
import { DependencyItem } from '../components/radar/DependencyItem'
import { Alert } from '../components/ui/Alert'
import { Button } from '../components/ui/Button'
import { Card, CardHeader, CardBody } from '../components/ui/Card'
import { Input } from '../components/ui/Input'
import { Select } from '../components/ui/Select'
import { Badge } from '../components/ui/Badge'
import type { AlertVariant } from '../components/ui/Alert'
import type { RadarResponse, ScanResponse, DependencyType, RiskLevel } from '../types/dependencyRadar'

const TEAM_ID = 'default'

function riskBand(score: number): 'high' | 'medium' | 'low' {
  if (score < 40) return 'high'
  if (score < 70) return 'medium'
  return 'low'
}

const RISK_ALERT_VARIANT: Record<string, AlertVariant> = {
  high: 'danger',
  medium: 'warning',
  low: 'success',
}

const RISK_LABEL: Record<string, string> = {
  high: 'High Risk',
  medium: 'Moderate Risk',
  low: 'Low Risk',
}

function Section({
  title,
  level,
  deps,
  onResolve,
}: {
  title: string
  level: RiskLevel
  deps: RadarResponse['dependencies']
  onResolve: (id: string) => void
}) {
  const [open, setOpen] = useState(true)
  const filtered = deps.filter(d => d.riskLevel === level)

  return (
    <Card style={{ marginBottom: 12 }}>
      <CardHeader>
        <button
          onClick={() => setOpen(o => !o)}
          style={{
            background: 'none',
            border: 'none',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: 0,
            width: '100%',
            textAlign: 'left',
          }}
        >
          <span style={{
            color: 'var(--color-text-primary)',
            fontFamily: 'var(--font-sans)',
            fontSize: 'var(--text-sm)',
            fontWeight: 600,
          }}>
            {title}
          </span>
          <Badge variant="default">{filtered.length}</Badge>
          <span style={{ color: 'var(--color-text-muted)', fontSize: 'var(--text-xs)', marginLeft: 'auto' }}>
            {open ? '▲' : '▼'}
          </span>
        </button>
      </CardHeader>

      {open && (
        <CardBody style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {filtered.length === 0 ? (
            <div style={{ color: 'var(--color-text-muted)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)' }}>
              No {level} risk dependencies
            </div>
          ) : (
            filtered.map(dep => (
              <DependencyItem key={dep.id} dep={dep} onResolve={onResolve} />
            ))
          )}
        </CardBody>
      )}
    </Card>
  )
}

export function DependencyRadarPage() {
  const { get, post } = useApi()
  const { isLoaded, isSignedIn } = useAuth()
  const queryClient = useQueryClient()

  const [scanning, setScanning] = useState(false)
  const [toast, setToast] = useState<string | null>(null)

  const [formOpen, setFormOpen] = useState(false)
  const [formTicketKey, setFormTicketKey] = useState('')
  const [formTicketTitle, setFormTicketTitle] = useState('')
  const [formDepType, setFormDepType] = useState<DependencyType>('blocks')
  const [formRiskLevel, setFormRiskLevel] = useState<RiskLevel>('medium')
  const [formDescription, setFormDescription] = useState('')
  const [formSubmitting, setFormSubmitting] = useState(false)

  const { data, isLoading, isError, error } = useQuery<RadarResponse, ApiError>({
    queryKey: ['dependency-radar', TEAM_ID],
    queryFn: () => get<RadarResponse>(`/api/dependency-radar/team/${TEAM_ID}`),
    enabled: isLoaded && isSignedIn,
  })
  const is403 = isError && error instanceof ApiError && error.status === 403

  function handleResolve(id: string) {
    queryClient.setQueryData<RadarResponse>(['dependency-radar', TEAM_ID], old => {
      if (!old) return old
      return {
        ...old,
        dependencies: old.dependencies.filter(d => d.id !== id),
      }
    })
  }

  async function handleScanJira() {
    setScanning(true)
    try {
      const result = await post<ScanResponse>('/api/dependency-radar/scan', { teamId: TEAM_ID })
      await queryClient.invalidateQueries({ queryKey: ['dependency-radar', TEAM_ID] })
      showToast(`Scan complete — ${result.dependenciesFound} dependencies found`)
    } catch {
      showToast('Scan failed')
    } finally {
      setScanning(false)
    }
  }

  function showToast(msg: string) {
    setToast(msg)
    setTimeout(() => setToast(null), 3500)
  }

  async function handleAddDep(e: React.FormEvent) {
    e.preventDefault()
    setFormSubmitting(true)
    try {
      await post('/api/dependency-radar/dependency', {
        teamId: TEAM_ID,
        ticketKey: formTicketKey,
        ticketTitle: formTicketTitle,
        dependencyType: formDepType,
        riskLevel: formRiskLevel,
        description: formDescription || null,
      })
      await queryClient.invalidateQueries({ queryKey: ['dependency-radar', TEAM_ID] })
      setFormOpen(false)
      setFormTicketKey('')
      setFormTicketTitle('')
      setFormDepType('blocks')
      setFormRiskLevel('medium')
      setFormDescription('')
    } catch {
      // Keep form open on error
    } finally {
      setFormSubmitting(false)
    }
  }

  const band = data ? riskBand(data.riskScore) : null

  return (
    <div style={{ fontFamily: 'var(--font-sans)', minHeight: '100%' }}>

      {/* Toast */}
      {toast && (
        <div style={{
          position: 'fixed',
          bottom: 24,
          right: 24,
          background: 'var(--color-bg-elevated)',
          border: '1px solid var(--color-border)',
          color: 'var(--color-text-primary)',
          borderRadius: 'var(--radius-lg)',
          padding: '10px 16px',
          fontSize: 'var(--text-sm)',
          zIndex: 1000,
          boxShadow: 'var(--shadow-md)',
          fontFamily: 'var(--font-sans)',
        }}>
          {toast}
        </div>
      )}

      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 20 }}>
        <h1 style={{ color: 'var(--color-text-primary)', fontSize: 'var(--text-xl)', fontWeight: 700, margin: 0 }}>
          Dependency Radar
        </h1>
        <div style={{ display: 'flex', gap: 8 }}>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setFormOpen(o => !o)}
          >
            {formOpen ? 'Cancel' : '+ Add Dependency'}
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={handleScanJira}
            disabled={scanning}
          >
            {scanning ? 'Scanning…' : 'Scan Jira'}
          </Button>
        </div>
      </div>

      {/* Aggregate risk score banner */}
      {band && data && (
        <Alert
          variant={RISK_ALERT_VARIANT[band]}
          title={`Risk Score: ${data.riskScore}`}
          style={{ marginBottom: 20 }}
        >
          {RISK_LABEL[band]}
        </Alert>
      )}

      {/* Inline Add Dependency form */}
      {formOpen && (
        <Card style={{ marginBottom: 20 }}>
          <CardHeader>
            <span style={{ color: 'var(--color-text-secondary)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-xs)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              Add Dependency
            </span>
          </CardHeader>
          <CardBody>
            <form onSubmit={handleAddDep} style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                <Input
                  required
                  placeholder="Ticket Key (e.g. PROJ-123)"
                  value={formTicketKey}
                  onChange={e => setFormTicketKey(e.target.value)}
                  containerStyle={{ flex: 1, minWidth: 140 }}
                />
                <Input
                  required
                  placeholder="Ticket Title"
                  value={formTicketTitle}
                  onChange={e => setFormTicketTitle(e.target.value)}
                  containerStyle={{ flex: 2, minWidth: 200 }}
                />
              </div>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                <Select
                  value={formDepType}
                  onChange={e => setFormDepType(e.target.value as DependencyType)}
                  containerStyle={{ flex: 1 }}
                >
                  <option value="blocks">Blocks</option>
                  <option value="is_blocked_by">Blocked By</option>
                  <option value="external_service">External Service</option>
                  <option value="cross_team">Cross-Team</option>
                </Select>
                <Select
                  value={formRiskLevel}
                  onChange={e => setFormRiskLevel(e.target.value as RiskLevel)}
                  containerStyle={{ flex: 1 }}
                >
                  <option value="high">High Risk</option>
                  <option value="medium">Medium Risk</option>
                  <option value="low">Low Risk</option>
                </Select>
              </div>
              <Input
                placeholder="Description (optional)"
                value={formDescription}
                onChange={e => setFormDescription(e.target.value)}
              />
              <div>
                <Button type="submit" variant="primary" size="sm" disabled={formSubmitting}>
                  {formSubmitting ? 'Adding…' : 'Add'}
                </Button>
              </div>
            </form>
          </CardBody>
        </Card>
      )}

      {/* Loading / error states */}
      {isLoading && (
        <div style={{ color: 'var(--color-text-muted)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)' }}>
          Loading dependencies…
        </div>
      )}
      {is403 && (
        <Alert variant="danger">Access denied. Lead role required.</Alert>
      )}
      {isError && !is403 && (
        <div style={{ color: 'var(--color-danger)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)' }}>
          Failed to load dependencies
        </div>
      )}

      {/* Grouped sections */}
      {data && (
        <>
          <Section title="High Risk" level="high" deps={data.dependencies} onResolve={handleResolve} />
          <Section title="Medium Risk" level="medium" deps={data.dependencies} onResolve={handleResolve} />
          <Section title="Low Risk" level="low" deps={data.dependencies} onResolve={handleResolve} />
        </>
      )}
    </div>
  )
}
