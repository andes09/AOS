// apps/web/src/pages/RetrospectivePage.tsx

import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { useAuth } from '@clerk/clerk-react'
import { useApi, ApiError } from '../lib/api'
import { RetroSection } from '../components/retro/RetroSection'
import { ActionItemList } from '../components/retro/ActionItemList'
import { PatternFeed } from '../components/retro/PatternFeed'
import type { RetroResponse } from '../types/retro'

const TEAM_ID = 'default'

interface SprintOption {
  id: string
  name: string
  endDate: string | null
}

interface CompletedSprintsResponse {
  sprints: SprintOption[]
}

function LoadingSkeleton() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {[1, 2, 3].map(i => (
        <div key={i} style={{
          background: '#1e2330',
          borderRadius: 8,
          height: 100,
          animation: 'pulse 1.5s ease-in-out infinite',
          opacity: 0.6,
        }} />
      ))}
    </div>
  )
}

export function RetrospectivePage() {
  const { get, post } = useApi()
  const { isLoaded, isSignedIn } = useAuth()
  const [searchParams] = useSearchParams()
  const queryClient = useQueryClient()

  const paramSprintId = searchParams.get('sprintId')
  const [selectedSprintId, setSelectedSprintId] = useState<string>(paramSprintId ?? '')

  // Load completed sprints for selector
  const { data: sprintsData } = useQuery<CompletedSprintsResponse>({
    queryKey: ['completed-sprints'],
    queryFn: () => get<CompletedSprintsResponse>('/api/sprints/completed'),
    enabled: isLoaded && isSignedIn,
  })

  // Pre-select sprint from query param once list is loaded
  useEffect(() => {
    if (paramSprintId && !selectedSprintId) {
      setSelectedSprintId(paramSprintId)
    }
  }, [paramSprintId])

  // Load existing retro for selected sprint
  const {
    data: retro,
    isLoading: retroLoading,
    error: retroError,
  } = useQuery<RetroResponse, ApiError>({
    queryKey: ['retro', selectedSprintId],
    queryFn: () => get<RetroResponse>(`/api/retro/${selectedSprintId}`),
    enabled: !!selectedSprintId && isLoaded && isSignedIn,
    retry: false,
  })

  const retroExists = !!retro && !(retroError instanceof ApiError && retroError.status === 404)
  const retroNotFound = retroError instanceof ApiError && retroError.status === 404
  const retro403 = retroError instanceof ApiError && retroError.status === 403

  // Generate retro mutation
  const {
    mutate: generateRetro,
    isPending: generating,
    error: genError,
  } = useMutation<RetroResponse, ApiError>({
    mutationFn: () =>
      post<RetroResponse>(`/api/retro/generate/${selectedSprintId}?team_id=${TEAM_ID}`, {}),
    onSuccess: (data) => {
      queryClient.setQueryData(['retro', selectedSprintId], data)
    },
  })
  const gen403 = genError instanceof ApiError && genError.status === 403

  return (
    <div style={{
      background: '#0f1117',
      minHeight: '100%',
      padding: '1.5rem',
      fontFamily: 'system-ui, sans-serif',
    }}>
      {/* Header */}
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ color: '#e2e8f0', fontSize: 22, fontWeight: 800, margin: 0, letterSpacing: '-0.01em' }}>
          Retrospective
        </h1>
        <div style={{ color: '#64748b', fontSize: 13, marginTop: 4 }}>
          AI-generated sprint retrospectives with action items and pattern tracking
        </div>
      </div>

      {/* Sprint selector + Generate button */}
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 24 }}>
        <select
          value={selectedSprintId}
          onChange={e => setSelectedSprintId(e.target.value)}
          style={{
            background: '#1e2330',
            border: '1px solid #334155',
            borderRadius: 7,
            color: '#e2e8f0',
            fontSize: 14,
            padding: '8px 12px',
            minWidth: 240,
            cursor: 'pointer',
          }}
        >
          <option value="">Select a completed sprint…</option>
          {(sprintsData?.sprints ?? []).map(s => (
            <option key={s.id} value={s.id}>{s.name}</option>
          ))}
        </select>

        <button
          onClick={() => generateRetro()}
          disabled={!selectedSprintId || retroExists || generating || retroLoading}
          style={{
            background: (!selectedSprintId || retroExists || generating || retroLoading) ? '#1e2330' : '#6366f1',
            border: 'none',
            borderRadius: 7,
            color: (!selectedSprintId || retroExists || generating || retroLoading) ? '#475569' : '#fff',
            fontSize: 14,
            fontWeight: 600,
            padding: '8px 20px',
            cursor: (!selectedSprintId || retroExists || generating || retroLoading) ? 'default' : 'pointer',
            transition: 'background 0.15s',
          }}
        >
          {generating ? 'Generating…' : 'Generate Retro'}
        </button>
      </div>

      {/* Access denied */}
      {(retro403 || gen403) && (
        <div style={{
          background: '#1e2130',
          border: '1px solid #ef444433',
          borderRadius: 10,
          padding: '2rem',
          textAlign: 'center',
          color: '#ef4444',
          fontSize: 15,
        }}>
          Access denied. Lead role required.
        </div>
      )}

      {/* Error banner */}
      {genError && !gen403 && (
        <div style={{
          background: '#7f1d1d',
          border: '1px solid #ef4444',
          borderRadius: 8,
          color: '#fca5a5',
          fontSize: 13,
          padding: '10px 14px',
          marginBottom: 16,
        }}>
          {genError.message}
        </div>
      )}

      {/* Loading skeleton */}
      {(generating || (retroLoading && selectedSprintId)) && <LoadingSkeleton />}

      {/* No sprint selected */}
      {!selectedSprintId && (
        <div style={{ color: '#475569', fontSize: 14, marginTop: 40, textAlign: 'center' }}>
          Select a completed sprint to view or generate its retrospective.
        </div>
      )}

      {/* Retro not yet generated */}
      {selectedSprintId && retroNotFound && !generating && (
        <div style={{ color: '#64748b', fontSize: 14, marginTop: 40, textAlign: 'center' }}>
          No retrospective found for this sprint. Click "Generate Retro" to create one.
        </div>
      )}

      {/* Retro content */}
      {retro && !generating && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {/* Velocity summary chip */}
          <div style={{
            background: '#1e2330',
            borderRadius: 8,
            padding: '10px 16px',
            display: 'flex',
            gap: 24,
          }}>
            <div>
              <span style={{ color: '#64748b', fontSize: 12 }}>Sprint </span>
              <span style={{ color: '#e2e8f0', fontSize: 13, fontWeight: 600 }}>{retro.sprintName}</span>
            </div>
            <div>
              <span style={{ color: '#64748b', fontSize: 12 }}>Committed </span>
              <span style={{ color: '#e2e8f0', fontSize: 13, fontWeight: 600 }}>{retro.velocitySummary.committed} pts</span>
            </div>
            <div>
              <span style={{ color: '#64748b', fontSize: 12 }}>Delivered </span>
              <span style={{ color: '#e2e8f0', fontSize: 13, fontWeight: 600 }}>{retro.velocitySummary.delivered} pts</span>
            </div>
            <div>
              <span style={{ color: '#64748b', fontSize: 12 }}>Completion </span>
              <span style={{
                color: retro.velocitySummary.completionRate >= 0.8 ? '#4ade80' : retro.velocitySummary.completionRate >= 0.6 ? '#fbbf24' : '#f87171',
                fontSize: 13,
                fontWeight: 600,
              }}>
                {Math.round(retro.velocitySummary.completionRate * 100)}%
              </span>
            </div>
          </div>

          <RetroSection title="Went Well" items={retro.wentWell} variant="positive" />
          <RetroSection title="Went Poorly" items={retro.wentPoorly} variant="negative" />
          <ActionItemList items={retro.actionItems} />
          <PatternFeed patterns={retro.patterns} />
        </div>
      )}
    </div>
  )
}
