import { useState } from 'react'
import { Card, CardBody } from '../ui/Card'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import type { BadgeVariant } from '../ui/Badge'
import type { AnalyzeResponse, TicketAnalysisResult } from '../../types/scopeCop'

interface Props {
  response: AnalyzeResponse
  onReanalyze: () => void
  isPending?: boolean
}

const STATUS_VARIANT: Record<TicketAnalysisResult['status'], BadgeVariant> = {
  ready:      'success',
  needs_work: 'warning',
  blocked:    'danger',
}

const STATUS_LABELS: Record<TicketAnalysisResult['status'], string> = {
  ready:      'Ready',
  needs_work: 'Needs Work',
  blocked:    'Blocked',
}

function scoreColor(score: number): string {
  if (score >= 80) return 'var(--color-success)'
  if (score >= 50) return 'var(--color-warning)'
  return 'var(--color-danger)'
}

function TicketRow({ ticket }: { ticket: TicketAnalysisResult }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div style={{ borderBottom: '1px solid var(--color-border-subtle)', padding: '6px 0' }}>
      <div
        onClick={() => setExpanded(e => !e)}
        style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}
      >
        <span style={{
          fontFamily: 'var(--font-sans)',
          fontSize: 'var(--text-xs)',
          fontWeight: 700,
          color: scoreColor(ticket.readinessScore),
          background: 'var(--color-bg-secondary)',
          borderRadius: 'var(--radius-sm)',
          padding: '2px 6px',
          minWidth: 32,
          textAlign: 'center',
        }}>
          {ticket.readinessScore}
        </span>
        <Badge variant={STATUS_VARIANT[ticket.status]}>{STATUS_LABELS[ticket.status]}</Badge>
        <span style={{ fontFamily: 'var(--font-sans)', fontSize: 'var(--text-xs)', color: 'var(--color-text-secondary)', fontWeight: 600 }}>
          {ticket.ticketKey}
        </span>
        <span style={{ fontFamily: 'var(--font-sans)', fontSize: 'var(--text-xs)', color: 'var(--color-text-primary)', flex: 1 }}>
          {ticket.ticketTitle}
        </span>
        <span style={{ color: 'var(--color-text-muted)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-xs)' }}>
          {expanded ? '▲' : '▼'}
        </span>
      </div>

      {expanded && (
        <div style={{ marginTop: 8, paddingLeft: 12 }}>
          {ticket.issues.length > 0 && (
            <div style={{ marginBottom: 6 }}>
              <div style={{ fontFamily: 'var(--font-sans)', fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--color-danger)', marginBottom: 2 }}>Issues</div>
              <ul style={{ margin: 0, paddingLeft: 16 }}>
                {ticket.issues.map((issue, i) => (
                  <li key={i} style={{ fontFamily: 'var(--font-sans)', fontSize: 'var(--text-xs)', color: 'var(--color-danger)', marginBottom: 2 }}>{issue}</li>
                ))}
              </ul>
            </div>
          )}
          {ticket.suggestions.length > 0 && (
            <div>
              <div style={{ fontFamily: 'var(--font-sans)', fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--color-success)', marginBottom: 2 }}>Suggestions</div>
              <ul style={{ margin: 0, paddingLeft: 16 }}>
                {ticket.suggestions.map((s, i) => (
                  <li key={i} style={{ fontFamily: 'var(--font-sans)', fontSize: 'var(--text-xs)', color: 'var(--color-success)', marginBottom: 2 }}>{s}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export function ScopeCopPanel({ response, onReanalyze, isPending }: Props) {
  const { summary, results } = response

  return (
    <Card style={{ marginBottom: 12 }}>
      <CardBody>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10, flexWrap: 'wrap' }}>
          <span style={{ fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)', fontWeight: 700, color: 'var(--color-text-primary)', marginRight: 4 }}>
            Scope Check
          </span>
          <Badge variant="success">{summary.readyCount} Ready</Badge>
          <Badge variant="warning">{summary.needsWorkCount} Needs Work</Badge>
          <Badge variant="danger">{summary.blockedCount} Blocked</Badge>
          <div style={{ marginLeft: 'auto' }}>
            <Button size="sm" variant="ghost" onClick={onReanalyze} disabled={isPending}>
              {isPending ? 'Analyzing...' : 'Re-analyze'}
            </Button>
          </div>
        </div>
        <div>
          {results.map(ticket => (
            <TicketRow key={ticket.ticketKey} ticket={ticket} />
          ))}
        </div>
      </CardBody>
    </Card>
  )
}
