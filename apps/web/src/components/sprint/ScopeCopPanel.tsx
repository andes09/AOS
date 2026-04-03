import { useState } from 'react'
import type { AnalyzeResponse, TicketAnalysisResult } from '../../types/scopeCop'

interface Props {
  response: AnalyzeResponse
  onReanalyze: () => void
  isPending?: boolean
}

const STATUS_COLORS: Record<TicketAnalysisResult['status'], string> = {
  ready: '#22c55e',
  needs_work: '#f59e0b',
  blocked: '#ef4444',
}

const STATUS_LABELS: Record<TicketAnalysisResult['status'], string> = {
  ready: 'Ready',
  needs_work: 'Needs Work',
  blocked: 'Blocked',
}

function scoreColor(score: number): string {
  if (score >= 80) return '#22c55e'
  if (score >= 50) return '#f59e0b'
  return '#ef4444'
}

function TicketRow({ ticket }: { ticket: TicketAnalysisResult }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div style={{ borderBottom: '1px solid #2d3148', padding: '0.5rem 0' }}>
      <div
        onClick={() => setExpanded(e => !e)}
        style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}
      >
        <span style={{
          fontSize: 11,
          fontWeight: 700,
          color: scoreColor(ticket.readinessScore),
          background: '#0f1117',
          borderRadius: 4,
          padding: '2px 6px',
          minWidth: 32,
          textAlign: 'center',
        }}>
          {ticket.readinessScore}
        </span>
        <span style={{
          fontSize: 11,
          fontWeight: 600,
          color: STATUS_COLORS[ticket.status],
          background: '#0f1117',
          borderRadius: 4,
          padding: '2px 6px',
        }}>
          {STATUS_LABELS[ticket.status]}
        </span>
        <span style={{ fontSize: 12, color: '#94a3b8', fontWeight: 600 }}>{ticket.ticketKey}</span>
        <span style={{ fontSize: 12, color: '#cbd5e1', flex: 1 }}>{ticket.ticketTitle}</span>
        <span style={{ fontSize: 11, color: '#475569' }}>{expanded ? '▲' : '▼'}</span>
      </div>

      {expanded && (
        <div style={{ marginTop: 8, paddingLeft: 12 }}>
          {ticket.issues.length > 0 && (
            <div style={{ marginBottom: 6 }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: '#ef4444', marginBottom: 2 }}>Issues</div>
              <ul style={{ margin: 0, paddingLeft: 16 }}>
                {ticket.issues.map((issue, i) => (
                  <li key={i} style={{ fontSize: 11, color: '#f87171', marginBottom: 2 }}>{issue}</li>
                ))}
              </ul>
            </div>
          )}
          {ticket.suggestions.length > 0 && (
            <div>
              <div style={{ fontSize: 11, fontWeight: 600, color: '#22c55e', marginBottom: 2 }}>Suggestions</div>
              <ul style={{ margin: 0, paddingLeft: 16 }}>
                {ticket.suggestions.map((s, i) => (
                  <li key={i} style={{ fontSize: 11, color: '#86efac', marginBottom: 2 }}>{s}</li>
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
    <div style={{ background: '#1e2030', borderRadius: 8, padding: '1rem', marginBottom: 12 }}>
      {/* Summary bar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 13, fontWeight: 700, color: '#e2e8f0', marginRight: 4 }}>Scope Analysis</span>
        <span style={{
          fontSize: 12, fontWeight: 600, color: '#22c55e',
          background: '#052e16', borderRadius: 12, padding: '2px 10px',
        }}>
          {summary.readyCount} Ready
        </span>
        <span style={{
          fontSize: 12, fontWeight: 600, color: '#f59e0b',
          background: '#1c1100', borderRadius: 12, padding: '2px 10px',
        }}>
          {summary.needsWorkCount} Needs Work
        </span>
        <span style={{
          fontSize: 12, fontWeight: 600, color: '#ef4444',
          background: '#1f0606', borderRadius: 12, padding: '2px 10px',
        }}>
          {summary.blockedCount} Blocked
        </span>
        <button
          onClick={onReanalyze}
          disabled={isPending}
          style={{
            marginLeft: 'auto',
            fontSize: 12,
            fontWeight: 600,
            color: isPending ? '#475569' : '#6366f1',
            background: 'transparent',
            border: `1px solid ${isPending ? '#2d3148' : '#6366f1'}`,
            borderRadius: 6,
            padding: '3px 10px',
            cursor: isPending ? 'default' : 'pointer',
          }}
        >
          {isPending ? 'Analyzing...' : 'Re-analyze'}
        </button>
      </div>

      {/* Per-ticket list */}
      <div>
        {results.map(ticket => (
          <TicketRow key={ticket.ticketKey} ticket={ticket} />
        ))}
      </div>
    </div>
  )
}
