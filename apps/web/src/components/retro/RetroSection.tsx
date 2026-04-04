// apps/web/src/components/retro/RetroSection.tsx

interface RetroSectionProps {
  title: string
  items: string[]
  variant: 'positive' | 'negative' | 'neutral'
}

const variantStyles: Record<RetroSectionProps['variant'], { borderColor: string; labelColor: string }> = {
  positive: { borderColor: '#22c55e', labelColor: '#4ade80' },
  negative: { borderColor: '#ef4444', labelColor: '#f87171' },
  neutral:  { borderColor: '#f59e0b', labelColor: '#fbbf24' },
}

export function RetroSection({ title, items, variant }: RetroSectionProps) {
  const { borderColor, labelColor } = variantStyles[variant]

  return (
    <div style={{
      background: '#1e2330',
      borderLeft: `4px solid ${borderColor}`,
      borderRadius: 8,
      padding: '1rem 1.25rem',
    }}>
      <div style={{ color: labelColor, fontSize: 13, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 10 }}>
        {title}
      </div>
      {items.length === 0 ? (
        <div style={{ color: '#475569', fontSize: 13, fontStyle: 'italic' }}>
          {title} — nothing noted
        </div>
      ) : (
        <ul style={{ margin: 0, paddingLeft: '1.2rem', display: 'flex', flexDirection: 'column', gap: 6 }}>
          {items.map((item, i) => (
            <li key={i} style={{ color: '#cbd5e1', fontSize: 14, lineHeight: 1.5 }}>
              {item}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
