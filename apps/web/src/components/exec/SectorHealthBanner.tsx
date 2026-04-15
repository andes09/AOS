import { Alert } from '../ui/Alert'
import { Badge } from '../ui/Badge'
import type { AlertVariant } from '../ui/Alert'
import type { BadgeVariant } from '../ui/Badge'

interface Props {
  sectorHealthScore: number
  teamCount: number
}

function getStatus(score: number): { variant: AlertVariant; badgeVariant: BadgeVariant; label: string; scoreColor: string } {
  if (score >= 70) return { variant: 'success', badgeVariant: 'success', label: 'Healthy', scoreColor: 'var(--color-success)' }
  if (score >= 40) return { variant: 'warning', badgeVariant: 'warning', label: 'At Risk', scoreColor: 'var(--color-warning)' }
  return { variant: 'danger', badgeVariant: 'danger', label: 'Critical', scoreColor: 'var(--color-danger)' }
}

export function SectorHealthBanner({ sectorHealthScore, teamCount }: Props) {
  const { variant, badgeVariant, label, scoreColor } = getStatus(sectorHealthScore)

  return (
    <Alert
      variant={variant}
      style={{ marginBottom: 24, padding: '16px 20px' }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 24, flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
          <span style={{ fontSize: 'var(--text-2xl)', fontWeight: 800, color: scoreColor, lineHeight: 1, fontFamily: 'var(--font-sans)' }}>
            {sectorHealthScore}
          </span>
          <span style={{ color: 'var(--color-text-secondary)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-xs)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            Sector Health
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <Badge variant={badgeVariant}>{label}</Badge>
          <span style={{ color: 'var(--color-text-secondary)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)' }}>
            {teamCount} team{teamCount !== 1 ? 's' : ''} tracked
          </span>
        </div>
      </div>
    </Alert>
  )
}
