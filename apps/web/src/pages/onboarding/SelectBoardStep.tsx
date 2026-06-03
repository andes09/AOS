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
      <h2 style={{ color: 'var(--color-text-primary)', fontSize: '1.25rem', fontWeight: 700, margin: '0 0 8px' }}>
        Select Board
      </h2>
      <p style={{ color: 'var(--color-text-secondary)', fontSize: 14, marginBottom: '1.5rem', lineHeight: 1.6 }}>
        Choose the Jira board Omada will use for sprint planning.
      </p>

      {isLoading && (
        <div style={{ color: 'var(--color-text-muted)', fontSize: 14, marginBottom: '1.5rem' }}>Loading boards...</div>
      )}
      {fetchError && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ color: 'var(--color-danger)', fontSize: 13, marginBottom: 8 }}>
            Failed to load boards. Check your Jira connection.
          </div>
          <button onClick={() => refetch()} style={ghostButtonStyle}>Retry</button>
        </div>
      )}
      {saveError && (
        <div style={{ color: 'var(--color-danger)', fontSize: 13, marginBottom: 12 }}>{saveError}</div>
      )}

      {boards && (
        <div style={{ marginBottom: '1.5rem' }}>
          {boards.length === 0 ? (
            <div style={{ color: 'var(--color-text-muted)', fontSize: 14 }}>
              No boards found. Make sure your Jira account has access to at least one project board.
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
                    border: `2px solid ${selectedBoardId === board.id ? 'var(--color-accent)' : 'var(--color-border)'}`,
                    background: selectedBoardId === board.id ? 'var(--color-accent-subtle)' : 'transparent',
                    cursor: 'pointer',
                    transition: 'border-color 0.15s, background 0.15s',
                  }}
                >
                  <div style={{ color: 'var(--color-text-primary)', fontSize: 14, fontWeight: 600 }}>{board.name}</div>
                  <div style={{ color: 'var(--color-text-muted)', fontSize: 12, marginTop: 2 }}>{board.project_key}</div>
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
          style={{
            flex: 1,
            background: !selectedBoardId || saving ? 'var(--color-bg-secondary)' : 'var(--color-accent)',
            color: !selectedBoardId || saving ? 'var(--color-text-muted)' : '#fff',
            border: 'none',
            borderRadius: 6,
            padding: '0.625rem 1.25rem',
            fontSize: 14,
            fontWeight: 600,
            cursor: !selectedBoardId || saving ? 'not-allowed' : 'pointer',
            transition: 'background 0.15s',
          }}
        >
          {saving ? 'Saving...' : 'Continue →'}
        </button>
      </div>
    </div>
  )
}

const ghostButtonStyle: React.CSSProperties = {
  background: 'transparent',
  color: 'var(--color-text-secondary)',
  border: '1px solid var(--color-border)',
  borderRadius: 6,
  padding: '0.625rem 1rem',
  fontSize: 14,
  cursor: 'pointer',
}
