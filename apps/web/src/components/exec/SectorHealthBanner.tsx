interface Props {
  sectorHealthScore: number
  teamCount: number
}

function getStatusLabel(score: number): { label: string; color: string } {
  if (score >= 70) return { label: 'Healthy', color: '#22c55e' }
  if (score >= 40) return { label: 'At Risk', color: '#f59e0b' }
  return { label: 'Critical', color: '#ef4444' }
}

export function SectorHealthBanner({ sectorHealthScore, teamCount }: Props) {
  const { label, color } = getStatusLabel(sectorHealthScore)

  return (
    <div style={{
      background: '#1e2130',
      border: `1px solid ${color}33`,
      borderRadius: 12,
      padding: '1.5rem 2rem',
      display: 'flex',
      alignItems: 'center',
      gap: '2rem',
      marginBottom: '1.5rem',
    }}>
      <div style={{ textAlign: 'center' }}>
        <div style={{ fontSize: 56, fontWeight: 800, color, lineHeight: 1 }}>
          {sectorHealthScore}
        </div>
        <div style={{ color: '#94a3b8', fontSize: 12, marginTop: 4 }}>Sector Health</div>
      </div>

      <div style={{ width: 1, height: 64, background: '#334155' }} />

      <div>
        <div style={{
          display: 'inline-block',
          background: `${color}22`,
          color,
          border: `1px solid ${color}66`,
          borderRadius: 20,
          padding: '4px 14px',
          fontSize: 14,
          fontWeight: 700,
          marginBottom: 8,
        }}>
          {label}
        </div>
        <div style={{ color: '#94a3b8', fontSize: 13 }}>
          {teamCount} team{teamCount !== 1 ? 's' : ''} tracked
        </div>
      </div>
    </div>
  )
}
