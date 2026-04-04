// apps/web/src/components/retro/ActionItemList.tsx

import type { ActionItem } from '../../types/retro'

const priorityChip: Record<ActionItem['priority'], { bg: string; color: string; label: string }> = {
  high:   { bg: '#7f1d1d', color: '#fca5a5', label: 'High' },
  medium: { bg: '#78350f', color: '#fcd34d', label: 'Medium' },
  low:    { bg: '#1e293b', color: '#94a3b8', label: 'Low' },
}

interface ActionItemListProps {
  items: ActionItem[]
}

export function ActionItemList({ items }: ActionItemListProps) {
  if (items.length === 0) {
    return (
      <div style={{
        background: '#1e2330',
        borderLeft: '4px solid #475569',
        borderRadius: 8,
        padding: '1rem 1.25rem',
      }}>
        <div style={{ color: '#94a3b8', fontSize: 13, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 10 }}>
          Action Items
        </div>
        <div style={{ color: '#475569', fontSize: 13, fontStyle: 'italic' }}>Action Items — nothing noted</div>
      </div>
    )
  }

  return (
    <div style={{
      background: '#1e2330',
      borderLeft: '4px solid #6366f1',
      borderRadius: 8,
      padding: '1rem 1.25rem',
    }}>
      <div style={{ color: '#a5b4fc', fontSize: 13, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 10 }}>
        Action Items
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {items.map((item, i) => {
          const chip = priorityChip[item.priority]
          return (
            <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
              <span style={{
                background: chip.bg,
                color: chip.color,
                fontSize: 11,
                fontWeight: 700,
                borderRadius: 4,
                padding: '2px 7px',
                flexShrink: 0,
                marginTop: 2,
              }}>
                {chip.label}
              </span>
              <span style={{ color: '#cbd5e1', fontSize: 14, lineHeight: 1.5, flex: 1 }}>
                {item.action}
              </span>
              {item.owner && (
                <span style={{ color: '#64748b', fontSize: 12, flexShrink: 0, marginTop: 2 }}>
                  {item.owner}
                </span>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
