import { useState, useEffect } from 'react'
import { useApi } from '../../lib/api'
import { Card, CardBody } from '../ui/Card'
import { Button } from '../ui/Button'
import type { TeamCapacityResponse, DeveloperCapacityItem } from '../../types/capacity'

interface CapacitySettingsPanelProps {
  onCapacityLoaded?: (data: TeamCapacityResponse) => void
}

const inputStyle: React.CSSProperties = {
  width: 60,
  background: 'var(--color-bg-tertiary)',
  border: '1px solid var(--color-border)',
  borderRadius: 'var(--radius-sm)',
  color: 'var(--color-text-primary)',
  fontFamily: 'var(--font-sans)',
  fontSize: 'var(--text-sm)',
  padding: '2px 6px',
  textAlign: 'right',
  outline: 'none',
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
      // Non-critical
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
        sprintId: null, capacityPct, ptoDays, notes: null,
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
    return (
      <div style={{ color: 'var(--color-text-muted)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)', padding: '1rem 0' }}>
        Loading capacity data...
      </div>
    )
  }

  if (!data) return null

  return (
    <Card>
      <CardBody>
        <div style={{
          color: 'var(--color-text-muted)',
          fontFamily: 'var(--font-sans)',
          fontSize: 'var(--text-xs)',
          fontWeight: 700,
          textTransform: 'uppercase',
          letterSpacing: '0.06em',
          marginBottom: 12,
        }}>
          Capacity Settings
        </div>

        {/* Team-wide meeting overhead */}
        <div style={{ marginBottom: 16, display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          <span style={{ color: 'var(--color-text-secondary)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)', minWidth: 180 }}>
            Meeting overhead %
          </span>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <input
              type="range"
              min={0}
              max={50}
              value={overheadInput}
              onChange={e => setOverheadInput(e.target.value)}
              style={{ width: 120 }}
            />
            <span style={{ color: 'var(--color-text-primary)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)', minWidth: 36 }}>
              {overheadInput}%
            </span>
            <Button size="sm" variant="secondary" onClick={handleSaveOverhead} disabled={overheadSaving}>
              {overheadSaving ? 'Saving...' : 'Save'}
            </Button>
            {overheadMsg && (
              <span style={{
                fontFamily: 'var(--font-sans)',
                fontSize: 'var(--text-xs)',
                color: overheadMsg === 'Saved' ? 'var(--color-success)' : 'var(--color-danger)',
              }}>
                {overheadMsg}
              </span>
            )}
          </div>
        </div>

        {/* Per-developer overrides */}
        {data.developers.length > 0 && (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)' }}>
            <thead>
              <tr>
                {['Developer', 'Base Vel.', 'PTO Days', 'Capacity %', 'Effective Pts', ''].map((h, i) => (
                  <th key={i} style={{
                    textAlign: i === 0 ? 'left' : 'right',
                    padding: '4px 8px',
                    color: 'var(--color-text-muted)',
                    fontFamily: 'var(--font-sans)',
                    fontSize: 'var(--text-xs)',
                    fontWeight: 600,
                    textTransform: 'uppercase',
                    letterSpacing: '0.05em',
                    borderBottom: '1px solid var(--color-border)',
                  }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.developers.map(dev => (
                <tr key={dev.developerId} style={{ borderTop: '1px solid var(--color-border-subtle)' }}>
                  <td style={{ padding: '6px 8px' }}>
                    <span style={{ color: dev.isHighMeetingLoad ? 'var(--color-warning)' : 'var(--color-text-primary)', fontFamily: 'var(--font-sans)' }}>
                      {dev.displayName}
                    </span>
                    {dev.isHighMeetingLoad && (
                      <span style={{ marginLeft: 6, fontFamily: 'var(--font-sans)', fontSize: 'var(--text-xs)', color: 'var(--color-warning)' }}>
                        High load
                      </span>
                    )}
                  </td>
                  <td style={{ textAlign: 'right', padding: '6px 8px', color: 'var(--color-text-secondary)' }}>
                    {dev.baseVelocity.toFixed(1)}
                  </td>
                  <td style={{ textAlign: 'right', padding: '6px 8px' }}>
                    <input
                      type="number" min={0} max={10} step={0.5}
                      value={devOverrides[dev.developerId]?.ptoDays ?? '0'}
                      onChange={e => setDevOverrides(m => ({ ...m, [dev.developerId]: { ...m[dev.developerId], ptoDays: e.target.value } }))}
                      style={inputStyle}
                    />
                  </td>
                  <td style={{ textAlign: 'right', padding: '6px 8px' }}>
                    <input
                      type="number" min={0} max={100} step={5}
                      value={devOverrides[dev.developerId]?.capacityPct ?? '100'}
                      onChange={e => setDevOverrides(m => ({ ...m, [dev.developerId]: { ...m[dev.developerId], capacityPct: e.target.value } }))}
                      style={inputStyle}
                    />
                  </td>
                  <td style={{
                    textAlign: 'right',
                    padding: '6px 8px',
                    color: dev.isHighMeetingLoad ? 'var(--color-warning)' : 'var(--color-success)',
                    fontFamily: 'var(--font-sans)',
                    fontWeight: 600,
                  }}>
                    {dev.effectiveCapacityPts.toFixed(1)}
                  </td>
                  <td style={{ padding: '6px 8px' }}>
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => handleSaveDev(dev)}
                      disabled={savingDev === dev.developerId}
                    >
                      {savingDev === dev.developerId ? 'Saving...' : 'Save'}
                    </Button>
                    {devMsg[dev.developerId] && (
                      <span style={{
                        marginLeft: 6,
                        fontFamily: 'var(--font-sans)',
                        fontSize: 'var(--text-xs)',
                        color: devMsg[dev.developerId] === 'Saved' ? 'var(--color-success)' : 'var(--color-danger)',
                      }}>
                        {devMsg[dev.developerId]}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </CardBody>
    </Card>
  )
}
