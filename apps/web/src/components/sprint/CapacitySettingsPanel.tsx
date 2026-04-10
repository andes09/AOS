import { useState, useEffect } from 'react'
import { useApi } from '../../lib/api'
import type { TeamCapacityResponse, DeveloperCapacityItem } from '../../types/capacity'

interface CapacitySettingsPanelProps {
  onCapacityLoaded?: (data: TeamCapacityResponse) => void
}

export function CapacitySettingsPanel({ onCapacityLoaded }: CapacitySettingsPanelProps) {
  const { get, patch, put } = useApi()
  const [data, setData] = useState<TeamCapacityResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [overheadInput, setOverheadInput] = useState('')
  const [overheadSaving, setOverheadSaving] = useState(false)
  const [overheadMsg, setOverheadMsg] = useState<string | null>(null)
  const [devOverrides, setDevOverrides] = useState<Record<string, { ptoDays: string; capacityPct: string }>>({})
  const [savingDev, setSavingDev] = useState<string | null>(null)
  const [devMsg, setDevMsg] = useState<Record<string, string>>({})

  async function loadCapacity() {
    try {
      const resp = await get<TeamCapacityResponse>('/api/capacity/team/default')
      setData(resp)
      setOverheadInput(String(Math.round(resp.meetingOverheadPct * 100)))
      const initial: Record<string, { ptoDays: string; capacityPct: string }> = {}
      for (const dev of resp.developers) {
        initial[dev.developerId] = {
          ptoDays: String(dev.ptoDays),
          capacityPct: String(Math.round(dev.capacityPct * 100)),
        }
      }
      setDevOverrides(initial)
      onCapacityLoaded?.(resp)
    } catch {
      // Non-critical — capacity panel silently fails if endpoint unavailable
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { loadCapacity() }, [])

  async function handleSaveOverhead() {
    if (!data) return
    const pct = parseFloat(overheadInput) / 100
    if (isNaN(pct) || pct < 0 || pct > 1) {
      setOverheadMsg('Value must be between 0 and 100')
      return
    }
    setOverheadSaving(true)
    setOverheadMsg(null)
    try {
      await patch(`/api/capacity/team/${data.teamId}/overhead`, { meetingOverheadPct: pct })
      setOverheadMsg('Saved')
      await loadCapacity()
    } catch {
      setOverheadMsg('Failed to save')
    } finally {
      setOverheadSaving(false)
    }
  }

  async function handleSaveDev(dev: DeveloperCapacityItem) {
    if (!data) return
    const override = devOverrides[dev.developerId]
    if (!override) return
    setSavingDev(dev.developerId)
    setDevMsg(m => ({ ...m, [dev.developerId]: '' }))
    try {
      const capacityPct = parseFloat(override.capacityPct) / 100
      const ptoDays = parseFloat(override.ptoDays) || 0
      if (isNaN(capacityPct) || capacityPct < 0 || capacityPct > 1) {
        setDevMsg(m => ({ ...m, [dev.developerId]: 'Capacity % must be 0–100' }))
        return
      }
      await put(`/api/capacity/team/${data.teamId}/developers/${dev.developerId}/override`, {
        sprintId: null,
        capacityPct,
        ptoDays,
        notes: null,
      })
      setDevMsg(m => ({ ...m, [dev.developerId]: 'Saved' }))
      await loadCapacity()
    } catch {
      setDevMsg(m => ({ ...m, [dev.developerId]: 'Failed to save' }))
    } finally {
      setSavingDev(null)
    }
  }

  if (loading) {
    return <div style={{ color: '#64748b', fontSize: 13, padding: '1rem 0' }}>Loading capacity data...</div>
  }

  if (!data) return null

  return (
    <div style={{ background: '#1e2030', borderRadius: 8, border: '1px solid #2d2f45', padding: '1rem 1.25rem' }}>
      <div style={{ color: '#a5b4fc', fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 12 }}>
        Capacity Settings
      </div>

      {/* Team-wide meeting overhead */}
      <div style={{ marginBottom: 16, display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <span style={{ color: '#94a3b8', fontSize: 13, minWidth: 180 }}>Meeting overhead %</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <input
            type="range"
            min={0}
            max={50}
            value={overheadInput}
            onChange={e => setOverheadInput(e.target.value)}
            style={{ width: 120 }}
          />
          <span style={{ color: '#e2e8f0', fontSize: 13, minWidth: 36 }}>{overheadInput}%</span>
          <button
            onClick={handleSaveOverhead}
            disabled={overheadSaving}
            style={{
              background: overheadSaving ? '#374151' : '#6366f1',
              color: overheadSaving ? '#64748b' : '#fff',
              border: 'none',
              borderRadius: 6,
              padding: '4px 14px',
              fontSize: 12,
              fontWeight: 600,
              cursor: overheadSaving ? 'not-allowed' : 'pointer',
            }}
          >
            {overheadSaving ? 'Saving...' : 'Save'}
          </button>
          {overheadMsg && (
            <span style={{ fontSize: 12, color: overheadMsg === 'Saved' ? '#4ade80' : '#ef4444' }}>{overheadMsg}</span>
          )}
        </div>
      </div>

      {/* Per-developer overrides */}
      {data.developers.length > 0 && (
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ color: '#64748b', fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              <th style={{ textAlign: 'left', padding: '4px 8px', fontWeight: 600 }}>Developer</th>
              <th style={{ textAlign: 'right', padding: '4px 8px', fontWeight: 600 }}>Base Vel.</th>
              <th style={{ textAlign: 'right', padding: '4px 8px', fontWeight: 600 }}>PTO Days</th>
              <th style={{ textAlign: 'right', padding: '4px 8px', fontWeight: 600 }}>Capacity %</th>
              <th style={{ textAlign: 'right', padding: '4px 8px', fontWeight: 600 }}>Effective Pts</th>
              <th style={{ padding: '4px 8px' }} />
            </tr>
          </thead>
          <tbody>
            {data.developers.map(dev => (
              <tr key={dev.developerId} style={{ borderTop: '1px solid #2d2f45' }}>
                <td style={{ padding: '6px 8px' }}>
                  <span style={{ color: dev.isHighMeetingLoad ? '#fbbf24' : '#e2e8f0' }}>{dev.displayName}</span>
                  {dev.isHighMeetingLoad && <span style={{ marginLeft: 6, fontSize: 11, color: '#f97316' }}>⚠ High load</span>}
                </td>
                <td style={{ textAlign: 'right', padding: '6px 8px', color: '#94a3b8' }}>{dev.baseVelocity.toFixed(1)}</td>
                <td style={{ textAlign: 'right', padding: '6px 8px' }}>
                  <input
                    type="number"
                    min={0}
                    max={10}
                    step={0.5}
                    value={devOverrides[dev.developerId]?.ptoDays ?? '0'}
                    onChange={e => setDevOverrides(m => ({ ...m, [dev.developerId]: { ...m[dev.developerId], ptoDays: e.target.value } }))}
                    style={{ width: 60, background: '#0f1117', border: '1px solid #2d2f45', borderRadius: 4, color: '#e2e8f0', fontSize: 13, padding: '2px 6px', textAlign: 'right' }}
                  />
                </td>
                <td style={{ textAlign: 'right', padding: '6px 8px' }}>
                  <input
                    type="number"
                    min={0}
                    max={100}
                    step={5}
                    value={devOverrides[dev.developerId]?.capacityPct ?? '100'}
                    onChange={e => setDevOverrides(m => ({ ...m, [dev.developerId]: { ...m[dev.developerId], capacityPct: e.target.value } }))}
                    style={{ width: 60, background: '#0f1117', border: '1px solid #2d2f45', borderRadius: 4, color: '#e2e8f0', fontSize: 13, padding: '2px 6px', textAlign: 'right' }}
                  />
                </td>
                <td style={{ textAlign: 'right', padding: '6px 8px', color: dev.isHighMeetingLoad ? '#fbbf24' : '#6ee7b7', fontWeight: 600 }}>
                  {dev.effectiveCapacityPts.toFixed(1)}
                </td>
                <td style={{ padding: '6px 8px' }}>
                  <button
                    onClick={() => handleSaveDev(dev)}
                    disabled={savingDev === dev.developerId}
                    style={{
                      background: savingDev === dev.developerId ? '#374151' : '#1e3a5f',
                      color: savingDev === dev.developerId ? '#64748b' : '#60a5fa',
                      border: '1px solid #1d4ed8',
                      borderRadius: 4,
                      padding: '3px 10px',
                      fontSize: 12,
                      fontWeight: 600,
                      cursor: savingDev === dev.developerId ? 'not-allowed' : 'pointer',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {savingDev === dev.developerId ? 'Saving...' : 'Save'}
                  </button>
                  {devMsg[dev.developerId] && (
                    <span style={{ marginLeft: 6, fontSize: 11, color: devMsg[dev.developerId] === 'Saved' ? '#4ade80' : '#ef4444' }}>
                      {devMsg[dev.developerId]}
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
