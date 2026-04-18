// apps/web/src/pages/RetrospectivePage.tsx

import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { useAuth } from '@clerk/clerk-react'
import { useApi, ApiError } from '../lib/api'
import { RetroSection } from '../components/retro/RetroSection'
import { ActionItemList } from '../components/retro/ActionItemList'
import { PatternFeed } from '../components/retro/PatternFeed'
import { Select } from '../components/ui/Select'
import { Button } from '../components/ui/Button'
import { Alert } from '../components/ui/Alert'
import { Card, CardBody } from '../components/ui/Card'
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
          background: 'var(--color-bg-elevated)',
          border: '1px solid var(--color-border)',
          borderRadius: 'var(--radius-lg)',
          height: 100,
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

  const { data: sprintsData } = useQuery<CompletedSprintsResponse>({
    queryKey: ['completed-sprints'],
    queryFn: () => get<CompletedSprintsResponse>('/api/sprints/completed'),
    enabled: isLoaded && isSignedIn,
  })

  useEffect(() => {
    if (paramSprintId && !selectedSprintId) {
      setSelectedSprintId(paramSprintId)
    }
  }, [paramSprintId])

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

  const completionColor = (rate: number) => {
    if (rate >= 0.8) return 'var(--color-success)'
    if (rate >= 0.6) return 'var(--color-warning)'
    return 'var(--color-danger)'
  }

  return (
    <div style={{ fontFamily: 'var(--font-sans)', minHeight: '100%' }}>
      {/* Header */}
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ color: 'var(--color-text-primary)', fontSize: 'var(--text-xl)', fontWeight: 700, margin: 0 }}>
          Retro Prep
        </h1>
        <div style={{ color: 'var(--color-text-muted)', fontSize: 'var(--text-sm)', marginTop: 4 }}>
          Prepare your team for a better retro conversation
        </div>
      </div>

      {/* Sprint selector + Generate button */}
      <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end', marginBottom: 24 }}>
        <Select
          label="Sprint"
          value={selectedSprintId}
          onChange={e => setSelectedSprintId(e.target.value)}
          containerStyle={{ minWidth: 240 }}
        >
          <option value="">Select a completed sprint…</option>
          {(sprintsData?.sprints ?? []).map(s => (
            <option key={s.id} value={s.id}>{s.name}</option>
          ))}
        </Select>

        <Button
          variant="primary"
          onClick={() => generateRetro()}
          disabled={!selectedSprintId || retroExists || generating || retroLoading}
        >
          {generating ? 'Generating…' : 'Generate Retro'}
        </Button>
      </div>

      {/* Access denied */}
      {(retro403 || gen403) && (
        <Alert variant="danger">Access denied. Lead role required.</Alert>
      )}

      {/* Error banner */}
      {genError && !gen403 && (
        <Alert variant="danger" style={{ marginBottom: 16 }}>{genError.message}</Alert>
      )}

      {/* Loading skeleton */}
      {(generating || (retroLoading && selectedSprintId)) && <LoadingSkeleton />}

      {/* No sprint selected */}
      {!selectedSprintId && (
        <div style={{ color: 'var(--color-text-muted)', fontSize: 'var(--text-base)', marginTop: 40, textAlign: 'center' }}>
          Select a completed sprint to view or generate its retrospective.
        </div>
      )}

      {/* Retro not yet generated */}
      {selectedSprintId && retroNotFound && !generating && (
        <div style={{ color: 'var(--color-text-muted)', fontSize: 'var(--text-base)', marginTop: 40, textAlign: 'center' }}>
          No retrospective found for this sprint. Click "Generate Retro" to create one.
        </div>
      )}

      {/* Retro content */}
      {retro && !generating && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {/* Velocity summary */}
          <Card>
            <CardBody style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
              <div>
                <span style={{ color: 'var(--color-text-muted)', fontSize: 'var(--text-xs)' }}>Sprint </span>
                <span style={{ color: 'var(--color-text-primary)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)', fontWeight: 600 }}>{retro.sprintName}</span>
              </div>
              <div>
                <span style={{ color: 'var(--color-text-muted)', fontSize: 'var(--text-xs)' }}>Committed </span>
                <span style={{ color: 'var(--color-text-primary)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)', fontWeight: 600 }}>{retro.velocitySummary.committed} pts</span>
              </div>
              <div>
                <span style={{ color: 'var(--color-text-muted)', fontSize: 'var(--text-xs)' }}>Delivered </span>
                <span style={{ color: 'var(--color-text-primary)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)', fontWeight: 600 }}>{retro.velocitySummary.delivered} pts</span>
              </div>
              <div>
                <span style={{ color: 'var(--color-text-muted)', fontSize: 'var(--text-xs)' }}>Completion </span>
                <span style={{
                  color: completionColor(retro.velocitySummary.completionRate),
                  fontFamily: 'var(--font-sans)',
                  fontSize: 'var(--text-sm)',
                  fontWeight: 600,
                }}>
                  {Math.round(retro.velocitySummary.completionRate * 100)}%
                </span>
              </div>
            </CardBody>
          </Card>

          <RetroSection title="Went Well" items={retro.wentWell} variant="positive" />
          <RetroSection title="Went Poorly" items={retro.wentPoorly} variant="negative" />
          <ActionItemList items={retro.actionItems} />
          <PatternFeed patterns={retro.patterns} />
        </div>
      )}
    </div>
  )
}
