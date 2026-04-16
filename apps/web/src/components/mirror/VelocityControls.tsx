// apps/web/src/components/mirror/VelocityControls.tsx

import { Card, CardBody } from '../ui/Card'

interface VelocityControlsProps {
  window: number
  setWindow: (value: number) => void
  fromDate: string | null
  setFromDate: (value: string | null) => void
  visibleMetrics: string[]
  setVisibleMetrics: (value: string[]) => void
}

const METRICS = [
  { key: 'rolling', label: 'Rolling Average' },
  { key: 'weighted', label: 'Weighted Average' },
  { key: 'stddev', label: 'Std Dev' },
]

export function VelocityControls({
  window,
  setWindow,
  fromDate,
  setFromDate,
  visibleMetrics,
  setVisibleMetrics,
}: VelocityControlsProps) {
  function toggleMetric(key: string) {
    setVisibleMetrics(
      visibleMetrics.includes(key)
        ? visibleMetrics.filter(m => m !== key)
        : [...visibleMetrics, key]
    )
  }

  return (
    <Card>
      <CardBody style={{ padding: '10px 12px', display: 'flex', alignItems: 'center', gap: 24, flexWrap: 'wrap' }}>
        {/* Sprint window slider */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <label style={{ color: 'var(--color-text-muted)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-xs)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', whiteSpace: 'nowrap' }}>
            Sprint window
          </label>
          <input
            type="range"
            min={3}
            max={12}
            value={window}
            onChange={e => setWindow(Number(e.target.value))}
            style={{ width: 100, accentColor: 'var(--color-accent)', cursor: 'pointer' }}
          />
          <span style={{ color: 'var(--color-text-primary)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)', fontWeight: 600, minWidth: 16, textAlign: 'right' }}>
            {window}
          </span>
        </div>

        {/* Divider */}
        <div style={{ width: 1, height: 24, background: 'var(--color-border)', flexShrink: 0 }} />

        {/* From date picker */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <label style={{ color: 'var(--color-text-muted)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-xs)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', whiteSpace: 'nowrap' }}>
            From date
          </label>
          <input
            type="date"
            value={fromDate ?? ''}
            onChange={e => setFromDate(e.target.value || null)}
            style={{
              background: 'var(--color-bg-tertiary)',
              border: '1px solid var(--color-border)',
              borderRadius: 'var(--radius-sm)',
              color: 'var(--color-text-primary)',
              fontFamily: 'var(--font-sans)',
              fontSize: 'var(--text-xs)',
              padding: '2px 6px',
            }}
          />
          {fromDate && (
            <button
              onClick={() => setFromDate(null)}
              style={{
                background: 'none',
                border: 'none',
                color: 'var(--color-text-muted)',
                cursor: 'pointer',
                fontSize: 14,
                lineHeight: 1,
                padding: '0 2px',
              }}
              title="Clear date"
            >
              ✕
            </button>
          )}
        </div>

        {/* Divider */}
        <div style={{ width: 1, height: 24, background: 'var(--color-border)', flexShrink: 0 }} />

        {/* Metric checkboxes */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          {METRICS.map(({ key, label }) => (
            <label
              key={key}
              style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', color: 'var(--color-text-secondary)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)', userSelect: 'none' }}
            >
              <input
                type="checkbox"
                checked={visibleMetrics.includes(key)}
                onChange={() => toggleMetric(key)}
                style={{ accentColor: 'var(--color-accent)', cursor: 'pointer' }}
              />
              {label}
            </label>
          ))}
        </div>
      </CardBody>
    </Card>
  )
}
