// apps/web/src/pages/onboarding/SelectBoardStep.tsx

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useApi } from '../../lib/api'
import type { JiraBoard } from '../../types/sprint'

interface SelectBoardStepProps {
  connectionId: string
  onNext: () => void
  onBack: () => void
}

export function SelectBoardStep({ connectionId, onNext, onBack }: SelectBoardStepProps) {
  const [selectedBoardId, setSelectedBoardId] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const { get, post } = useApi()

  const { data: boards, isLoading, error: fetchError, refetch } = useQuery({
    queryKey: ['jira-boards', connectionId],
    queryFn: () => get<JiraBoard[]>(`/api/integrations/jira/boards?connection_id=${connectionId}`),
    enabled: !!connectionId,
  })

  async function handleSave() {
    if (!selectedBoardId || !boards) return
    const board = boards.find(b => b.id === selectedBoardId)
    if (!board) return
    setSaving(true)
    setSaveError(null)
    try {
      await post('/api/integrations/jira/board-selection', {
        connection_id: connectionId,
        board_id: board.id,
        project_key: board.project_key,
      })
      onNext()
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Failed to save board selection')
      setSaving(false)
    }
  }

  return (
    <div>
      <h2 style={{ color: '#e2e8f0', fontSize: '1.25rem', fontWeight: 700, margin: '0 0 8px' }}>
        Select Board
      </h2>
      <p style={{ color: '#94a3b8', fontSize: 14, marginBottom: '1.5rem', lineHeight: 1.6 }}>
        Choose the Jira board Sprint Brain will use for sprint planning.
      </p>

      {isLoading && (
        <div style={{ color: '#64748b', fontSize: 14, marginBottom: '1.5rem' }}>Loading boards...</div>
      )}
      {fetchError && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ color: '#ef4444', fontSize: 13, marginBottom: 8 }}>
            Failed to load boards. Check your Jira connection.
          </div>
          <button onClick={() => refetch()} style={ghostButtonStyle}>Retry</button>
        </div>
      )}
      {saveError && (
        <div style={{ color: '#ef4444', fontSize: 13, marginBottom: 12 }}>{saveError}</div>
      )}

      {boards && (
        <div style={{ marginBottom: '1.5rem' }}>
          {boards.length === 0 ? (
            <div style={{ color: '#64748b', fontSize: 14 }}>
              No scrum boards found. Make sure your Jira account has access to at least one scrum project.
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {boards.map(board => (
                <div
                  key={board.id}
                  onClick={() => setSelectedBoardId(board.id)}
                  style={{
                    padding: '0.75rem 1rem',
                    borderRadius: 6,
                    border: `2px solid ${selectedBoardId === board.id ? '#6366f1' : '#2d2f45'}`,
                    background: selectedBoardId === board.id ? '#2d2f45' : 'transparent',
                    cursor: 'pointer',
                    transition: 'border-color 0.15s, background 0.15s',
                  }}
                >
                  <div style={{ color: '#e2e8f0', fontSize: 14, fontWeight: 600 }}>{board.name}</div>
                  <div style={{ color: '#64748b', fontSize: 12, marginTop: 2 }}>{board.project_key}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      <div style={{ display: 'flex', gap: 8 }}>
        <button onClick={onBack} style={ghostButtonStyle}>← Back</button>
        <button
          onClick={handleSave}
          disabled={!selectedBoardId || saving}
          style={primaryButtonStyle(!selectedBoardId || saving ? '#374151' : '#6366f1')}
        >
          {saving ? 'Saving...' : 'Continue →'}
        </button>
      </div>
    </div>
  )
}

const ghostButtonStyle: React.CSSProperties = {
  background: 'transparent',
  color: '#94a3b8',
  border: '1px solid #2d2f45',
  borderRadius: 6,
  padding: '0.625rem 1rem',
  fontSize: 14,
  cursor: 'pointer',
}

function primaryButtonStyle(bg: string): React.CSSProperties {
  return {
    flex: 1,
    background: bg,
    color: '#fff',
    border: 'none',
    borderRadius: 6,
    padding: '0.625rem 1.25rem',
    fontSize: 14,
    fontWeight: 600,
    cursor: 'pointer',
  }
}
