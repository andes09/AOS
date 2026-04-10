import { useState } from 'react'
import type { DeveloperCapacityItem } from '../../types/capacity'

interface MeetingLoadWarningProps {
  developers: DeveloperCapacityItem[]
  onAdjustCapacity: () => void
}

export function MeetingLoadWarning({ developers, onAdjustCapacity }: MeetingLoadWarningProps) {
  const [expanded, setExpanded] = useState(false)
  const highLoad = developers.filter(d => d.isHighMeetingLoad)
  if (highLoad.length === 0) return null

  return (
    <div style={{
      background: '#78350f',
      border: '1px solid #d97706',
      borderRadius: 8,
      padding: '0.75rem 1rem',
      marginBottom: 12,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
        <button
          onClick={() => setExpanded(e => !e)}
          style={{ background: 'none', border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 8, padding: 0, flex: 1, textAlign: 'left' }}
        >
          <span style={{ color: '#fbbf24', fontSize: 16 }}>⚠</span>
          <span style={{ color: '#fde68a', fontSize: 13, fontWeight: 600 }}>
            {highLoad.length} developer{highLoad.length !== 1 ? 's' : ''} have reduced capacity this sprint
          </span>
          <span style={{ color: '#d97706', fontSize: 11, marginLeft: 4 }}>{expanded ? '▲' : '▼'}</span>
        </button>
        <button
          onClick={onAdjustCapacity}
          style={{
            background: 'transparent',
            color: '#fbbf24',
            border: '1px solid #d97706',
            borderRadius: 6,
            padding: '4px 12px',
            fontSize: 12,
            fontWeight: 600,
            cursor: 'pointer',
            whiteSpace: 'nowrap',
          }}
        >
          Adjust Capacity
        </button>
      </div>
      {expanded && (
        <ul style={{ margin: '8px 0 0', paddingLeft: 24, display: 'flex', flexDirection: 'column', gap: 4 }}>
          {highLoad.map(d => (
            <li key={d.developerId} style={{ color: '#fde68a', fontSize: 13 }}>
              {d.warningMessage}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
