// apps/web/src/pages/SprintPlannerPage.tsx

import { useState, useEffect } from 'react'
import { useMutation } from '@tanstack/react-query'
import { useApi, ApiError } from '../lib/api'
import { VelocityCard } from '../components/sprint/VelocityCard'
import { ConfidenceGauge } from '../components/sprint/ConfidenceGauge'
import { TicketList } from '../components/sprint/TicketList'
import { PlanReasoningPanel } from '../components/sprint/PlanReasoningPanel'
import type { SprintPlanResponse, WhatIfResponse, Ticket, PushToJiraResponse } from '../types/sprint'

const SESSION_KEY = 'sprint_plan_cache'

function deriveCommitted(assignments: SprintPlanResponse['assignments']): Map<string, number> {
  const map = new Map<string, number>()
  for (const a of assignments) {
    map.set(a.developer_id, (map.get(a.developer_id) ?? 0) + a.story_points)
  }
  return map
}

const DEFAULT_CAPACITY = 40

export function SprintPlannerPage() {
  const { post } = useApi()

  const [plan, setPlan] = useState<SprintPlanResponse | null>(() => {
    try {
      const cached = sessionStorage.getItem(SESSION_KEY)
      return cached ? JSON.parse(cached) : null
    } catch {
      return null
    }
  })
  const [confidence, setConfidence] = useState<number>(() => {
    try {
      const cached = sessionStorage.getItem(SESSION_KEY)
      return cached ? JSON.parse(cached).confidence_score ?? 0 : 0
    } catch {
      return 0
    }
  })
  const [pushResult, setPushResult] = useState<PushToJiraResponse | null>(null)
  const [pushError, setPushError] = useState<string | null>(null)
  const [droppedIds, setDroppedIds] = useState<Set<string>>(new Set())
  const [warnings, setWarnings] = useState<string[]>(() => {
    try {
      const cached = sessionStorage.getItem(SESSION_KEY)
      return cached ? JSON.parse(cached).warnings ?? [] : []
    } catch {
      return []
    }
  })

  useEffect(() => {
    if (plan) {
      try { sessionStorage.setItem(SESSION_KEY, JSON.stringify(plan)) } catch { /* quota */ }
    }
  }, [plan])

  const generatePlan = useMutation({
    mutationFn: () =>
      post<SprintPlanResponse>('/api/sprint-brain/plan', {
        team_id: 'default',
        sprint_length_days: 14,
        pto_overrides: {},
      }),
    onSuccess: data => {
      setPlan(data)
      setConfidence(data.confidence_score)
      setWarnings(data.warnings)
      setDroppedIds(new Set())
    },
  })

  const pushMutation = useMutation({
    mutationFn: () => post<PushToJiraResponse>('/api/sprint-brain/push-to-jira', {}),
    onSuccess: (data) => { setPushResult(data); setPushError(null) },
    onError: (err: ApiError) => {
      if (err.status === 409) setPushError('Active sprint in progress — end it in Jira first.')
      else if (err.status === 402) setPushError('No Jira connection. Connect in Settings.')
      else setPushError('Push failed. Try again.')
    },
  })

  const whatIf = useMutation({
    mutationFn: (dropped: string[]) =>
      post<WhatIfResponse>('/api/sprint-brain/what-if', {
        team_id: 'default',
        sprint_length_days: 14,
        dropped_ticket_ids: dropped,
      }),
    onSuccess: data => {
      setConfidence(data.confidence_score)
    },
  })

  function handleDropTicket(ticketId: string) {
    const next = new Set(droppedIds)
    next.add(ticketId)
    setDroppedIds(next)
    whatIf.mutate(Array.from(next))
  }

  function handleRestoreTicket(ticketId: string) {
    const next = new Set(droppedIds)
    next.delete(ticketId)
    setDroppedIds(next)
    whatIf.mutate(Array.from(next))
  }

  const committed = plan ? deriveCommitted(plan.assignments) : new Map<string, number>()
  const developers = Array.from(committed.keys())
  const devNameMap = plan?.developers ?? {}

  const tickets: Ticket[] = (plan?.assignments ?? []).map(a => ({
    ticket_id: a.ticket_id,
    title: a.title || a.ticket_id,
    developer_id: a.developer_id,
    developer_name: a.developer_name || devNameMap[a.developer_id.toLowerCase()] || a.developer_id,
    story_points: a.story_points,
    confidence: a.confidence,
  }))

  return (
    <div style={{ background: '#0f1117', minHeight: '100%', padding: '1.5rem', fontFamily: 'system-ui, sans-serif' }}>

      {/* Top row: velocity cards + gauge + generate button */}
      <div style={{ display: 'flex', gap: 12, alignItems: 'stretch', marginBottom: 16, flexWrap: 'wrap' }}>

        {developers.length === 0 && !generatePlan.isPending && (
          <div style={{
            flex: 1,
            background: '#1e2030',
            borderRadius: 8,
            padding: '0.875rem 1rem',
            color: '#64748b',
            fontSize: 13,
            display: 'flex',
            alignItems: 'center',
          }}>
            Velocity cards will appear here after generating a plan.
          </div>
        )}

        {developers.map(dev => (
          <VelocityCard
            key={dev}
            developer={devNameMap[dev] || dev}
            meanVelocity={committed.get(dev) ?? 0}
            committed={committed.get(dev) ?? 0}
            capacity={DEFAULT_CAPACITY}
            sprintCount={3}
          />
        ))}

        {plan && (
          <div style={{ background: '#1e2030', borderRadius: 8, padding: '0.875rem 1rem', display: 'flex', alignItems: 'center' }}>
            <ConfidenceGauge score={confidence} sampleSize={plan.assignments.length} />
          </div>
        )}

        <button
          onClick={() => generatePlan.mutate()}
          disabled={generatePlan.isPending}
          style={{
            background: generatePlan.isPending ? '#374151' : '#6366f1',
            color: '#fff',
            border: 'none',
            borderRadius: 8,
            padding: '0.875rem 1.5rem',
            fontSize: 14,
            fontWeight: 700,
            cursor: generatePlan.isPending ? 'default' : 'pointer',
            whiteSpace: 'nowrap',
            alignSelf: 'center',
          }}
        >
          {generatePlan.isPending ? 'Generating...' : '✦ Generate Plan'}
        </button>

        {plan && (
          <button
            onClick={() => pushMutation.mutate()}
            disabled={pushMutation.isPending}
            style={{
              background: pushMutation.isPending ? '#374151' : '#059669',
              color: '#fff',
              border: 'none',
              borderRadius: 8,
              padding: '0.875rem 1.5rem',
              fontSize: 14,
              fontWeight: 700,
              cursor: pushMutation.isPending ? 'default' : 'pointer',
              whiteSpace: 'nowrap',
              alignSelf: 'center',
            }}
          >
            {pushMutation.isPending ? 'Pushing...' : 'Push to Jira'}
          </button>
        )}
      </div>

      {generatePlan.isError && (
        <div style={{ color: '#ef4444', fontSize: 13, marginBottom: 12 }}>
          {generatePlan.error instanceof Error
            ? generatePlan.error.message
            : 'Failed to generate plan. Check your Anthropic key and Jira connection.'}
        </div>
      )}

      {warnings.length > 0 && (
        <div style={{ background: '#1e2030', borderRadius: 8, padding: '0.75rem 1rem', marginBottom: 16, display: 'flex', flexDirection: 'column', gap: 4 }}>
          {warnings.map((w, i) => (
            <div key={i} style={{ color: '#fbbf24', fontSize: 13, display: 'flex', gap: 8 }}>
              <span>⚠</span><span>{w}</span>
            </div>
          ))}
        </div>
      )}

      {pushError && (
        <div style={{ background: '#78350f', border: '1px solid #d97706', borderRadius: 8, padding: '0.75rem 1rem', marginBottom: 16, color: '#fbbf24', fontSize: 13 }}>
          {pushError}
        </div>
      )}

      {pushResult && (
        <div style={{ background: '#064e3b', border: '1px solid #059669', borderRadius: 8, padding: '0.75rem 1rem', marginBottom: 16, fontSize: 13 }}>
          <div style={{ color: '#6ee7b7' }}>
            Sprint pushed! {pushResult.pushedTickets} tickets assigned.{' '}
            <a href={pushResult.sprintUrl} target="_blank" rel="noreferrer" style={{ color: '#34d399', textDecoration: 'underline' }}>
              View in Jira
            </a>
          </div>
          {pushResult.unassignedWarnings.length > 0 && (
            <ul style={{ margin: '8px 0 0', paddingLeft: 20, color: '#fbbf24' }}>
              {pushResult.unassignedWarnings.map((w, i) => (
                <li key={i} style={{ fontSize: 12 }}>{w}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {plan && (
        <div style={{ display: 'flex', gap: 12, minHeight: 400 }}>
          <div style={{ flex: 1 }}>
            <TicketList
              tickets={tickets}
              droppedIds={droppedIds}
              onDropTicket={handleDropTicket}
              onRestoreTicket={handleRestoreTicket}
            />
          </div>
          <div style={{
            flex: 1,
            background: '#1e2030',
            borderRadius: 8,
            padding: '1rem',
            overflowY: 'auto',
          }}>
            <PlanReasoningPanel assignments={plan.assignments} />
          </div>
        </div>
      )}

      {!plan && !generatePlan.isPending && (
        <div style={{ textAlign: 'center', padding: '5rem 0', color: '#374151' }}>
          <div style={{ fontSize: 48, marginBottom: 12 }}>✦</div>
          <div style={{ fontSize: 14, color: '#64748b' }}>Click "Generate Plan" to start sprint planning</div>
        </div>
      )}
    </div>
  )
}
