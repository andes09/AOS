import { Card, CardBody } from '../ui/Card'

export interface VelocityCardProps {
  developer: string
  meanVelocity: number
  committed: number
  capacity: number
  sprintCount: number
}

function utilColour(ratio: number): string {
  if (ratio < 0.8) return 'var(--color-success)'
  if (ratio < 1.0) return 'var(--color-warning)'
  return 'var(--color-danger)'
}

export function VelocityCard({ developer, meanVelocity, committed, capacity, sprintCount }: VelocityCardProps) {
  const isInsufficient = sprintCount < 3
  const ratio = capacity > 0 ? committed / capacity : 0
  const barColour = utilColour(ratio)

  return (
    <Card style={{ minWidth: 150, flex: 1 }}>
      <CardBody>
        <div style={{
          color: 'var(--color-text-secondary)',
          fontSize: 'var(--text-xs)',
          fontFamily: 'var(--font-sans)',
          fontWeight: 600,
          textTransform: 'uppercase',
          letterSpacing: '0.06em',
          marginBottom: 6,
        }}>
          {developer}
        </div>

        {isInsufficient ? (
          <div>
            <div style={{ color: 'var(--color-text-muted)', fontSize: 'var(--text-sm)', marginBottom: 4 }}>
              Insufficient data
            </div>
            <div style={{ color: 'var(--color-text-muted)', fontSize: 'var(--text-xs)' }}>
              {3 - sprintCount} more sprint{3 - sprintCount !== 1 ? 's' : ''} needed
            </div>
          </div>
        ) : (
          <>
            <div style={{ color: 'var(--color-text-primary)', fontSize: 22, fontWeight: 700, marginBottom: 4 }}>
              {meanVelocity} pts
            </div>
            <div style={{ color: 'var(--color-text-secondary)', fontSize: 'var(--text-xs)', marginBottom: 6 }}>
              {committed}/{capacity} pts committed
            </div>
            <div style={{ background: 'var(--color-border)', height: 6, borderRadius: 3 }}>
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
      </CardBody>
    </Card>
  )
}
