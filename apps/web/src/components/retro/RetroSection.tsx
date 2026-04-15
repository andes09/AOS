// apps/web/src/components/retro/RetroSection.tsx

import { Card, CardBody } from '../ui/Card'

interface RetroSectionProps {
  title: string
  items: string[]
  variant: 'positive' | 'negative' | 'neutral'
}

const variantBorder: Record<RetroSectionProps['variant'], string> = {
  positive: 'var(--color-success)',
  negative: 'var(--color-danger)',
  neutral:  'var(--color-warning)',
}

const variantLabelColor: Record<RetroSectionProps['variant'], string> = {
  positive: 'var(--color-success)',
  negative: 'var(--color-danger)',
  neutral:  'var(--color-warning)',
}

export function RetroSection({ title, items, variant }: RetroSectionProps) {
  return (
    <Card style={{ borderLeft: `4px solid ${variantBorder[variant]}` }}>
      <CardBody style={{ padding: '14px 18px' }}>
        <div style={{
          color: variantLabelColor[variant],
          fontFamily: 'var(--font-sans)',
          fontSize: 'var(--text-xs)',
          fontWeight: 700,
          textTransform: 'uppercase',
          letterSpacing: '0.06em',
          marginBottom: 10,
        }}>
          {title}
        </div>
        {items.length === 0 ? (
          <div style={{ color: 'var(--color-text-muted)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)', fontStyle: 'italic' }}>
            {title} — nothing noted
          </div>
        ) : (
          <ul style={{ margin: 0, paddingLeft: '1.2rem', display: 'flex', flexDirection: 'column', gap: 6 }}>
            {items.map((item, i) => (
              <li key={i} style={{ color: 'var(--color-text-primary)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-base)', lineHeight: 1.5 }}>
                {item}
              </li>
            ))}
          </ul>
        )}
      </CardBody>
    </Card>
  )
}
