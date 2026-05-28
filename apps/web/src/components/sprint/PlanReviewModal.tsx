// apps/web/src/components/sprint/PlanReviewModal.tsx
// SB-10 / B8 — full-screen plan-review takeover. Orchestrates the inline
// refinement flow: a three-pane layout (left rail = ticket list, center =
// TicketEditorPane, right rail = assignee context) plus the SignOffCarousel
// for final approval. Owns the per-ticket editable state, draft persistence
// (localStorage, 30-day TTL), keyboard navigation, and the commit-approval
// assembly handed to the parent's onCommit.

import { useState, useMemo, useEffect, useCallback, CSSProperties } from 'react'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { Alert } from '../ui/Alert'
import type { BadgeVariant } from '../ui/Badge'
import { TicketEditorPane } from './TicketEditorPane'
import { SignOffCarousel } from './SignOffCarousel'
import type { SignOffTicket } from './SignOffCarousel'
import type { SprintPlanResponse, Assignment } from '../../types/sprint'
import type {
  TicketFields,
  RefinementTicket,
  CommitApproval,
  CommitRevision,
  CommitPlanResponse,
  ScopeCopResult,
} from '../../types/inlineRefinement'

export interface PlanReviewModalProps {
  plan: SprintPlanResponse
  open: boolean
  onClose: () => void
  onCommit: (approvals: CommitApproval[]) => void
  isPushing?: boolean
  pushResult?: CommitPlanResponse | null
}

// ---- constants -------------------------------------------------------------

const DRAFT_TTL_MS = 30 * 864e5 // 30 days

interface DraftPayload {
  savedAt: number
  data: Record<string, TicketFields>
}

const STATUS_VARIANT: Record<ScopeCopResult['status'], BadgeVariant> = {
  ready: 'success',
  needs_work: 'warning',
  blocked: 'danger',
}

const STATUS_LABELS: Record<ScopeCopResult['status'], string> = {
  ready: 'Ready',
  needs_work: 'Needs Work',
  blocked: 'Blocked',
}

// ---- pure helpers ----------------------------------------------------------

function arraysEqual(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false
  return true
}

function fieldsEqual(a: TicketFields, b: TicketFields): boolean {
  return (
    a.title === b.title &&
    a.description === b.description &&
    a.storyPoints === b.storyPoints &&
    arraysEqual(a.acceptanceCriteria, b.acceptanceCriteria)
  )
}

function cloneFields(f: TicketFields): TicketFields {
  return { ...f, acceptanceCriteria: f.acceptanceCriteria.slice() }
}

// Stable per-plan draft key. The plan response carries no plan_id, so we derive
// one from team + sprint start; a new plan for the same sprint window reuses the
// slot, which is the desired "latest draft wins" behavior for v1.
function planDraftKey(plan: SprintPlanResponse): string {
  return `plan-draft:${plan.team_id}:${plan.sprint_start}`
}

// Build the per-ticket refinement bundle from the plan + its Scope Cop results.
// NOTE: the plan assignment only carries title + story_points (no description /
// AC), so the "original" baseline leaves those empty. A richer original would
// come from SB-7's revision-preview endpoint; the modal uses what the plan
// provides.
function buildRefinementTickets(plan: SprintPlanResponse): RefinementTicket[] {
  return plan.assignments.map((a: Assignment) => {
    const scope = plan.scopeCopResults?.find(r => r.ticketKey === a.ticket_id)
    const original: TicketFields = {
      title: a.title,
      description: '',
      acceptanceCriteria: [],
      storyPoints: a.story_points,
    }
    const sr = scope?.suggestedRevision
    const suggested: TicketFields = {
      title: sr?.title ?? original.title,
      description: sr?.description ?? original.description,
      acceptanceCriteria: sr?.acceptance_criteria ?? [],
      storyPoints: sr?.story_points ?? original.storyPoints,
    }
    return {
      ticketKey: a.ticket_id,
      developerId: a.developer_id,
      developerName: a.developer_name,
      reasoning: a.reasoning,
      readinessScore: scope?.readinessScore ?? null,
      status: scope?.status ?? null,
      original,
      suggested,
      fetchedUpdatedAt: scope?.fetchedUpdatedAt ?? null,
    }
  })
}

function loadDraft(plan: SprintPlanResponse): Record<string, TicketFields> | null {
  try {
    const raw = window.localStorage.getItem(planDraftKey(plan))
    if (!raw) return null
    const parsed = JSON.parse(raw) as DraftPayload
    if (typeof parsed?.savedAt !== 'number' || !parsed.data) return null
    if (Date.now() - parsed.savedAt >= DRAFT_TTL_MS) {
      // Stale draft — clear it so it does not linger.
      window.localStorage.removeItem(planDraftKey(plan))
      return null
    }
    return parsed.data
  } catch {
    return null
  }
}

// ---- main component --------------------------------------------------------

export function PlanReviewModal({
  plan,
  open,
  onClose,
  onCommit,
  isPushing,
  pushResult,
}: PlanReviewModalProps): JSX.Element | null {
  const tickets = useMemo(() => buildRefinementTickets(plan), [plan])

  const ticketByKey = useMemo(() => {
    const map: Record<string, RefinementTicket> = {}
    for (const t of tickets) map[t.ticketKey] = t
    return map
  }, [tickets])

  // Editable current state per ticket. Initialize each to a copy of the
  // ticket's suggested fields, then overlay any restored draft.
  const [currentByKey, setCurrentByKey] = useState<Record<string, TicketFields>>({})
  const [lastEditedAt, setLastEditedAt] = useState<Record<string, number>>({})
  const [selectedKey, setSelectedKey] = useState<string>('')
  const [showCarousel, setShowCarousel] = useState(false)

  // (Re)initialize editable state whenever the underlying plan changes. Start
  // from Scope Cop's suggestion, then restore a fresh-enough localStorage draft
  // over the top.
  useEffect(() => {
    const base: Record<string, TicketFields> = {}
    for (const t of tickets) base[t.ticketKey] = cloneFields(t.suggested)
    const draft = loadDraft(plan)
    if (draft) {
      for (const t of tickets) {
        const d = draft[t.ticketKey]
        if (d) {
          base[t.ticketKey] = {
            title: d.title ?? base[t.ticketKey].title,
            description: d.description ?? base[t.ticketKey].description,
            acceptanceCriteria: Array.isArray(d.acceptanceCriteria)
              ? d.acceptanceCriteria.slice()
              : base[t.ticketKey].acceptanceCriteria,
            storyPoints: d.storyPoints ?? base[t.ticketKey].storyPoints,
          }
        }
      }
    }
    setCurrentByKey(base)
    setLastEditedAt({})
    setSelectedKey(tickets.length > 0 ? tickets[0].ticketKey : '')
    setShowCarousel(false)
  }, [plan, tickets])

  // Sum of assigned story points per developer (for the right-rail load line).
  const assignedPointsByDev = useMemo(() => {
    const acc: Record<string, number> = {}
    for (const a of plan.assignments) {
      acc[a.developer_id] = (acc[a.developer_id] ?? 0) + (a.story_points ?? 0)
    }
    return acc
  }, [plan.assignments])

  const handleEditTicket = useCallback((key: string, next: TicketFields) => {
    setCurrentByKey(prev => ({ ...prev, [key]: next }))
    setLastEditedAt(prev => ({ ...prev, [key]: Date.now() }))
  }, [])

  const saveDraft = useCallback(() => {
    try {
      const payload: DraftPayload = { savedAt: Date.now(), data: currentByKey }
      window.localStorage.setItem(planDraftKey(plan), JSON.stringify(payload))
    } catch {
      // localStorage unavailable / quota exceeded — drafts are best-effort.
    }
  }, [plan, currentByKey])

  // Any story-point delta vs. the original baseline triggers the re-plan banner.
  const hasStoryPointChange = useMemo(() => {
    return tickets.some(t => {
      const cur = currentByKey[t.ticketKey]
      if (!cur) return false
      return cur.storyPoints !== t.original.storyPoints
    })
  }, [tickets, currentByKey])

  // Keyboard navigation: j/↓ and k/↑ move rail selection; Cmd+Enter opens the
  // carousel; Esc closes the modal. Disabled while the carousel owns the screen
  // (the carousel installs its own Esc handler).
  useEffect(() => {
    if (!open || showCarousel) return
    function onKey(e: KeyboardEvent) {
      const target = e.target as HTMLElement | null
      const tag = target?.tagName
      const typing = tag === 'INPUT' || tag === 'TEXTAREA' || target?.isContentEditable
      if (e.key === 'Escape') {
        e.preventDefault()
        onClose()
        return
      }
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
        e.preventDefault()
        setShowCarousel(true)
        return
      }
      // Rail nav keys only when not editing text (so j/k don't hijack typing).
      if (typing) return
      const isDown = e.key === 'j' || e.key === 'ArrowDown'
      const isUp = e.key === 'k' || e.key === 'ArrowUp'
      if (!isDown && !isUp) return
      e.preventDefault()
      setSelectedKey(prevKey => {
        const idx = tickets.findIndex(t => t.ticketKey === prevKey)
        if (tickets.length === 0) return prevKey
        const base = idx < 0 ? 0 : idx
        const nextIdx = isDown
          ? Math.min(tickets.length - 1, base + 1)
          : Math.max(0, base - 1)
        return tickets[nextIdx].ticketKey
      })
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, showCarousel, tickets, onClose])

  // Build CommitApproval[] from the carousel-approved keys. A `revision` is only
  // attached when the current content actually differs from the original
  // baseline (snake_case for the backend contract).
  const handlePush = useCallback(
    (approvedKeys: string[]) => {
      const approvals: CommitApproval[] = approvedKeys.map(key => {
        const t = ticketByKey[key]
        const cur = currentByKey[key]
        const approval: CommitApproval = {
          ticket_key: key,
          approved_at: new Date().toISOString(),
          fetched_updated_at: t?.fetchedUpdatedAt ?? null,
          developer_id: t?.developerId ?? null,
        }
        if (t && cur && !fieldsEqual(cur, t.original)) {
          const revision: CommitRevision = {
            title: cur.title,
            description: cur.description,
            acceptance_criteria: cur.acceptanceCriteria,
            story_points: cur.storyPoints ?? undefined,
          }
          approval.revision = revision
        }
        return approval
      })
      onCommit(approvals)
    },
    [ticketByKey, currentByKey, onCommit],
  )

  if (!open) return null

  // ---- carousel takeover ----
  if (showCarousel) {
    const signOffTickets: SignOffTicket[] = tickets.map(t => ({
      ticketKey: t.ticketKey,
      developerName: t.developerName,
      reasoning: t.reasoning,
      original: t.original,
      current: currentByKey[t.ticketKey] ?? cloneFields(t.suggested),
      lastEditedAt: lastEditedAt[t.ticketKey] ?? null,
    }))
    return (
      <SignOffCarousel
        tickets={signOffTickets}
        onClose={() => setShowCarousel(false)}
        onEditTicket={key => {
          setSelectedKey(key)
          setShowCarousel(false)
        }}
        onPush={handlePush}
        isPushing={isPushing}
        pushResult={
          pushResult
            ? { committed: pushResult.committed, conflicts: pushResult.conflicts }
            : null
        }
      />
    )
  }

  const selected = ticketByKey[selectedKey]
  const selectedCurrent = selectedKey ? currentByKey[selectedKey] : undefined

  return (
    <div style={overlayStyle} role="dialog" aria-modal="true">
      {/* ---------- header ---------- */}
      <div style={headerStyle}>
        <span style={{ fontSize: 'var(--text-base)', fontWeight: 700, color: 'var(--color-text-primary)' }}>
          Review sprint plan
        </span>
        <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-muted)' }}>
          {tickets.length} ticket{tickets.length === 1 ? '' : 's'}
        </span>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 10 }}>
          <Button variant="secondary" onClick={saveDraft}>Save Draft</Button>
          <Button variant="ghost" onClick={onClose}>Close</Button>
        </div>
      </div>

      {/* ---------- three-pane body ---------- */}
      <div style={bodyStyle}>
        {/* LEFT: ticket rail */}
        <div style={leftRailStyle}>
          {tickets.map(t => {
            const isSelected = t.ticketKey === selectedKey
            const cur = currentByKey[t.ticketKey]
            return (
              <div
                key={t.ticketKey}
                onClick={() => setSelectedKey(t.ticketKey)}
                style={{
                  ...railRowStyle,
                  background: isSelected ? 'var(--color-bg-secondary)' : 'transparent',
                  borderLeft: isSelected
                    ? '3px solid var(--color-accent)'
                    : '3px solid transparent',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                  {t.status ? (
                    <Badge variant={STATUS_VARIANT[t.status]}>{STATUS_LABELS[t.status]}</Badge>
                  ) : (
                    <Badge variant="default">—</Badge>
                  )}
                  <span style={{ fontSize: 'var(--text-xs)', fontWeight: 700, color: 'var(--color-text-secondary)' }}>
                    {t.ticketKey}
                  </span>
                  <span style={{ marginLeft: 'auto', fontSize: 'var(--text-xs)', color: 'var(--color-text-muted)' }}>
                    {cur?.storyPoints ?? t.original.storyPoints ?? '—'} pts
                  </span>
                </div>
                <div style={{ fontSize: 'var(--text-sm)', color: 'var(--color-text-primary)', marginBottom: 2 }}>
                  {(cur?.title ?? t.original.title) || '—'}
                </div>
                <div style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-muted)' }}>
                  {t.developerName}
                </div>
              </div>
            )
          })}
          {tickets.length === 0 && (
            <div style={{ padding: 16, fontSize: 'var(--text-sm)', color: 'var(--color-text-muted)' }}>
              No tickets in this plan.
            </div>
          )}
        </div>

        {/* CENTER: editor */}
        <div style={centerStyle}>
          {selected && selectedCurrent ? (
            <TicketEditorPane
              key={selected.ticketKey}
              original={selected.original}
              current={selectedCurrent}
              suggested={selected.suggested}
              onChange={next => handleEditTicket(selected.ticketKey, next)}
            />
          ) : (
            <div style={{ fontSize: 'var(--text-sm)', color: 'var(--color-text-muted)' }}>
              Select a ticket from the list to refine it.
            </div>
          )}
        </div>

        {/* RIGHT: assignee context */}
        <div style={rightRailStyle}>
          {selected ? (
            <>
              <div style={sectionLabelStyle}>Assignee</div>
              <div style={{ fontSize: 'var(--text-sm)', fontWeight: 600, color: 'var(--color-text-primary)', marginBottom: 16 }}>
                {selected.developerName}
              </div>

              <div style={sectionLabelStyle}>Sprint load</div>
              <div style={{ fontSize: 'var(--text-sm)', color: 'var(--color-text-primary)', marginBottom: 4 }}>
                {assignedPointsByDev[selected.developerId] ?? 0} pts assigned
              </div>
              <div style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-muted)', marginBottom: 16 }}>
                safe capacity unavailable
              </div>
              <Button
                variant="ghost"
                size="sm"
                disabled
                style={{ color: 'var(--color-accent)', marginBottom: 16, padding: 0, height: 'auto' }}
                title="Reassignment is not available in this view yet"
              >
                Reassign
              </Button>

              <div style={sectionLabelStyle}>Velocity citation</div>
              <div style={{ fontSize: 'var(--text-sm)', color: 'var(--color-text-secondary)', lineHeight: 1.5 }}>
                {selected.reasoning || '—'}
              </div>
            </>
          ) : (
            <div style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-muted)' }}>
              No ticket selected.
            </div>
          )}
        </div>
      </div>

      {/* ---------- footer ---------- */}
      <div style={footerStyle}>
        {hasStoryPointChange && (
          <div style={{ flex: 1, marginRight: 12 }}>
            <Alert variant="warning" title="Ticket points changed">
              Ticket points changed — re-plan capacity?
            </Alert>
          </div>
        )}
        <div style={{ marginLeft: 'auto' }}>
          <Button variant="primary" onClick={() => setShowCarousel(true)}>
            Review and Commit
          </Button>
        </div>
      </div>
    </div>
  )
}

// ---- styles ----------------------------------------------------------------

const overlayStyle: CSSProperties = {
  position: 'fixed',
  inset: 0,
  zIndex: 1000,
  background: 'var(--color-bg-primary)',
  display: 'flex',
  flexDirection: 'column',
  fontFamily: 'var(--font-sans)',
}

const headerStyle: CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 12,
  padding: '14px 24px',
  borderBottom: '1px solid var(--color-border)',
  flexShrink: 0,
}

const bodyStyle: CSSProperties = {
  flex: 1,
  display: 'flex',
  minHeight: 0,
}

const leftRailStyle: CSSProperties = {
  width: 280,
  flexShrink: 0,
  borderRight: '1px solid var(--color-border)',
  overflowY: 'auto',
  padding: '8px 0',
}

const railRowStyle: CSSProperties = {
  padding: '8px 12px',
  cursor: 'pointer',
}

const centerStyle: CSSProperties = {
  flex: 1,
  minWidth: 0,
  overflowY: 'auto',
  padding: '24px',
}

const rightRailStyle: CSSProperties = {
  width: 280,
  flexShrink: 0,
  borderLeft: '1px solid var(--color-border)',
  overflowY: 'auto',
  padding: '20px',
}

const sectionLabelStyle: CSSProperties = {
  fontSize: 'var(--text-xs)',
  fontWeight: 700,
  textTransform: 'uppercase',
  letterSpacing: '0.04em',
  color: 'var(--color-text-muted)',
  marginBottom: 4,
}

const footerStyle: CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 10,
  padding: '14px 24px',
  borderTop: '1px solid var(--color-border)',
  flexShrink: 0,
}
