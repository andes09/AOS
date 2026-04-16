import { useState } from 'react'
import { Alert } from '../ui/Alert'
import { Button } from '../ui/Button'
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
    <Alert variant="warning" style={{ marginBottom: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
        <button
          onClick={() => setExpanded(e => !e)}
          style={{ background: 'none', border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 8, padding: 0, flex: 1, textAlign: 'left' }}
        >
          <span style={{ color: 'var(--color-warning)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)', fontWeight: 600 }}>
            {highLoad.length} developer{highLoad.length !== 1 ? 's' : ''} have reduced capacity this sprint
          </span>
          <span style={{ color: 'var(--color-warning)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-xs)', marginLeft: 4 }}>
            {expanded ? '▲' : '▼'}
          </span>
        </button>
        <Button size="sm" variant="secondary" onClick={onAdjustCapacity}>
          Adjust Capacity
        </Button>
      </div>
      {expanded && (
        <ul style={{ margin: '8px 0 0', paddingLeft: 20, display: 'flex', flexDirection: 'column', gap: 4 }}>
          {highLoad.map(d => (
            <li key={d.developerId} style={{ color: 'var(--color-text-primary)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)' }}>
              {d.warningMessage}
            </li>
          ))}
        </ul>
      )}
    </Alert>
  )
}
