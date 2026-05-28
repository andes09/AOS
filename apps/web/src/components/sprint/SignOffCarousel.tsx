// apps/web/src/components/sprint/SignOffCarousel.tsx
// SB-11 / B9 — full-screen, one-ticket-per-screen approval carousel. The final
// step before pushing a refined plan to Jira. Session-scoped approval memory
// lives in internal React state; a ticket's approval is only valid while its
// approval timestamp is newer than the ticket's last edit.

import { useState, useEffect, useCallback, CSSProperties } from 'react'
import { Card, CardBody } from '../ui/Card'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { Alert } from '../ui/Alert'
import type { TicketFields, CommitConflict } from '../../types/inlineRefinement'

export interface SignOffTicket {
  ticketKey: string
  developerName: string
  reasoning: string                 // Sprint Brain reasoning, shown on each screen
  original: TicketFields
  current: TicketFields             // the revised content that will be pushed
  lastEditedAt: number | null       // ms epoch of the ticket's last edit in B8
}

export interface SignOffCarouselProps {
  tickets: SignOffTicket[]
  onClose: () => void                          // Esc / "Back to Triage" — preserves approvals
  onEditTicket: (ticketKey: string) => void    // "Go back to edit" → returns to modal with this ticket selected
  onPush: (approvedKeys: string[]) => void     // final screen "Push to Jira" → parent calls /commit
  isPushing?: boolean
  pushResult?: { committed: string[]; conflicts: CommitConflict[] } | null
}

// Hardcoded per the locked decision (Open Q3). Bulk-approve only renders when at
// least this many unapproved tickets remain from the current position.
const BULK_APPROVE_COUNT = 5

// A ticket's approval is valid only if it was approved strictly after its last
// edit. Editing in B8 (newer lastEditedAt) silently invalidates a prior approval.
function isApproved(ticket: SignOffTicket, approvedAt: number | undefined): boolean {
  if (approvedAt === undefined) return false
  return approvedAt > (ticket.lastEditedAt ?? 0)
}

const labelStyle: CSSProperties = {
  fontFamily: 'var(--font-sans)',
  fontSize: 'var(--text-xs)',
  fontWeight: 700,
  textTransform: 'uppercase',
  letterSpacing: '0.04em',
  color: 'var(--color-text-muted)',
  marginBottom: 4,
}

const fieldValueStyle: CSSProperties = {
  fontFamily: 'var(--font-sans)',
  fontSize: 'var(--text-sm)',
  color: 'var(--color-text-primary)',
  lineHeight: 1.5,
  whiteSpace: 'pre-wrap',
}

function FieldsView({ fields }: { fields: TicketFields }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div>
        <div style={labelStyle}>Title</div>
        <div style={{ ...fieldValueStyle, fontWeight: 600 }}>{fields.title || '—'}</div>
      </div>
      <div>
        <div style={labelStyle}>Description</div>
        <div style={fieldValueStyle}>{fields.description || '—'}</div>
      </div>
      <div>
        <div style={labelStyle}>Acceptance Criteria</div>
        {fields.acceptanceCriteria.length > 0 ? (
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {fields.acceptanceCriteria.map((ac, i) => (
              <li key={i} style={fieldValueStyle}>{ac}</li>
            ))}
          </ul>
        ) : (
          <div style={fieldValueStyle}>—</div>
        )}
      </div>
      <div>
        <div style={labelStyle}>Story Points</div>
        <div style={fieldValueStyle}>{fields.storyPoints ?? '—'}</div>
      </div>
    </div>
  )
}

export function SignOffCarousel({
  tickets,
  onClose,
  onEditTicket,
  onPush,
  isPushing,
  pushResult,
}: SignOffCarouselProps): JSX.Element {
  // Session approval memory: { ticketKey: approvedAtMs }.
  const [approvals, setApprovals] = useState<Record<string, number>>({})
  // index === tickets.length => final commit-summary screen.
  const [index, setIndex] = useState(0)

  const total = tickets.length
  const onSummary = index >= total

  // Esc closes (preserving approvals).
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.preventDefault()
        onClose()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  // Currently-valid approved keys (invalidation applied).
  const approvedKeys = tickets
    .filter(t => isApproved(t, approvals[t.ticketKey]))
    .map(t => t.ticketKey)

  // Advance from `from` to the next still-unapproved ticket, else the summary.
  const advanceFrom = useCallback(
    (from: number, pending: Record<string, number>) => {
      for (let i = from + 1; i < total; i++) {
        if (!isApproved(tickets[i], pending[tickets[i].ticketKey])) {
          setIndex(i)
          return
        }
      }
      setIndex(total)
    },
    [tickets, total],
  )

  const approveCurrent = useCallback(() => {
    if (onSummary) return
    const key = tickets[index].ticketKey
    const next = { ...approvals, [key]: Date.now() }
    setApprovals(next)
    advanceFrom(index, next)
  }, [onSummary, tickets, index, approvals, advanceFrom])

  // Approve the next N unapproved tickets from the current position, each with a
  // distinct timestamp (incrementing offset guarantees distinctness even when
  // Date.now() returns the same ms across the loop).
  const approveNextN = useCallback(
    (n: number) => {
      if (onSummary) return
      const next = { ...approvals }
      const base = Date.now()
      let stamped = 0
      let lastStampedIndex = index
      for (let i = index; i < total && stamped < n; i++) {
        const t = tickets[i]
        if (isApproved(t, next[t.ticketKey])) continue
        next[t.ticketKey] = base + stamped // distinct ms per ticket
        lastStampedIndex = i
        stamped++
      }
      setApprovals(next)
      advanceFrom(lastStampedIndex, next)
    },
    [onSummary, approvals, index, total, tickets, advanceFrom],
  )

  // Count unapproved tickets remaining from the current position (inclusive).
  const unapprovedRemaining = onSummary
    ? 0
    : tickets
        .slice(index)
        .filter(t => !isApproved(t, approvals[t.ticketKey])).length

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
    gap: 10,
    padding: '14px 24px',
    borderBottom: '1px solid var(--color-border)',
    flexShrink: 0,
  }

  const bodyStyle: CSSProperties = {
    flex: 1,
    overflowY: 'auto',
    padding: '24px',
    display: 'flex',
    justifyContent: 'center',
  }

  const footerStyle: CSSProperties = {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    padding: '14px 24px',
    borderTop: '1px solid var(--color-border)',
    flexShrink: 0,
  }

  // ---- Final commit-summary screen ----
  if (onSummary) {
    const conflicts = pushResult?.conflicts ?? []
    const committed = pushResult?.committed ?? []
    return (
      <div style={overlayStyle} role="dialog" aria-modal="true">
        <div style={headerStyle}>
          <span style={{ fontSize: 'var(--text-base)', fontWeight: 700, color: 'var(--color-text-primary)' }}>
            Sign-off summary
          </span>
          <div style={{ marginLeft: 'auto' }}>
            <Button variant="ghost" size="sm" onClick={onClose}>Back to Triage</Button>
          </div>
        </div>

        <div style={bodyStyle}>
          <div style={{ width: '100%', maxWidth: 640 }}>
            <Card>
              <CardBody>
                <div style={{ fontSize: 'var(--text-sm)', fontWeight: 700, color: 'var(--color-text-primary)', marginBottom: 8 }}>
                  {approvedKeys.length} ticket{approvedKeys.length === 1 ? '' : 's'} approved for push
                </div>
                {approvedKeys.length > 0 ? (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                    {approvedKeys.map(k => (
                      <Badge key={k} variant="success">{k}</Badge>
                    ))}
                  </div>
                ) : (
                  <div style={fieldValueStyle}>
                    No tickets are currently approved. Approve at least one ticket before pushing.
                  </div>
                )}
              </CardBody>
            </Card>

            {pushResult && (
              <div style={{ marginTop: 14, display: 'flex', flexDirection: 'column', gap: 10 }}>
                <Alert variant={conflicts.length > 0 ? 'warning' : 'success'} title="Push result">
                  {committed.length} pushed, {conflicts.length} conflict{conflicts.length === 1 ? '' : 's'}
                </Alert>
                {conflicts.length > 0 && (
                  <Card>
                    <CardBody>
                      <div style={{ ...labelStyle, color: 'var(--color-danger)' }}>Conflicts</div>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 6 }}>
                        {conflicts.map(c => (
                          <div key={c.ticket_key} style={{ display: 'flex', alignItems: 'flex-start', gap: 8 }}>
                            <Badge variant="danger">{c.ticket_key}</Badge>
                            <span style={fieldValueStyle}>{c.reason}</span>
                            <Button
                              variant="ghost"
                              size="sm"
                              style={{ marginLeft: 'auto' }}
                              onClick={() => onEditTicket(c.ticket_key)}
                            >
                              Go back to edit
                            </Button>
                          </div>
                        ))}
                      </div>
                    </CardBody>
                  </Card>
                )}
              </div>
            )}
          </div>
        </div>

        <div style={footerStyle}>
          {total > 0 && (
            <Button variant="ghost" onClick={() => setIndex(total - 1)} disabled={isPushing}>
              Back
            </Button>
          )}
          <div style={{ marginLeft: 'auto' }}>
            <Button
              variant="primary"
              onClick={() => onPush(approvedKeys)}
              disabled={isPushing || approvedKeys.length === 0}
            >
              {isPushing ? 'Pushing…' : 'Push to Jira'}
            </Button>
          </div>
        </div>
      </div>
    )
  }

  // ---- Per-ticket screen ----
  const ticket = tickets[index]
  const currentApproved = isApproved(ticket, approvals[ticket.ticketKey])

  return (
    <div style={overlayStyle} role="dialog" aria-modal="true">
      <div style={headerStyle}>
        <span style={{ fontSize: 'var(--text-sm)', fontWeight: 700, color: 'var(--color-text-secondary)' }}>
          Ticket {index + 1} of {total}
        </span>
        <span style={{ fontSize: 'var(--text-sm)', fontWeight: 700, color: 'var(--color-text-primary)' }}>
          {ticket.ticketKey}
        </span>
        <Badge variant="info">{ticket.developerName}</Badge>
        {currentApproved && <Badge variant="success">Approved</Badge>}
        <div style={{ marginLeft: 'auto' }}>
          <Button variant="ghost" size="sm" onClick={onClose}>Back to Triage</Button>
        </div>
      </div>

      <div style={bodyStyle}>
        <div style={{ width: '100%', maxWidth: 980, display: 'flex', flexDirection: 'column', gap: 16 }}>
          {ticket.reasoning && (
            <Alert variant="info" title="Sprint Brain reasoning">
              {ticket.reasoning}
            </Alert>
          )}
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
            <Card style={{ flex: '1 1 360px', minWidth: 280 }}>
              <CardBody>
                <div style={{ ...labelStyle, color: 'var(--color-text-secondary)', marginBottom: 12 }}>
                  Original
                </div>
                <FieldsView fields={ticket.original} />
              </CardBody>
            </Card>
            <Card style={{ flex: '1 1 360px', minWidth: 280, borderColor: 'var(--color-accent)' }}>
              <CardBody>
                <div style={{ ...labelStyle, color: 'var(--color-accent)', marginBottom: 12 }}>
                  Revised (will be pushed)
                </div>
                <FieldsView fields={ticket.current} />
              </CardBody>
            </Card>
          </div>
        </div>
      </div>

      <div style={footerStyle}>
        <Button variant="ghost" onClick={() => onEditTicket(ticket.ticketKey)}>
          Go back to edit
        </Button>
        {index > 0 && (
          <Button variant="ghost" onClick={() => setIndex(index - 1)}>
            Previous
          </Button>
        )}
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 10 }}>
          {unapprovedRemaining >= BULK_APPROVE_COUNT && (
            <Button variant="secondary" onClick={() => approveNextN(BULK_APPROVE_COUNT)}>
              Approve next {BULK_APPROVE_COUNT}
            </Button>
          )}
          <Button variant="primary" onClick={approveCurrent}>
            {currentApproved ? 'Re-approve' : 'Approve'}
          </Button>
        </div>
      </div>
    </div>
  )
}
