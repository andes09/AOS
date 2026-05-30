// apps/web/src/pages/SprintPlannerPage.tsx

import { useState, useEffect, useRef } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useApi, ApiError } from '../lib/api'
import { VelocityCard } from '../components/sprint/VelocityCard'
import { ConfidenceGauge } from '../components/sprint/ConfidenceGauge'
import { TicketList } from '../components/sprint/TicketList'
import { PlanReasoningPanel } from '../components/sprint/PlanReasoningPanel'
import { ScopeCopPanel } from '../components/sprint/ScopeCopPanel'
import { CapacitySettingsPanel } from '../components/sprint/CapacitySettingsPanel'
import { MeetingLoadWarning } from '../components/sprint/MeetingLoadWarning'
import { ReviewRefineCarousel } from '../components/sprint/ReviewRefineCarousel'
import { Button } from '../components/ui/Button'
import { Alert } from '../components/ui/Alert'
import { Card, CardBody } from '../components/ui/Card'
import { useFeature } from '../featureFlags'
import { useNavigate } from 'react-router-dom'
import type { SprintPlanResponse, WhatIfResponse, Ticket, PushToJiraResponse } from '../types/sprint'
import type { CommitApproval, CommitPlanRequest, CommitPlanResponse } from '../types/inlineRefinement'
import type { AnalyzeResponse } from '../types/scopeCop'
import type { TeamCapacityResponse } from '../types/capacity'

const SESSION_KEY = 'sprint_plan_cache'

function deriveCommitted(assignments: SprintPlanResponse['assignments']): Map<string, number> {
  const map = new Map<string, number>()
  for (const a of assignments) {
    map.set(a.developer_id, (map.get(a.developer_id) ?? 0) + a.story_points)
  }
  return map
}

const DEFAULT_CAPACITY = 40

function RecurringIssuesPanel({ warnings }: { warnings: string[] }) {
  const [open, setOpen] = useState(warnings.length <= 2)
  return (
    <Card>
      <CardBody style={{ padding: '10px 14px' }}>
        <button
          onClick={() => setOpen(o => !o)}
          style={{
            background: 'none',
            border: 'none',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: 0,
            width: '100%',
            textAlign: 'left',
          }}
        >
          <span style={{ color: 'var(--color-accent)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)', fontWeight: 600 }}>
            Recurring Issues ({warnings.length})
          </span>
          <span style={{ color: 'var(--color-text-muted)', fontSize: 'var(--text-xs)', marginLeft: 'auto' }}>
            {open ? '▲' : '▼'}
          </span>
        </button>
        {open && (
          <ul style={{ margin: '8px 0 0', paddingLeft: 18, display: 'flex', flexDirection: 'column', gap: 4 }}>
            {warnings.map((w, i) => (
              <li key={i} style={{ color: 'var(--color-text-secondary)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)', lineHeight: 1.5 }}>{w}</li>
            ))}
          </ul>
        )}
      </CardBody>
    </Card>
  )
}

export function SprintPlannerPage() {
  const { post, get } = useApi()
  const navigate = useNavigate()
  const canPushToJira = useFeature('push_to_jira')
  const canInlineRefine = useFeature('scope_check_v2')
  const canScanDependencies = useFeature('dependency_radar')

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
  const [capacityOpen, setCapacityOpen] = useState(false)
  const [reviewOpen, setReviewOpen] = useState(false)
  const [commitResult, setCommitResult] = useState<CommitPlanResponse | null>(null)

  const capacityQuery = useQuery({
    queryKey: ['capacity', 'team', 'default'],
    queryFn: () => get<TeamCapacityResponse>('/api/capacity/team/default'),
  })
  const capacityData = capacityQuery.data ?? null
  const capacityRef = useRef<HTMLDivElement>(null)
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
      // Inline-refinement rollout: auto-open the review modal so the lead can
      // refine + commit. Gated behind scope_check_v2 — when off, behave as today.
      if (canInlineRefine) {
        setCommitResult(null)
        setReviewOpen(true)
      }
    },
  })

  const commitMutation = useMutation({
    mutationFn: (approvals: CommitApproval[]) => {
      const planId = encodeURIComponent(`${plan!.team_id}:${plan!.sprint_start}`)
      return post<CommitPlanResponse>(`/api/sprint-brain/plans/${planId}/commit`, {
        team_id: plan!.team_id,
        sprint_id: null,
        approvals,
      } satisfies CommitPlanRequest)
    },
    onSuccess: (data) => {
      setCommitResult(data)
      // No conflicts → close the modal. With conflicts, keep it open so the
      // carousel's Done screen can surface them.
      if (data.conflicts.length === 0) setReviewOpen(false)
    },
  })

  const pushMutation = useMutation({
    mutationFn: () => {
      const today = new Date()
      const end = new Date(today)
      end.setDate(end.getDate() + 14)
      const fmt = (d: Date) => d.toISOString().slice(0, 10)
      return post<PushToJiraResponse>('/api/sprint-brain/push-to-jira', {
        teamId: 'default',
        sprintName: `Sprint ${fmt(today)}`,
        sprintStartDate: fmt(today),
        sprintEndDate: fmt(end),
        assignments: (plan?.assignments ?? []).map(a => ({
          ticketId: a.ticket_id,
          developerId: a.developer_id,
        })),
      })
    },
    onSuccess: (data) => { setPushResult(data); setPushError(null) },
    onError: (err: ApiError) => {
      if (err.status === 409) setPushError('Active sprint in progress — end it in Jira first.')
      else if (err.status === 402) setPushError('No Jira connection. Connect in Settings.')
      else setPushError('Push failed. Try again.')
    },
  })

  const scopeAnalysisMutation = useMutation({
    mutationFn: () => post<AnalyzeResponse>('/api/scope-cop/analyze', {
      teamId: 'default',
      ticketKeys: (plan?.assignments ?? []).map(a => a.ticket_id),
    }),
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

  const committed = plan ? deriveCommitted(plan.assignments.filter(a => !droppedIds.has(a.ticket_id))) : new Map<string, number>()
  const developers = Array.from(committed.keys())
  const devNameMap = plan?.developers ?? {}

  const tickets: Ticket[] = (plan?.assignments ?? []).map(a => ({
    ticket_id: a.ticket_id,
    title: a.title || a.ticket_id,
    developer_id: a.developer_id,
    developer_name: a.developer_name || devNameMap[a.developer_id.toLowerCase()] || a.developer_id,
    story_points: a.story_points,
    confidence: a.confidence,
    skill_vector: a.skill_vector,
    matched_identifiers: a.matched_identifiers,
  }))

  return (
    <div style={{ fontFamily: 'var(--font-sans)', minHeight: '100%' }}>

      {/* Top row: velocity cards + gauge + action buttons */}
      <div style={{ display: 'flex', gap: 12, alignItems: 'stretch', marginBottom: 16, flexWrap: 'wrap' }}>

        {developers.length === 0 && !generatePlan.isPending && (
          <Card style={{ flex: 1 }}>
            <CardBody style={{
              color: 'var(--color-text-muted)',
              fontSize: 'var(--text-sm)',
              display: 'flex',
              alignItems: 'center',
            }}>
              Velocity cards will appear here after generating a plan.
            </CardBody>
          </Card>
        )}

        {developers.map(dev => (
          <VelocityCard
            key={dev}
            developer={devNameMap[dev] || dev}
            meanVelocity={committed.get(dev) ?? 0}
            committed={committed.get(dev) ?? 0}
            capacity={
              capacityData?.developers.find(d => d.displayName === (devNameMap[dev] || dev))?.effectiveCapacityPts
              ?? DEFAULT_CAPACITY
            }
            sprintCount={3}
          />
        ))}

        {plan && (
          <Card>
            <CardBody style={{ display: 'flex', alignItems: 'center' }}>
              <ConfidenceGauge score={confidence} sampleSize={plan.assignments.length} />
            </CardBody>
          </Card>
        )}

        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <Button
            variant="primary"
            onClick={() => generatePlan.mutate()}
            disabled={generatePlan.isPending}
          >
            {generatePlan.isPending ? 'Generating...' : 'Generate Plan'}
          </Button>

          {/* Legacy push CTA — hidden when inline refinement is on; the modal's
              Review-and-Commit flow supersedes it. */}
          {plan && canPushToJira && !canInlineRefine && (
            <Button
              variant="secondary"
              onClick={() => pushMutation.mutate()}
              disabled={pushMutation.isPending}
              style={{ color: 'var(--color-success)', borderColor: 'var(--color-success)' }}
            >
              {pushMutation.isPending ? 'Pushing...' : 'Push to Jira'}
            </Button>
          )}

          {plan && canInlineRefine && (
            <Button
              variant="primary"
              onClick={() => setReviewOpen(true)}
            >
              ✦ Review
            </Button>
          )}
        </div>
      </div>

      {/* Capacity panel — collapsible */}
      <div style={{ marginBottom: 12 }}>
        <button
          onClick={() => setCapacityOpen(o => !o)}
          style={{
            background: 'none',
            border: 'none',
            cursor: 'pointer',
            color: 'var(--color-text-muted)',
            fontFamily: 'var(--font-sans)',
            fontSize: 'var(--text-xs)',
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            padding: 0,
          }}
        >
          <span>{capacityOpen ? '▼' : '▶'}</span>
          <span>Capacity Settings</span>
        </button>
        {capacityOpen && (
          <div ref={capacityRef} style={{ marginTop: 8 }}>
            <CapacitySettingsPanel />
          </div>
        )}
      </div>

      {capacityData && capacityData.developers.some(d => d.isHighMeetingLoad) && (
        <MeetingLoadWarning
          developers={capacityData.developers}
          onAdjustCapacity={() => {
            setCapacityOpen(true)
            capacityRef.current?.scrollIntoView({ behavior: 'smooth' })
          }}
        />
      )}

      {generatePlan.isError && (
        <Alert variant="danger" style={{ marginBottom: 12 }}>
          {generatePlan.error instanceof Error
            ? generatePlan.error.message
            : 'Failed to generate plan. Check your Anthropic key and Jira connection.'}
        </Alert>
      )}

      {warnings.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginBottom: 16 }}>
          {warnings.map((w, i) => (
            <Alert key={i} variant="warning">{w}</Alert>
          ))}
        </div>
      )}

      {pushError && (
        <Alert variant="danger" style={{ marginBottom: 16 }}>{pushError}</Alert>
      )}

      {pushResult && (
        <Alert variant="success" style={{ marginBottom: 16 }}>
          Sprint pushed! {pushResult.pushedTickets} tickets assigned.{' '}
          <a href={pushResult.sprintUrl} target="_blank" rel="noreferrer" style={{ color: 'var(--color-accent)', textDecoration: 'underline' }}>
            View in Jira
          </a>
          {pushResult.unassignedWarnings.length > 0 && (
            <ul style={{ margin: '8px 0 0', paddingLeft: 20, color: 'var(--color-warning)' }}>
              {pushResult.unassignedWarnings.map((w, i) => (
                <li key={i} style={{ fontSize: 'var(--text-xs)' }}>{w}</li>
              ))}
            </ul>
          )}
        </Alert>
      )}

      {commitResult && commitResult.conflicts.length === 0 && commitResult.committed.length > 0 && (
        <Alert variant="success" style={{ marginBottom: 16 }}>
          Committed {commitResult.committed.length} ticket{commitResult.committed.length === 1 ? '' : 's'} to Jira.
        </Alert>
      )}

      {scopeAnalysisMutation.data?.summary.needsWorkCount != null &&
        scopeAnalysisMutation.data.summary.needsWorkCount > 0 && (
        <Alert variant="warning" style={{ marginBottom: 12 }}>
          {scopeAnalysisMutation.data.summary.needsWorkCount} ticket{scopeAnalysisMutation.data.summary.needsWorkCount !== 1 ? 's' : ''} need work before planning
        </Alert>
      )}

      {scopeAnalysisMutation.data && (
        <ScopeCopPanel
          response={scopeAnalysisMutation.data}
          onReanalyze={() => scopeAnalysisMutation.mutate()}
          isPending={scopeAnalysisMutation.isPending}
        />
      )}

      {/* Enrichment status panels (Tracks 22 + 23) */}
      {plan?.enrichmentStatus && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 12 }}>

          {/* Scope Check status */}
          {plan.enrichmentStatus.scopeCop === 'all_ready' && (
            <Alert variant="success">All tickets scope-ready</Alert>
          )}
          {plan.enrichmentStatus.scopeCop === 'has_issues' && (plan.scopeWarnings ?? []).map(w => (
            <Alert key={w.ticketId} variant="warning" title={w.ticketId}>
              {w.status}
              {w.issues.length > 0 && (
                <span style={{ color: 'var(--color-text-secondary)', marginLeft: 8 }}>{w.issues.join(' · ')}</span>
              )}
            </Alert>
          ))}

          {/* Dependency Radar status */}
          {canScanDependencies && plan.enrichmentStatus.dependencyRadar === 'not_scanned' && (
            <Alert variant="warning">
              Dependencies not scanned —{' '}
              <button
                onClick={() => navigate('/app/dependency-radar')}
                style={{ background: 'transparent', border: 'none', color: 'var(--color-warning)', cursor: 'pointer', fontSize: 'var(--text-sm)', padding: 0, textDecoration: 'underline', fontFamily: 'var(--font-sans)' }}
              >
                run Dependency Radar
              </button>
            </Alert>
          )}
          {plan.enrichmentStatus.dependencyRadar === 'no_risks' && (
            <Alert variant="success">No dependency risks</Alert>
          )}
          {plan.enrichmentStatus.dependencyRadar === 'has_risks' && (plan.dependencyWarnings ?? []).map(w => (
            <Alert key={w.ticketId} variant="danger" title={`${w.ticketId} — ${w.riskLevel} risk`}>
              {w.description && <span>{w.description}</span>}
              <button
                onClick={() => navigate('/app/dependency-radar')}
                style={{ background: 'transparent', border: 'none', color: 'var(--color-danger)', cursor: 'pointer', fontSize: 'var(--text-xs)', padding: 0, marginLeft: 8, textDecoration: 'underline', fontFamily: 'var(--font-sans)' }}
              >
                View Radar
              </button>
            </Alert>
          ))}

          {/* Retro Patterns panel */}
          {plan.enrichmentStatus.retroPatterns === 'has_patterns' && (plan.historicalWarnings ?? []).length > 0 && (
            <RecurringIssuesPanel warnings={plan.historicalWarnings ?? []} />
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
          <Card style={{ flex: 1, overflow: 'hidden' }}>
            <CardBody style={{ height: '100%', overflowY: 'auto' }}>
              <PlanReasoningPanel assignments={plan.assignments} />
            </CardBody>
          </Card>
        </div>
      )}

      {!plan && !generatePlan.isPending && (
        <div style={{ textAlign: 'center', padding: '5rem 0', color: 'var(--color-text-muted)' }}>
          <div style={{ fontSize: 32, marginBottom: 12, color: 'var(--color-text-muted)' }}>✦</div>
          <div style={{ fontSize: 'var(--text-sm)', color: 'var(--color-text-muted)' }}>
            Click "Generate Plan" to start sprint planning
          </div>
        </div>
      )}

      {plan && canInlineRefine && (
        <ReviewRefineCarousel
          plan={plan}
          open={reviewOpen}
          onClose={() => setReviewOpen(false)}
          onCommit={(approvals) => commitMutation.mutate(approvals)}
          isPushing={commitMutation.isPending}
          pushResult={commitResult}
        />
      )}
    </div>
  )
}
