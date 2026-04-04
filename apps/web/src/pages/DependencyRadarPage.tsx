// apps/web/src/pages/DependencyRadarPage.tsx

import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '@clerk/clerk-react'
import { useApi } from '../lib/api'
import { DependencyItem } from '../components/radar/DependencyItem'
import type { RadarResponse, ScanResponse, DependencyType, RiskLevel } from '../types/dependencyRadar'

const TEAM_ID = 'default'

const RISK_BANNER: Record<string, { bg: string; border: string; color: string; label: string }> = {
  high:   { bg: '#450a0a', border: '#7f1d1d', color: '#fca5a5', label: 'High Risk' },
  medium: { bg: '#451a03', border: '#78350f', color: '#fcd34d', label: 'Moderate Risk' },
  low:    { bg: '#052e16', border: '#14532d', color: '#86efac', label: 'Low Risk' },
}

function riskBand(score: number): 'high' | 'medium' | 'low' {
  if (score < 40) return 'high'
  if (score < 70) return 'medium'
  return 'low'
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
    <div style={{ marginBottom: 16 }}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          background: 'none',
          border: 'none',
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          padding: '6px 0',
          width: '100%',
          textAlign: 'left',
        }}
      >
        <span style={{ color: '#94a3b8', fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          {title}
        </span>
        <span style={{
          background: '#2d3148',
          color: '#64748b',
          borderRadius: '50%',
          width: 18,
          height: 18,
          fontSize: 10,
          fontWeight: 700,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}>
          {filtered.length}
        </span>
        <span style={{ color: '#475569', fontSize: 12, marginLeft: 'auto' }}>{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {filtered.length === 0 ? (
            <div style={{ color: '#475569', fontSize: 13, padding: '4px 0 8px' }}>
              No {level} risk dependencies
            </div>
          ) : (
            filtered.map(dep => (
              <DependencyItem key={dep.id} dep={dep} onResolve={onResolve} />
            ))
          )}
        </div>
      )}
    </div>
  )
}

export function DependencyRadarPage() {
  const { get, post } = useApi()
  const { isLoaded, isSignedIn } = useAuth()
  const queryClient = useQueryClient()

  const [scanning, setScanning] = useState(false)
  const [toast, setToast] = useState<string | null>(null)

  // Add dep form state
  const [formOpen, setFormOpen] = useState(false)
  const [formTicketKey, setFormTicketKey] = useState('')
  const [formTicketTitle, setFormTicketTitle] = useState('')
  const [formDepType, setFormDepType] = useState<DependencyType>('blocks')
  const [formRiskLevel, setFormRiskLevel] = useState<RiskLevel>('medium')
  const [formDescription, setFormDescription] = useState('')
  const [formSubmitting, setFormSubmitting] = useState(false)

  const { data, isLoading, isError } = useQuery<RadarResponse>({
    queryKey: ['dependency-radar', TEAM_ID],
    queryFn: () => get<RadarResponse>(`/api/dependency-radar/team/${TEAM_ID}`),
    enabled: isLoaded && isSignedIn,
  })

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
  const banner = band ? RISK_BANNER[band] : null

  return (
    <div style={{ background: '#0f1117', minHeight: '100%', padding: '1.5rem', fontFamily: 'system-ui, sans-serif' }}>

      {/* Toast */}
      {toast && (
        <div style={{
          position: 'fixed',
          bottom: 24,
          right: 24,
          background: '#1e2030',
          border: '1px solid #334155',
          color: '#e2e8f0',
          borderRadius: 8,
          padding: '10px 16px',
          fontSize: 13,
          zIndex: 1000,
          boxShadow: '0 4px 12px rgba(0,0,0,0.4)',
        }}>
          {toast}
        </div>
      )}

      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 20 }}>
        <h1 style={{ color: '#e2e8f0', fontSize: 22, fontWeight: 800, margin: 0, letterSpacing: '-0.01em' }}>
          Dependency Radar
        </h1>
        <div style={{ display: 'flex', gap: 8 }}>
          <button
            onClick={() => setFormOpen(o => !o)}
            style={{
              background: '#1e2030',
              border: '1px solid #334155',
              color: '#94a3b8',
              borderRadius: 6,
              padding: '6px 12px',
              fontSize: 12,
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            {formOpen ? 'Cancel' : '+ Add Dependency'}
          </button>
          <button
            onClick={handleScanJira}
            disabled={scanning}
            style={{
              background: scanning ? '#1e3a5f' : '#1e40af',
              border: 'none',
              color: scanning ? '#64748b' : '#bfdbfe',
              borderRadius: 6,
              padding: '6px 14px',
              fontSize: 12,
              fontWeight: 600,
              cursor: scanning ? 'not-allowed' : 'pointer',
            }}
          >
            {scanning ? 'Scanning…' : 'Scan Jira'}
          </button>
        </div>
      </div>

      {/* Aggregate risk score banner */}
      {banner && data && (
        <div style={{
          background: banner.bg,
          border: `1px solid ${banner.border}`,
          borderRadius: 8,
          padding: '12px 16px',
          marginBottom: 20,
          display: 'flex',
          alignItems: 'center',
          gap: 12,
        }}>
          <span style={{ color: banner.color, fontWeight: 700, fontSize: 15 }}>
            Risk Score: {data.riskScore}
          </span>
          <span style={{ color: banner.color, fontSize: 13 }}>— {banner.label}</span>
        </div>
      )}

      {/* Inline Add Dependency form */}
      {formOpen && (
        <form
          onSubmit={handleAddDep}
          style={{
            background: '#1e2030',
            borderRadius: 8,
            padding: '1rem',
            marginBottom: 20,
            display: 'flex',
            flexDirection: 'column',
            gap: 10,
          }}
        >
          <div style={{ color: '#94a3b8', fontSize: 12, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            Add Dependency
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <input
              required
              placeholder="Ticket Key (e.g. PROJ-123)"
              value={formTicketKey}
              onChange={e => setFormTicketKey(e.target.value)}
              style={inputStyle}
            />
            <input
              required
              placeholder="Ticket Title"
              value={formTicketTitle}
              onChange={e => setFormTicketTitle(e.target.value)}
              style={{ ...inputStyle, flex: 2, minWidth: 200 }}
            />
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <select value={formDepType} onChange={e => setFormDepType(e.target.value as DependencyType)} style={selectStyle}>
              <option value="blocks">Blocks</option>
              <option value="is_blocked_by">Blocked By</option>
              <option value="external_service">External Service</option>
              <option value="cross_team">Cross-Team</option>
            </select>
            <select value={formRiskLevel} onChange={e => setFormRiskLevel(e.target.value as RiskLevel)} style={selectStyle}>
              <option value="high">High Risk</option>
              <option value="medium">Medium Risk</option>
              <option value="low">Low Risk</option>
            </select>
          </div>
          <input
            placeholder="Description (optional)"
            value={formDescription}
            onChange={e => setFormDescription(e.target.value)}
            style={{ ...inputStyle, width: '100%' }}
          />
          <div>
            <button
              type="submit"
              disabled={formSubmitting}
              style={{
                background: formSubmitting ? '#1e3a5f' : '#1e40af',
                border: 'none',
                color: formSubmitting ? '#64748b' : '#bfdbfe',
                borderRadius: 6,
                padding: '6px 16px',
                fontSize: 12,
                fontWeight: 600,
                cursor: formSubmitting ? 'not-allowed' : 'pointer',
              }}
            >
              {formSubmitting ? 'Adding…' : 'Add'}
            </button>
          </div>
        </form>
      )}

      {/* Loading / error states */}
      {isLoading && (
        <div style={{ color: '#64748b', fontSize: 13 }}>Loading dependencies…</div>
      )}
      {isError && (
        <div style={{ color: '#ef4444', fontSize: 13 }}>Failed to load dependencies</div>
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

const inputStyle: React.CSSProperties = {
  background: '#0f1117',
  border: '1px solid #334155',
  color: '#e2e8f0',
  borderRadius: 6,
  padding: '6px 10px',
  fontSize: 12,
  outline: 'none',
  flex: 1,
  minWidth: 120,
}

const selectStyle: React.CSSProperties = {
  background: '#0f1117',
  border: '1px solid #334155',
  color: '#e2e8f0',
  borderRadius: 6,
  padding: '6px 10px',
  fontSize: 12,
  outline: 'none',
  cursor: 'pointer',
}
