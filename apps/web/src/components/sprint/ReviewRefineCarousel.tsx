// apps/web/src/components/sprint/ReviewRefineCarousel.tsx
// Scope Cop · Review & Refine — a single carousel modal that replaces the
// previous three-component flow (PlanReviewModal + TicketEditorPane +
// SignOffCarousel). One ticket per slide, suggestion cards on the right rail,
// approval marches through the deck, and a Done screen handles the Jira push.

import {
  CSSProperties,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import { Button } from '../ui/Button'
import type { SprintPlanResponse, Assignment } from '../../types/sprint'
import type {
  TicketFields,
  RefinementTicket,
  CommitApproval,
  CommitRevision,
  CommitPlanResponse,
} from '../../types/inlineRefinement'

export interface ReviewRefineCarouselProps {
  plan: SprintPlanResponse
  open: boolean
  onClose: () => void
  onCommit: (approvals: CommitApproval[]) => void
  isPushing?: boolean
  pushResult?: CommitPlanResponse | null
}

// ─── constants ──────────────────────────────────────────────────────────────

const DRAFT_TTL_MS = 30 * 864e5 // 30 days

interface DraftPayload {
  savedAt: number
  data: Record<string, TicketFields>
}

// Category accent palette kept as raw hex — the design system has no category
// tokens for Clarity / Completeness / Sizing / Correctness.
const CAT = {
  clarity: { label: 'Clarity', color: '#9a5a06', bg: '#fdf2dc', ln: '#d99a2b' },
  completeness: { label: 'Completeness', color: '#1b5e8a', bg: '#e6f1f8', ln: '#3b8fc4' },
  sizing: { label: 'Sizing', color: '#5b3a8a', bg: '#efe9f8', ln: '#8a6fc4' },
  correctness: { label: 'Correctness', color: '#b3261e', bg: '#fbe9e8', ln: '#e06a63' },
} as const

type CategoryKey = keyof typeof CAT

const TYPE_META: Record<'Story' | 'Bug' | 'Task', { color: string; glyph: string }> = {
  Story: { color: 'var(--color-success)', glyph: '▦' },
  Bug: { color: 'var(--color-danger)', glyph: '●' },
  Task: { color: 'var(--color-accent)', glyph: '✔' },
}

type TicketType = keyof typeof TYPE_META
type Priority = 'High' | 'Medium' | 'Low'
type CardStatus = 'open' | 'accepted' | 'ignored'
type CardAction = 'replace-title' | 'replace-description' | 'set-description' | 'add-ac' | 'set-points'

interface SuggestionCardModel {
  id: string                // stable per ticket: derived from action + index
  ticketKey: string
  category: CategoryKey
  action: CardAction
  before?: string | number | null
  after: string | number
  message: string
}

// ─── pure helpers ───────────────────────────────────────────────────────────

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

function planDraftKey(plan: SprintPlanResponse): string {
  return `plan-draft:${plan.team_id}:${plan.sprint_start}`
}

// Replicated from PlanReviewModal so this file can stand alone after that
// component is deleted. Original baseline only has title + storyPoints because
// Assignment doesn't carry description / AC.
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
      window.localStorage.removeItem(planDraftKey(plan))
      return null
    }
    return parsed.data
  } catch {
    return null
  }
}

// Build the suggestion-card deck for one ticket by diffing suggested vs original
// at the field level. (Phrase-level diffs from the mock aren't supported by the
// current Scope Cop payload — see the file-header comment.)
function buildCardsFor(t: RefinementTicket): SuggestionCardModel[] {
  const out: SuggestionCardModel[] = []
  const o = t.original
  const s = t.suggested

  if (s.title !== o.title) {
    out.push({
      id: `${t.ticketKey}::title`,
      ticketKey: t.ticketKey,
      category: 'clarity',
      action: 'replace-title',
      before: o.title,
      after: s.title,
      message: 'Scope Cop rewrote the title for clarity.',
    })
  }

  if ((s.description || '') !== (o.description || '')) {
    const wasEmpty = !o.description?.trim()
    out.push({
      id: `${t.ticketKey}::desc`,
      ticketKey: t.ticketKey,
      category: wasEmpty ? 'completeness' : 'clarity',
      action: wasEmpty ? 'set-description' : 'replace-description',
      before: o.description,
      after: s.description,
      message: wasEmpty
        ? 'No description. A one-line intent gives the team something to estimate against.'
        : 'Tighten the description so the intent is unambiguous.',
    })
  }

  const oSet = new Set(o.acceptanceCriteria)
  s.acceptanceCriteria.forEach((ac, i) => {
    if (!oSet.has(ac)) {
      out.push({
        id: `${t.ticketKey}::ac::${i}`,
        ticketKey: t.ticketKey,
        category: 'completeness',
        action: 'add-ac',
        after: ac,
        message: 'Add this testable condition so the ticket can be closed confidently.',
      })
    }
  })

  if (s.storyPoints != null && s.storyPoints !== o.storyPoints) {
    out.push({
      id: `${t.ticketKey}::pts`,
      ticketKey: t.ticketKey,
      category: 'sizing',
      action: 'set-points',
      before: o.storyPoints,
      after: s.storyPoints,
      message:
        o.storyPoints == null
          ? 'Unestimated. Scope Cop suggested a starting estimate based on similar work.'
          : 'Re-estimate this ticket based on similar work in recent sprints.',
    })
  }

  return out
}

// Per-ticket synthesized meta the Assignment payload doesn't carry. These are
// purely presentational — they don't ride along on the commit.
function priorityFor(t: RefinementTicket): Priority {
  const r = t.readinessScore
  if (r == null) return 'Medium'
  if (r < 0.4) return 'High'
  if (r < 0.7) return 'Medium'
  return 'Low'
}

function ticketTypeFor(t: RefinementTicket): TicketType {
  // Lightweight heuristic from the ticket key prefix — backend doesn't carry
  // an explicit type. Defaults to Story.
  const key = t.ticketKey.toUpperCase()
  if (key.includes('BUG')) return 'Bug'
  if (key.includes('TASK') || key.includes('CHORE')) return 'Task'
  return 'Story'
}

// ─── atoms ──────────────────────────────────────────────────────────────────

function TypeBadge({ type }: { type: TicketType }) {
  const m = TYPE_META[type]
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        fontSize: 'var(--text-xs)',
        fontWeight: 600,
        color: 'var(--color-text-secondary)',
      }}
    >
      <span
        style={{
          width: 16,
          height: 16,
          borderRadius: 3,
          background: m.color,
          color: '#fff',
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: 9,
        }}
      >
        {m.glyph}
      </span>
      {type}
    </span>
  )
}

function Pill({
  children,
  color = 'var(--color-text-secondary)',
  bg = 'var(--color-bg-secondary)',
}: {
  children: React.ReactNode
  color?: string
  bg?: string
}) {
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 5,
        padding: '3px 9px',
        borderRadius: 999,
        fontSize: 11,
        fontWeight: 600,
        color,
        background: bg,
      }}
    >
      {children}
    </span>
  )
}

function PriorityPill({ priority }: { priority: Priority }) {
  if (priority === 'High') return <Pill color="#b3261e" bg="#fbe9e8">High</Pill>
  if (priority === 'Medium') return <Pill color="#9a5a06" bg="#fdf2dc">Medium</Pill>
  return <Pill>Low</Pill>
}

// ─── SuggestionCard ─────────────────────────────────────────────────────────

interface SuggestionCardProps {
  card: SuggestionCardModel
  status: CardStatus
  onAccept: () => void
  onIgnore: () => void
  onUndo: () => void
}

function SuggestionCard({ card, status, onAccept, onIgnore, onUndo }: SuggestionCardProps) {
  const c = CAT[card.category]
  const resolved = status !== 'open'

  return (
    <div
      style={{
        border: `1px solid var(--color-border)`,
        borderLeft: `3px solid ${c.ln}`,
        borderRadius: 8,
        padding: '12px 14px',
        background: 'var(--color-bg-elevated)',
        opacity: resolved ? 0.62 : 1,
        transition: 'opacity 0.12s',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 8,
        }}
      >
        <Pill color={c.color} bg={c.bg}>
          {c.label}
        </Pill>
        {status === 'accepted' && (
          <span
            style={{
              fontSize: 11,
              fontWeight: 600,
              color: 'var(--color-success)',
            }}
          >
            ✓ Accepted
          </span>
        )}
        {status === 'ignored' && (
          <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--color-text-muted)' }}>
            Ignored
          </span>
        )}
      </div>

      <p
        style={{
          fontSize: 13,
          color: 'var(--color-text-secondary)',
          lineHeight: 1.5,
          marginBottom: 10,
        }}
      >
        {card.message}
      </p>

      {/* before → after preview */}
      {(card.action === 'replace-title' || card.action === 'replace-description') && (
        <div style={{ fontSize: 13, lineHeight: 1.5, marginBottom: 12 }}>
          <span
            style={{
              color: 'var(--color-text-muted)',
              textDecoration: 'line-through',
              textDecorationColor: c.ln,
            }}
          >
            {String(card.before ?? '—') || '—'}
          </span>
          <span style={{ color: 'var(--color-text-muted)', margin: '0 6px' }}>→</span>
          <span style={{ color: 'var(--color-text-primary)', fontWeight: 500 }}>
            {String(card.after)}
          </span>
        </div>
      )}
      {card.action === 'set-description' && (
        <div
          style={{
            fontSize: 13,
            lineHeight: 1.5,
            marginBottom: 12,
            color: 'var(--color-text-primary)',
            fontWeight: 500,
          }}
        >
          “{String(card.after)}”
        </div>
      )}
      {card.action === 'add-ac' && (
        <div
          style={{
            fontSize: 13,
            lineHeight: 1.5,
            marginBottom: 12,
            color: 'var(--color-text-primary)',
            padding: '8px 10px',
            background: c.bg,
            borderRadius: 6,
          }}
        >
          + {String(card.after)}
        </div>
      )}
      {card.action === 'set-points' && (
        <div style={{ fontSize: 13, lineHeight: 1.5, marginBottom: 12 }}>
          <span style={{ color: 'var(--color-text-muted)' }}>Set estimate to </span>
          <span style={{ color: 'var(--color-text-primary)', fontWeight: 600 }}>
            {String(card.after)} points
          </span>
        </div>
      )}

      {!resolved ? (
        <div style={{ display: 'flex', gap: 8 }}>
          <button
            type="button"
            onClick={onAccept}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
              padding: '6px 12px',
              borderRadius: 6,
              background: 'var(--color-success)',
              color: '#fff',
              border: 'none',
              fontSize: 12,
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            ✓ Accept
          </button>
          <button
            type="button"
            onClick={onIgnore}
            style={{
              padding: '6px 12px',
              borderRadius: 6,
              background: 'transparent',
              color: 'var(--color-text-secondary)',
              border: `1px solid var(--color-border)`,
              fontSize: 12,
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            Ignore
          </button>
        </div>
      ) : (
        <button
          type="button"
          onClick={onUndo}
          style={{
            padding: '4px 0',
            background: 'transparent',
            color: 'var(--color-text-secondary)',
            border: 'none',
            fontSize: 12,
            fontWeight: 600,
            cursor: 'pointer',
            textDecoration: 'underline',
          }}
        >
          Undo
        </button>
      )}
    </div>
  )
}

// ─── FieldHead (Edit/Done toggle) ───────────────────────────────────────────

function FieldHead({
  label,
  onToggleEdit,
  editing,
}: {
  label: string
  onToggleEdit?: () => void
  editing?: boolean
}) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        marginBottom: 7,
      }}
    >
      <span
        style={{
          fontSize: 10,
          fontWeight: 700,
          color: 'var(--color-text-muted)',
          letterSpacing: '0.08em',
          textTransform: 'uppercase',
        }}
      >
        {label}
      </span>
      {onToggleEdit && (
        <button
          type="button"
          onClick={onToggleEdit}
          style={{
            background: 'transparent',
            border: 'none',
            color: 'var(--color-text-muted)',
            fontSize: 11,
            fontWeight: 600,
            cursor: 'pointer',
          }}
        >
          {editing ? 'Done' : 'Edit'}
        </button>
      )}
    </div>
  )
}

// ─── TicketSlide ────────────────────────────────────────────────────────────

interface TicketSlideProps {
  ticket: RefinementTicket
  current: TicketFields
  cards: SuggestionCardModel[]
  cardStatus: Record<string, CardStatus>
  onChangeCurrent: (next: TicketFields) => void
  onAcceptCard: (card: SuggestionCardModel) => void
  onIgnoreCard: (card: SuggestionCardModel) => void
  onUndoCard: (card: SuggestionCardModel) => void
}

function TicketSlide({
  ticket,
  current,
  cards,
  cardStatus,
  onChangeCurrent,
  onAcceptCard,
  onIgnoreCard,
  onUndoCard,
}: TicketSlideProps) {
  const [editing, setEditing] = useState<'title' | 'description' | null>(null)
  useEffect(() => {
    setEditing(null)
  }, [ticket.ticketKey])

  const type = ticketTypeFor(ticket)
  const priority = priorityFor(ticket)
  const labels: string[] = [] // Assignment carries no labels — leave empty.
  const assignee = ticket.developerName
  const openCount = cards.filter(c => cardStatus[c.id] === 'open').length

  function patch(p: Partial<TicketFields>) {
    onChangeCurrent({ ...current, ...p })
  }

  return (
    <div
      className="srf-slide-in"
      style={{
        display: 'grid',
        gridTemplateColumns: '1.45fr 1fr',
        minHeight: 0,
        height: '100%',
      }}
    >
      {/* Ticket panel — Jira style */}
      <div
        style={{
          overflowY: 'auto',
          padding: '24px 28px',
          borderRight: `1px solid var(--color-border)`,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 18 }}>
          <span
            style={{
              fontFamily: "'JetBrains Mono', ui-monospace, monospace",
              fontSize: 12,
              color: 'var(--color-text-muted)',
            }}
          >
            {ticket.ticketKey}
          </span>
          <TypeBadge type={type} />
          <PriorityPill priority={priority} />
        </div>

        {/* Title */}
        <FieldHead
          label="Summary"
          editing={editing === 'title'}
          onToggleEdit={() => setEditing(editing === 'title' ? null : 'title')}
        />
        {editing === 'title' ? (
          <input
            value={current.title}
            onChange={e => patch({ title: e.target.value })}
            autoFocus
            style={{
              width: '100%',
              fontSize: 20,
              fontWeight: 600,
              padding: '6px 10px',
              border: `1px solid var(--color-border)`,
              borderRadius: 6,
              marginBottom: 20,
              background: 'var(--color-bg-primary)',
              color: 'var(--color-text-primary)',
            }}
          />
        ) : (
          <h2
            style={{
              fontSize: 20,
              fontWeight: 600,
              letterSpacing: '-0.01em',
              lineHeight: 1.3,
              marginBottom: 20,
              color: 'var(--color-text-primary)',
            }}
          >
            {current.title || '—'}
          </h2>
        )}

        {/* Meta grid */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: '1fr 1fr',
            gap: 14,
            padding: '14px 16px',
            background: 'var(--color-bg-secondary)',
            border: `1px solid var(--color-border)`,
            borderRadius: 8,
            marginBottom: 22,
          }}
        >
          <div>
            <div style={metaLabel}>Assignee</div>
            <div
              style={{
                fontSize: 13,
                color: 'var(--color-text-primary)',
                fontWeight: 500,
              }}
            >
              {assignee || 'Unassigned'}
            </div>
          </div>
          <div>
            <div style={metaLabel}>Story points</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <input
                type="number"
                min={0}
                value={current.storyPoints ?? ''}
                placeholder="—"
                onChange={e =>
                  patch({
                    storyPoints: e.target.value === '' ? null : Number(e.target.value),
                  })
                }
                style={{
                  width: 56,
                  fontSize: 13,
                  fontWeight: 600,
                  padding: '4px 8px',
                  border: `1px solid ${
                    current.storyPoints == null ? CAT.sizing.ln : 'var(--color-border)'
                  }`,
                  borderRadius: 6,
                  background:
                    current.storyPoints == null ? CAT.sizing.bg : 'var(--color-bg-elevated)',
                  color: 'var(--color-text-primary)',
                }}
              />
              {current.storyPoints == null && (
                <span style={{ fontSize: 11, color: CAT.sizing.color, fontWeight: 600 }}>
                  Unestimated
                </span>
              )}
            </div>
          </div>
          <div style={{ gridColumn: '1 / -1' }}>
            <div style={metaLabel}>Labels</div>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {labels.length === 0 ? (
                <span
                  style={{
                    fontSize: 12,
                    color: 'var(--color-text-muted)',
                    fontStyle: 'italic',
                  }}
                >
                  None
                </span>
              ) : (
                labels.map(l => <Pill key={l}>{l}</Pill>)
              )}
            </div>
          </div>
        </div>

        {/* Description */}
        <FieldHead
          label="Description"
          editing={editing === 'description'}
          onToggleEdit={() =>
            setEditing(editing === 'description' ? null : 'description')
          }
        />
        {editing === 'description' ? (
          <textarea
            value={current.description}
            onChange={e => patch({ description: e.target.value })}
            autoFocus
            rows={4}
            placeholder="Describe the intent…"
            style={{
              width: '100%',
              fontSize: 14,
              lineHeight: 1.6,
              padding: '10px 12px',
              border: `1px solid var(--color-border)`,
              borderRadius: 6,
              marginBottom: 22,
              background: 'var(--color-bg-primary)',
              color: 'var(--color-text-primary)',
              resize: 'vertical',
            }}
          />
        ) : (
          <div
            style={{
              fontSize: 14,
              lineHeight: 1.65,
              color: current.description
                ? 'var(--color-text-primary)'
                : 'var(--color-text-muted)',
              marginBottom: 22,
              minHeight: 22,
              whiteSpace: 'pre-wrap',
            }}
          >
            {current.description || <em>No description yet.</em>}
          </div>
        )}

        {/* Acceptance criteria */}
        <FieldHead label="Acceptance criteria" />
        {current.acceptanceCriteria.length === 0 && (
          <div
            style={{
              fontSize: 13,
              color: 'var(--color-text-muted)',
              fontStyle: 'italic',
              padding: '8px 0',
              marginBottom: 4,
            }}
          >
            None defined.
          </div>
        )}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {current.acceptanceCriteria.map((ac, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: 8 }}>
              <span
                style={{
                  marginTop: 9,
                  width: 14,
                  height: 14,
                  flexShrink: 0,
                  borderRadius: 3,
                  border: `1.5px solid var(--color-border)`,
                  display: 'inline-block',
                }}
              />
              <input
                value={ac}
                onChange={e => {
                  const next = current.acceptanceCriteria.slice()
                  next[i] = e.target.value
                  patch({ acceptanceCriteria: next })
                }}
                style={{
                  flex: 1,
                  fontSize: 13,
                  lineHeight: 1.5,
                  padding: '5px 8px',
                  border: `1px solid var(--color-border-subtle)`,
                  borderRadius: 5,
                  background: 'transparent',
                  color: 'var(--color-text-primary)',
                }}
              />
              <button
                type="button"
                onClick={() =>
                  patch({
                    acceptanceCriteria: current.acceptanceCriteria.filter((_, j) => j !== i),
                  })
                }
                style={{
                  background: 'transparent',
                  border: 'none',
                  color: 'var(--color-text-muted)',
                  cursor: 'pointer',
                  fontSize: 16,
                  padding: '2px 4px',
                  marginTop: 4,
                }}
                title="Remove this criterion"
              >
                ×
              </button>
            </div>
          ))}
        </div>
        <button
          type="button"
          onClick={() =>
            patch({ acceptanceCriteria: [...current.acceptanceCriteria, ''] })
          }
          style={{
            marginTop: 8,
            background: 'transparent',
            border: 'none',
            color: 'var(--color-text-secondary)',
            fontSize: 12,
            fontWeight: 600,
            cursor: 'pointer',
            display: 'inline-flex',
            alignItems: 'center',
            gap: 5,
          }}
        >
          <span style={{ fontSize: 15, lineHeight: 1 }}>+</span> Add criterion
        </button>
      </div>

      {/* Suggestions rail */}
      <div
        style={{
          overflowY: 'auto',
          padding: '24px 22px',
          background: 'var(--color-bg-secondary)',
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            marginBottom: 16,
          }}
        >
          <h3
            style={{
              fontSize: 14,
              fontWeight: 700,
              color: 'var(--color-text-primary)',
            }}
          >
            Suggestions
          </h3>
          <span style={{ fontSize: 12, color: 'var(--color-text-secondary)' }}>
            {openCount} open
          </span>
        </div>

        {cards.length === 0 ? (
          <div
            style={{
              textAlign: 'center',
              padding: '40px 16px',
              color: 'var(--color-text-secondary)',
            }}
          >
            <div
              style={{
                width: 44,
                height: 44,
                borderRadius: '50%',
                background: 'var(--color-success-bg, #e8f5ee)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                margin: '0 auto 14px',
                color: 'var(--color-success)',
                fontSize: 22,
                fontWeight: 700,
              }}
            >
              ✓
            </div>
            <div
              style={{
                fontSize: 14,
                fontWeight: 600,
                color: 'var(--color-text-primary)',
                marginBottom: 4,
              }}
            >
              No issues found
            </div>
            <div style={{ fontSize: 13, color: 'var(--color-text-secondary)' }}>
              This ticket is ready to estimate.
            </div>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {cards.map(card => (
              <SuggestionCard
                key={card.id}
                card={card}
                status={cardStatus[card.id] ?? 'open'}
                onAccept={() => onAcceptCard(card)}
                onIgnore={() => onIgnoreCard(card)}
                onUndo={() => onUndoCard(card)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// ─── ProgressRail ───────────────────────────────────────────────────────────

interface ProgressRailProps {
  total: number
  index: number
  approvedKeys: Set<string>
  ticketKeys: string[]
  onJump: (i: number) => void
}

function ProgressRail({ total, index, approvedKeys, ticketKeys, onJump }: ProgressRailProps) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 6,
        padding: '12px 20px',
        borderBottom: `1px solid var(--color-border-subtle)`,
      }}
    >
      {ticketKeys.map((k, i) => {
        const approved = approvedKeys.has(k)
        const cur = i === index
        return (
          <button
            key={k}
            type="button"
            onClick={() => onJump(i)}
            title={k}
            style={{
              flex: 1,
              height: 6,
              borderRadius: 999,
              border: 'none',
              cursor: 'pointer',
              padding: 0,
              background: approved
                ? 'var(--color-success)'
                : cur
                ? 'var(--color-text-primary)'
                : 'var(--color-bg-secondary)',
              outline: cur ? `2px solid var(--color-text-primary)` : 'none',
              outlineOffset: 2,
              transition: 'background 0.2s',
            }}
          />
        )
      })}
      <span
        style={{
          fontSize: 12,
          color: 'var(--color-text-secondary)',
          marginLeft: 10,
          whiteSpace: 'nowrap',
          fontVariantNumeric: 'tabular-nums',
        }}
      >
        Ticket {Math.min(index + 1, total)} of {total}
      </span>
    </div>
  )
}

// ─── DoneScreen ─────────────────────────────────────────────────────────────

interface DoneScreenProps {
  approvedCount: number
  refinedCount: number
  isPushing: boolean
  pushResult: CommitPlanResponse | null | undefined
  onPush: () => void
  onClose: () => void
  onEditConflict: (ticketKey: string) => void
}

function DoneScreen({
  approvedCount,
  refinedCount,
  isPushing,
  pushResult,
  onPush,
  onClose,
  onEditConflict,
}: DoneScreenProps) {
  const conflicts = pushResult?.conflicts ?? []
  const committed = pushResult?.committed ?? []

  return (
    <div
      style={{
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '48px',
        textAlign: 'center',
      }}
    >
      <div
        style={{
          width: 64,
          height: 64,
          borderRadius: '50%',
          background: 'var(--color-success-bg, #e8f5ee)',
          color: 'var(--color-success)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          marginBottom: 24,
          fontSize: 32,
          fontWeight: 700,
        }}
      >
        ✓
      </div>
      <h2
        style={{
          fontSize: 24,
          fontWeight: 700,
          letterSpacing: '-0.02em',
          marginBottom: 8,
          color: 'var(--color-text-primary)',
        }}
      >
        Backlog refined
      </h2>
      <p
        style={{
          fontSize: 15,
          color: 'var(--color-text-secondary)',
          maxWidth: 380,
          lineHeight: 1.6,
          marginBottom: 28,
        }}
      >
        {approvedCount} approved · {refinedCount} refined. They're ready to carry into
        Sprint Brain planning.
      </p>

      {pushResult && (
        <div
          style={{
            marginBottom: 24,
            padding: '12px 16px',
            borderRadius: 8,
            background:
              conflicts.length > 0
                ? 'var(--color-warning-bg, #fdf2dc)'
                : 'var(--color-success-bg, #e8f5ee)',
            color:
              conflicts.length > 0 ? 'var(--color-warning)' : 'var(--color-success)',
            fontSize: 13,
            fontWeight: 600,
            maxWidth: 480,
          }}
        >
          {committed.length} pushed, {conflicts.length} conflict
          {conflicts.length === 1 ? '' : 's'}.
        </div>
      )}

      {conflicts.length > 0 && (
        <div
          style={{
            width: '100%',
            maxWidth: 480,
            marginBottom: 24,
            display: 'flex',
            flexDirection: 'column',
            gap: 8,
            textAlign: 'left',
          }}
        >
          {conflicts.map(c => (
            <div
              key={c.ticket_key}
              style={{
                display: 'flex',
                alignItems: 'flex-start',
                gap: 10,
                padding: '10px 12px',
                border: `1px solid var(--color-border)`,
                borderRadius: 8,
                background: 'var(--color-bg-elevated)',
              }}
            >
              <span
                style={{
                  fontFamily: "'JetBrains Mono', ui-monospace, monospace",
                  fontSize: 12,
                  fontWeight: 700,
                  color: 'var(--color-danger)',
                }}
              >
                {c.ticket_key}
              </span>
              <span
                style={{
                  flex: 1,
                  fontSize: 13,
                  color: 'var(--color-text-secondary)',
                }}
              >
                {c.reason}
              </span>
              <Button variant="ghost" size="sm" onClick={() => onEditConflict(c.ticket_key)}>
                Back to edit
              </Button>
            </div>
          ))}
        </div>
      )}

      <div style={{ display: 'flex', gap: 10 }}>
        <button
          type="button"
          onClick={onPush}
          disabled={isPushing || approvedCount === 0}
          style={{
            height: 44,
            padding: '0 22px',
            background: 'var(--color-text-primary)',
            color: 'var(--color-bg-primary)',
            border: 'none',
            borderRadius: 9,
            fontSize: 14,
            fontWeight: 600,
            cursor: isPushing || approvedCount === 0 ? 'default' : 'pointer',
            opacity: isPushing || approvedCount === 0 ? 0.5 : 1,
          }}
        >
          {isPushing ? 'Pushing…' : 'Push to Jira'}
        </button>
        <button
          type="button"
          onClick={onClose}
          style={{
            height: 44,
            padding: '0 20px',
            background: 'transparent',
            color: 'var(--color-text-secondary)',
            border: `1px solid var(--color-border)`,
            borderRadius: 9,
            fontSize: 14,
            fontWeight: 600,
            cursor: 'pointer',
          }}
        >
          Back to backlog
        </button>
      </div>
    </div>
  )
}

// ─── main component ─────────────────────────────────────────────────────────

export function ReviewRefineCarousel({
  plan,
  open,
  onClose,
  onCommit,
  isPushing,
  pushResult,
}: ReviewRefineCarouselProps): JSX.Element | null {
  const tickets = useMemo(() => buildRefinementTickets(plan), [plan])

  const ticketByKey = useMemo(() => {
    const m: Record<string, RefinementTicket> = {}
    for (const t of tickets) m[t.ticketKey] = t
    return m
  }, [tickets])

  // Per-ticket card deck. Stable while tickets list is stable.
  const cardsByKey = useMemo(() => {
    const out: Record<string, SuggestionCardModel[]> = {}
    for (const t of tickets) out[t.ticketKey] = buildCardsFor(t)
    return out
  }, [tickets])

  const [currentByKey, setCurrentByKey] = useState<Record<string, TicketFields>>({})
  const [cardStatusByKey, setCardStatusByKey] = useState<Record<string, Record<string, CardStatus>>>({})
  const [approvedKeys, setApprovedKeys] = useState<Set<string>>(new Set())
  const [index, setIndex] = useState(0)
  const [showDone, setShowDone] = useState(false)
  const [toast, setToast] = useState<string | null>(null)

  const toastTimerRef = useRef<number | null>(null)

  // (Re)initialize whenever the underlying plan / ticket list changes.
  useEffect(() => {
    const baseCurrent: Record<string, TicketFields> = {}
    const baseCardStatus: Record<string, Record<string, CardStatus>> = {}
    for (const t of tickets) {
      // Start from a copy of ORIGINAL so the user sees pristine ticket content
      // and applies Scope Cop suggestions card-by-card via Accept.
      baseCurrent[t.ticketKey] = cloneFields(t.original)
      const cardMap: Record<string, CardStatus> = {}
      for (const c of cardsByKey[t.ticketKey] ?? []) cardMap[c.id] = 'open'
      baseCardStatus[t.ticketKey] = cardMap
    }
    const draft = loadDraft(plan)
    if (draft) {
      for (const t of tickets) {
        const d = draft[t.ticketKey]
        if (d) {
          baseCurrent[t.ticketKey] = {
            title: d.title ?? baseCurrent[t.ticketKey].title,
            description: d.description ?? baseCurrent[t.ticketKey].description,
            acceptanceCriteria: Array.isArray(d.acceptanceCriteria)
              ? d.acceptanceCriteria.slice()
              : baseCurrent[t.ticketKey].acceptanceCriteria,
            storyPoints: d.storyPoints ?? baseCurrent[t.ticketKey].storyPoints,
          }
        }
      }
    }
    setCurrentByKey(baseCurrent)
    setCardStatusByKey(baseCardStatus)
    setApprovedKeys(new Set())
    setShowDone(false)
    // Jump to the first ticket that still has open suggestions; fall back to 0.
    const firstOpen = tickets.findIndex(t => (cardsByKey[t.ticketKey] ?? []).length > 0)
    setIndex(firstOpen >= 0 ? firstOpen : 0)
  }, [plan, tickets, cardsByKey])

  // ─── derived ──
  const total = tickets.length
  const ticket = total > 0 ? tickets[Math.min(index, total - 1)] : null
  const current = ticket ? currentByKey[ticket.ticketKey] : undefined
  const cards = ticket ? cardsByKey[ticket.ticketKey] ?? [] : []
  const cardStatus = ticket ? cardStatusByKey[ticket.ticketKey] ?? {} : {}

  const hasChanges = useMemo(() => {
    if (!ticket || !current) return false
    return !fieldsEqual(current, ticket.original)
  }, [ticket, current])

  const refinedCount = useMemo(() => {
    let n = 0
    for (const t of tickets) {
      const c = currentByKey[t.ticketKey]
      if (c && !fieldsEqual(c, t.original)) n++
    }
    return n
  }, [tickets, currentByKey])

  // ─── handlers ──
  const updateCurrent = useCallback(
    (key: string, next: TicketFields) => {
      setCurrentByKey(prev => ({ ...prev, [key]: next }))
    },
    [],
  )

  const acceptCard = useCallback(
    (card: SuggestionCardModel) => {
      setCardStatusByKey(prev => ({
        ...prev,
        [card.ticketKey]: { ...(prev[card.ticketKey] ?? {}), [card.id]: 'accepted' },
      }))
      setCurrentByKey(prev => {
        const cur = prev[card.ticketKey]
        if (!cur) return prev
        const next: TicketFields = cloneFields(cur)
        if (card.action === 'replace-title') next.title = String(card.after)
        else if (
          card.action === 'replace-description' ||
          card.action === 'set-description'
        )
          next.description = String(card.after)
        else if (card.action === 'add-ac') {
          if (!next.acceptanceCriteria.includes(String(card.after))) {
            next.acceptanceCriteria = [...next.acceptanceCriteria, String(card.after)]
          }
        } else if (card.action === 'set-points') {
          next.storyPoints = Number(card.after)
        }
        return { ...prev, [card.ticketKey]: next }
      })
    },
    [],
  )

  const ignoreCard = useCallback((card: SuggestionCardModel) => {
    setCardStatusByKey(prev => ({
      ...prev,
      [card.ticketKey]: { ...(prev[card.ticketKey] ?? {}), [card.id]: 'ignored' },
    }))
  }, [])

  const undoCard = useCallback(
    (card: SuggestionCardModel) => {
      const wasAccepted =
        (cardStatusByKey[card.ticketKey]?.[card.id] ?? 'open') === 'accepted'
      setCardStatusByKey(prev => ({
        ...prev,
        [card.ticketKey]: { ...(prev[card.ticketKey] ?? {}), [card.id]: 'open' },
      }))
      if (!wasAccepted) return
      setCurrentByKey(prev => {
        const cur = prev[card.ticketKey]
        const orig = ticketByKey[card.ticketKey]?.original
        if (!cur || !orig) return prev
        const next: TicketFields = cloneFields(cur)
        if (card.action === 'replace-title') next.title = orig.title
        else if (card.action === 'replace-description') next.description = orig.description
        else if (card.action === 'set-description') next.description = orig.description
        else if (card.action === 'add-ac') {
          next.acceptanceCriteria = next.acceptanceCriteria.filter(
            ac => ac !== String(card.after),
          )
        } else if (card.action === 'set-points') {
          next.storyPoints = orig.storyPoints
        }
        return { ...prev, [card.ticketKey]: next }
      })
    },
    [cardStatusByKey, ticketByKey],
  )

  const goTo = useCallback(
    (next: number) => {
      if (next < 0 || next >= total) return
      setIndex(next)
    },
    [total],
  )

  const approveAndAdvance = useCallback(() => {
    if (!ticket) return
    setApprovedKeys(prev => {
      const next = new Set(prev)
      next.add(ticket.ticketKey)
      return next
    })
    if (index >= total - 1) setShowDone(true)
    else setIndex(index + 1)
  }, [ticket, index, total])

  const revertCurrent = useCallback(() => {
    if (!ticket) return
    setCurrentByKey(prev => ({ ...prev, [ticket.ticketKey]: cloneFields(ticket.original) }))
    // Re-open every suggestion card on this ticket.
    setCardStatusByKey(prev => {
      const reset: Record<string, CardStatus> = {}
      for (const c of cardsByKey[ticket.ticketKey] ?? []) reset[c.id] = 'open'
      return { ...prev, [ticket.ticketKey]: reset }
    })
  }, [ticket, cardsByKey])

  const showToast = useCallback((msg: string) => {
    setToast(msg)
    if (toastTimerRef.current) window.clearTimeout(toastTimerRef.current)
    toastTimerRef.current = window.setTimeout(() => setToast(null), 2200)
  }, [])

  const saveProgress = useCallback(() => {
    try {
      const payload: DraftPayload = { savedAt: Date.now(), data: currentByKey }
      window.localStorage.setItem(planDraftKey(plan), JSON.stringify(payload))
      showToast('Progress saved')
    } catch {
      showToast('Could not save')
    }
  }, [plan, currentByKey, showToast])

  // Build CommitApproval[] from the approved set and hand to parent.
  const pushApprovals = useCallback(() => {
    const approvals: CommitApproval[] = []
    for (const key of approvedKeys) {
      const t = ticketByKey[key]
      const cur = currentByKey[key]
      if (!t) continue
      const approval: CommitApproval = {
        ticket_key: key,
        approved_at: new Date().toISOString(),
        fetched_updated_at: t.fetchedUpdatedAt ?? null,
        developer_id: t.developerId ?? null,
      }
      if (cur && !fieldsEqual(cur, t.original)) {
        const revision: CommitRevision = {
          title: cur.title,
          description: cur.description,
          acceptance_criteria: cur.acceptanceCriteria,
          story_points: cur.storyPoints ?? undefined,
        }
        approval.revision = revision
      }
      approvals.push(approval)
    }
    onCommit(approvals)
  }, [approvedKeys, ticketByKey, currentByKey, onCommit])

  const editConflict = useCallback(
    (key: string) => {
      const i = tickets.findIndex(t => t.ticketKey === key)
      if (i < 0) return
      setShowDone(false)
      setIndex(i)
    },
    [tickets],
  )

  // ─── keyboard ──
  useEffect(() => {
    if (!open) return
    function onKey(e: KeyboardEvent) {
      const target = e.target as HTMLElement | null
      const tag = target?.tagName
      const typing = tag === 'INPUT' || tag === 'TEXTAREA' || target?.isContentEditable
      if (e.key === 'Escape') {
        e.preventDefault()
        onClose()
        return
      }
      if (typing) return
      if (showDone) return
      if (e.key === 'ArrowRight') {
        e.preventDefault()
        goTo(index + 1)
      } else if (e.key === 'ArrowLeft') {
        e.preventDefault()
        goTo(index - 1)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose, goTo, index, showDone])

  // Cleanup any pending toast timer on unmount.
  useEffect(() => {
    return () => {
      if (toastTimerRef.current) window.clearTimeout(toastTimerRef.current)
    }
  }, [])

  if (!open) return null

  return (
    <>
      <style>{KEYFRAMES_CSS}</style>
      <div
        className="srf-overlay-fade"
        role="dialog"
        aria-modal="true"
        onMouseDown={e => {
          if (e.target === e.currentTarget) onClose()
        }}
        style={{
          position: 'fixed',
          inset: 0,
          zIndex: 1000,
          background: 'rgba(0,0,0,0.55)',
          backdropFilter: 'blur(3px)',
          WebkitBackdropFilter: 'blur(3px)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: 24,
          fontFamily: 'var(--font-sans)',
        }}
      >
        <div
          className="srf-modal-in"
          style={{
            width: '100%',
            maxWidth: 920,
            height: 'min(680px, 90vh)',
            background: 'var(--color-bg-elevated)',
            borderRadius: 14,
            overflow: 'hidden',
            display: 'flex',
            flexDirection: 'column',
            boxShadow: '0 24px 64px -12px rgba(0,0,0,0.4)',
            border: `1px solid var(--color-border)`,
          }}
        >
          {/* Header */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: '14px 20px',
              borderBottom: `1px solid var(--color-border)`,
              flexShrink: 0,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <div
                style={{
                  width: 24,
                  height: 24,
                  borderRadius: 6,
                  background: 'var(--color-text-primary)',
                  color: 'var(--color-bg-primary)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: 12,
                  fontWeight: 700,
                }}
              >
                O
              </div>
              <span
                style={{
                  fontSize: 13,
                  fontWeight: 600,
                  color: 'var(--color-text-primary)',
                }}
              >
                Scope Cop
              </span>
              <span style={{ color: 'var(--color-text-muted)' }}>·</span>
              <span style={{ fontSize: 13, color: 'var(--color-text-secondary)' }}>
                Review &amp; Refine
              </span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <button
                type="button"
                onClick={saveProgress}
                style={{
                  padding: '6px 12px',
                  borderRadius: 6,
                  background: 'transparent',
                  color: 'var(--color-text-secondary)',
                  border: `1px solid var(--color-border)`,
                  fontSize: 12,
                  fontWeight: 600,
                  cursor: 'pointer',
                }}
              >
                Save progress
              </button>
              <button
                type="button"
                onClick={onClose}
                aria-label="Close"
                style={{
                  width: 30,
                  height: 30,
                  borderRadius: 6,
                  background: 'transparent',
                  border: 'none',
                  color: 'var(--color-text-secondary)',
                  fontSize: 20,
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                ×
              </button>
            </div>
          </div>

          {showDone ? (
            <DoneScreen
              approvedCount={approvedKeys.size}
              refinedCount={refinedCount}
              isPushing={!!isPushing}
              pushResult={pushResult}
              onPush={pushApprovals}
              onClose={onClose}
              onEditConflict={editConflict}
            />
          ) : ticket && current ? (
            <>
              <ProgressRail
                total={total}
                index={index}
                approvedKeys={approvedKeys}
                ticketKeys={tickets.map(t => t.ticketKey)}
                onJump={goTo}
              />

              <div style={{ flex: 1, minHeight: 0 }}>
                <TicketSlide
                  key={ticket.ticketKey}
                  ticket={ticket}
                  current={current}
                  cards={cards}
                  cardStatus={cardStatus}
                  onChangeCurrent={next => updateCurrent(ticket.ticketKey, next)}
                  onAcceptCard={acceptCard}
                  onIgnoreCard={ignoreCard}
                  onUndoCard={undoCard}
                />
              </div>

              {/* Footer */}
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: 12,
                  padding: '14px 20px',
                  borderTop: `1px solid var(--color-border)`,
                  background: 'var(--color-bg-secondary)',
                  flexShrink: 0,
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <button
                    type="button"
                    onClick={approveAndAdvance}
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: 8,
                      height: 42,
                      padding: '0 20px',
                      background: 'var(--color-success)',
                      color: '#fff',
                      border: 'none',
                      borderRadius: 9,
                      fontSize: 14,
                      fontWeight: 600,
                      cursor: 'pointer',
                      boxShadow:
                        '0 1px 2px rgba(31,122,77,0.3), 0 6px 16px -6px rgba(31,122,77,0.5)',
                    }}
                  >
                    ✓ {index >= total - 1 ? 'Approve & Finish' : 'Approve & Next'}
                  </button>
                  {approvedKeys.has(ticket.ticketKey) && (
                    <span
                      style={{
                        fontSize: 12,
                        color: 'var(--color-success)',
                        fontWeight: 600,
                      }}
                    >
                      ✓ Approved
                    </span>
                  )}
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <button
                    type="button"
                    onClick={revertCurrent}
                    disabled={!hasChanges}
                    style={{
                      padding: '0 14px',
                      height: 42,
                      borderRadius: 9,
                      background: 'transparent',
                      color: hasChanges
                        ? 'var(--color-text-secondary)'
                        : 'var(--color-text-muted)',
                      border: 'none',
                      fontSize: 13,
                      fontWeight: 600,
                      cursor: hasChanges ? 'pointer' : 'default',
                      opacity: hasChanges ? 1 : 0.5,
                    }}
                  >
                    ↺ Revert to original
                  </button>
                  <button
                    type="button"
                    onClick={() => goTo(index - 1)}
                    disabled={index === 0}
                    style={{
                      height: 42,
                      padding: '0 18px',
                      background: 'var(--color-bg-elevated)',
                      color:
                        index === 0
                          ? 'var(--color-text-muted)'
                          : 'var(--color-text-primary)',
                      border: `1px solid var(--color-border)`,
                      borderRadius: 9,
                      fontSize: 14,
                      fontWeight: 600,
                      cursor: index === 0 ? 'default' : 'pointer',
                      opacity: index === 0 ? 0.5 : 1,
                    }}
                  >
                    ← Previous
                  </button>
                </div>
              </div>
            </>
          ) : (
            <div
              style={{
                flex: 1,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: 'var(--color-text-muted)',
                fontSize: 14,
              }}
            >
              No tickets in this plan.
            </div>
          )}
        </div>
      </div>

      {/* Toast */}
      {toast && (
        <div
          className="srf-toast-in"
          style={{
            position: 'fixed',
            bottom: 24,
            left: '50%',
            transform: 'translateX(-50%)',
            zIndex: 1100,
            background: 'var(--color-text-primary)',
            color: 'var(--color-bg-primary)',
            padding: '11px 18px',
            borderRadius: 9,
            fontSize: 13,
            fontWeight: 600,
            boxShadow: '0 8px 24px rgba(0,0,0,0.25)',
            fontFamily: 'var(--font-sans)',
          }}
        >
          ✓ {toast}
        </div>
      )}
    </>
  )
}

// ─── styles & keyframes ─────────────────────────────────────────────────────

const metaLabel: CSSProperties = {
  fontSize: 10,
  fontWeight: 700,
  color: 'var(--color-text-muted)',
  letterSpacing: '0.07em',
  textTransform: 'uppercase',
  marginBottom: 5,
}

const KEYFRAMES_CSS = `
@keyframes srfFadeIn { from { opacity: 0; } to { opacity: 1; } }
@keyframes srfScaleIn { from { opacity: 0; transform: translateY(8px) scale(0.99); } to { opacity: 1; transform: none; } }
@keyframes srfSlideIn { from { opacity: 0; transform: translateX(14px); } to { opacity: 1; transform: none; } }
@keyframes srfToastIn { from { opacity: 0; transform: translate(-50%, 10px); } to { opacity: 1; transform: translate(-50%, 0); } }
.srf-overlay-fade { animation: srfFadeIn 0.18s ease both; }
.srf-modal-in { animation: srfScaleIn 0.22s cubic-bezier(0.2,0.7,0.2,1) both; }
.srf-slide-in { animation: srfSlideIn 0.26s cubic-bezier(0.2,0.7,0.2,1) both; }
.srf-toast-in { animation: srfToastIn 0.2s ease both; }
`
