export interface VelocityCardProps {
  developer: string
  meanVelocity: number
  committed: number
  capacity: number
  sprintCount: number
}

function utilColour(ratio: number): string {
  if (ratio < 0.8) return '#4ade80'
  if (ratio < 1.0) return '#fbbf24'
  return '#ef4444'
}

export function VelocityCard({ developer, meanVelocity, committed, capacity, sprintCount }: VelocityCardProps) {
  const isInsufficient = sprintCount < 3
  const ratio = capacity > 0 ? committed / capacity : 0
  const barColour = utilColour(ratio)

  return (
    <div style={{
      background: '#1e2030',
      borderRadius: 8,
      padding: '0.875rem 1rem',
      minWidth: 150,
      flex: 1,
    }}>
      <div style={{
        color: '#a5b4fc',
        fontSize: 11,
        fontWeight: 700,
        textTransform: 'uppercase',
        letterSpacing: '0.06em',
        marginBottom: 6,
      }}>
        {developer}
      </div>

      {isInsufficient ? (
        <div>
          <div style={{ color: '#64748b', fontSize: 13, marginBottom: 4 }}>Insufficient data</div>
          <div style={{ color: '#94a3b8', fontSize: 11 }}>
            {3 - sprintCount} more sprint{3 - sprintCount !== 1 ? 's' : ''} needed
          </div>
        </div>
      ) : (
        <>
          <div style={{ color: '#e2e8f0', fontSize: 22, fontWeight: 700, marginBottom: 4 }}>
            {meanVelocity} pts
          </div>
          <div style={{ color: '#94a3b8', fontSize: 11, marginBottom: 6 }}>
            {committed}/{capacity} pts committed
          </div>
          <div style={{ background: '#2d2f45', height: 6, borderRadius: 3 }}>
            <div style={{
              width: `${Math.min(ratio * 100, 100)}%`,
              height: 6,
              borderRadius: 3,
              background: barColour,
              transition: 'width 0.4s ease',
            }} />
          </div>
        </>
      )}
    </div>
  )
}
