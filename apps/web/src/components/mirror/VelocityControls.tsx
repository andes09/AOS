// apps/web/src/components/mirror/VelocityControls.tsx

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
    <div style={{
      background: '#1e2030',
      borderRadius: 8,
      padding: '0.875rem 1rem',
      display: 'flex',
      alignItems: 'center',
      gap: 24,
      flexWrap: 'wrap',
    }}>
      {/* Sprint window slider */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <label style={{ color: '#94a3b8', fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', whiteSpace: 'nowrap' }}>
          Sprint window
        </label>
        <input
          type="range"
          min={3}
          max={12}
          value={window}
          onChange={e => setWindow(Number(e.target.value))}
          style={{ width: 100, accentColor: '#6366f1', cursor: 'pointer' }}
        />
        <span style={{ color: '#e2e8f0', fontSize: 12, fontWeight: 600, minWidth: 16, textAlign: 'right' }}>
          {window}
        </span>
      </div>

      {/* Divider */}
      <div style={{ width: 1, height: 24, background: '#2d2f45', flexShrink: 0 }} />

      {/* From date picker */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <label style={{ color: '#94a3b8', fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', whiteSpace: 'nowrap' }}>
          From date
        </label>
        <input
          type="date"
          value={fromDate ?? ''}
          onChange={e => setFromDate(e.target.value || null)}
          style={{
            background: '#0f1117',
            border: '1px solid #2d2f45',
            borderRadius: 4,
            color: '#e2e8f0',
            fontSize: 12,
            padding: '2px 6px',
            colorScheme: 'dark',
          }}
        />
        {fromDate && (
          <button
            onClick={() => setFromDate(null)}
            style={{
              background: 'none',
              border: 'none',
              color: '#64748b',
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
      <div style={{ width: 1, height: 24, background: '#2d2f45', flexShrink: 0 }} />

      {/* Metric checkboxes */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
        {METRICS.map(({ key, label }) => (
          <label
            key={key}
            style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', color: '#94a3b8', fontSize: 12, userSelect: 'none' }}
          >
            <input
              type="checkbox"
              checked={visibleMetrics.includes(key)}
              onChange={() => toggleMetric(key)}
              style={{ accentColor: '#6366f1', cursor: 'pointer' }}
            />
            {label}
          </label>
        ))}
      </div>
    </div>
  )
}
