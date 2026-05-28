import { CSSProperties, ReactNode, useState } from 'react'
import { Button } from '../ui/Button'
import { Badge } from '../ui/Badge'
import type { TicketFields } from '../../types/inlineRefinement'

export interface TicketEditorPaneProps {
  original: TicketFields          // read-only, left column
  current: TicketFields           // editable, right column (controlled by parent)
  suggested: TicketFields         // Scope Cop's suggestion, for per-field reset
  onChange: (next: TicketFields) => void
}

// ---- Word-level diff -------------------------------------------------------
// A small token-by-token LCS over whitespace-split words. We build the
// classic LCS-length DP table, then backtrack to emit a sequence of tokens
// tagged 'same' | 'added' | 'removed'. Added words (present in `next` but not
// `prev`) render highlighted; removed words (present in `prev` but not `next`)
// render struck-through. Kept intentionally minimal — no fuzzy matching.

type DiffOp = 'same' | 'added' | 'removed'
interface DiffToken { op: DiffOp; text: string }

function tokenize(s: string): string[] {
  // Split on whitespace, keep non-empty tokens.
  return s.split(/\s+/).filter(t => t.length > 0)
}

function wordDiff(prev: string, next: string): DiffToken[] {
  const a = tokenize(prev) // "removed" source
  const b = tokenize(next) // "added" source
  const n = a.length
  const m = b.length

  // LCS length table: (n+1) x (m+1).
  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0))
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1])
    }
  }

  const tokens: DiffToken[] = []
  let i = 0
  let j = 0
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      tokens.push({ op: 'same', text: a[i] })
      i++
      j++
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      tokens.push({ op: 'removed', text: a[i] })
      i++
    } else {
      tokens.push({ op: 'added', text: b[j] })
      j++
    }
  }
  while (i < n) tokens.push({ op: 'removed', text: a[i++] })
  while (j < m) tokens.push({ op: 'added', text: b[j++] })
  return tokens
}

// ---- helpers ---------------------------------------------------------------

function arraysEqual(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false
  return true
}

const labelStyle: CSSProperties = {
  fontFamily: 'var(--font-sans)',
  fontSize: 'var(--text-xs)',
  fontWeight: 600,
  color: 'var(--color-text-muted)',
  textTransform: 'uppercase',
  letterSpacing: '0.04em',
}

const readOnlyValueStyle: CSSProperties = {
  fontFamily: 'var(--font-sans)',
  fontSize: 'var(--text-sm)',
  color: 'var(--color-text-secondary)',
  whiteSpace: 'pre-wrap',
  wordBreak: 'break-word',
}

const inputBase: CSSProperties = {
  fontFamily: 'var(--font-sans)',
  fontSize: 'var(--text-sm)',
  color: 'var(--color-text-primary)',
  background: 'var(--color-bg-tertiary)',
  borderRadius: 'var(--radius-sm)',
  padding: '5px 9px',
  outline: 'none',
  width: '100%',
  boxSizing: 'border-box',
}

function fieldBorder(changed: boolean): string {
  return changed ? '1px solid var(--color-accent)' : '1px solid var(--color-border-subtle)'
}

// Left accent stripe used to flag a changed editable field.
function changedAccent(changed: boolean): CSSProperties {
  return changed
    ? { borderLeft: '3px solid var(--color-accent)', paddingLeft: 9, marginLeft: -12 }
    : { borderLeft: '3px solid transparent', paddingLeft: 9, marginLeft: -12 }
}

function ChangedBadge({ show }: { show: boolean }) {
  if (!show) return null
  return <Badge variant="info">changed</Badge>
}

// ---- subcomponents ---------------------------------------------------------

function FieldHeader({
  label,
  changed,
  canReset,
  onReset,
}: {
  label: string
  changed: boolean
  canReset: boolean
  onReset: () => void
}) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
      <span style={labelStyle}>{label}</span>
      <ChangedBadge show={changed} />
      {canReset && (
        <Button
          size="sm"
          variant="ghost"
          onClick={onReset}
          style={{ marginLeft: 'auto', height: 20, padding: '2px 6px' }}
          title="Reset this field to Scope Cop's suggestion"
        >
          Reset to suggestion
        </Button>
      )}
    </div>
  )
}

function Column({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div
        style={{
          fontFamily: 'var(--font-sans)',
          fontSize: 'var(--text-xs)',
          fontWeight: 700,
          color: 'var(--color-text-secondary)',
          textTransform: 'uppercase',
          letterSpacing: '0.06em',
          paddingBottom: 6,
          borderBottom: '1px solid var(--color-border-subtle)',
        }}
      >
        {title}
      </div>
      {children}
    </div>
  )
}

// ---- main component --------------------------------------------------------

export function TicketEditorPane({
  original,
  current,
  suggested,
  onChange,
}: TicketEditorPaneProps): JSX.Element {
  const [focusedAcIndex, setFocusedAcIndex] = useState<number | null>(null)

  const titleChanged = current.title !== original.title
  const descChanged = current.description !== original.description
  const acChanged = !arraysEqual(current.acceptanceCriteria, original.acceptanceCriteria)
  const pointsChanged = current.storyPoints !== original.storyPoints

  // Per-field reset availability: only when the suggestion actually differs
  // from the current value (no-op resets are hidden).
  const canResetTitle = current.title !== suggested.title
  const canResetDesc = current.description !== suggested.description
  const canResetAc = !arraysEqual(current.acceptanceCriteria, suggested.acceptanceCriteria)
  const canResetPoints = current.storyPoints !== suggested.storyPoints

  const patch = (partial: Partial<TicketFields>) => onChange({ ...current, ...partial })

  const setAc = (index: number, value: string) => {
    const next = current.acceptanceCriteria.slice()
    next[index] = value
    patch({ acceptanceCriteria: next })
  }
  const addAc = () => patch({ acceptanceCriteria: [...current.acceptanceCriteria, ''] })
  const removeAc = (index: number) =>
    patch({ acceptanceCriteria: current.acceptanceCriteria.filter((_, i) => i !== index) })

  const descTokens = descChanged ? wordDiff(original.description, current.description) : null

  return (
    <div
      style={{
        display: 'flex',
        gap: 24,
        alignItems: 'stretch',
        fontFamily: 'var(--font-sans)',
      }}
    >
      {/* ---------- LEFT: original (read-only) ---------- */}
      <Column title="Original">
        <div>
          <div style={labelStyle}>Title</div>
          <div style={{ ...readOnlyValueStyle, marginTop: 4 }}>{original.title || '—'}</div>
        </div>
        <div>
          <div style={labelStyle}>Description</div>
          <div style={{ ...readOnlyValueStyle, marginTop: 4 }}>{original.description || '—'}</div>
        </div>
        <div>
          <div style={labelStyle}>Acceptance Criteria</div>
          {original.acceptanceCriteria.length === 0 ? (
            <div style={{ ...readOnlyValueStyle, marginTop: 4 }}>—</div>
          ) : (
            <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
              {original.acceptanceCriteria.map((ac, i) => (
                <li key={i} style={{ ...readOnlyValueStyle, marginBottom: 2 }}>
                  {ac}
                </li>
              ))}
            </ul>
          )}
        </div>
        <div>
          <div style={labelStyle}>Story Points</div>
          <div style={{ ...readOnlyValueStyle, marginTop: 4 }}>
            {original.storyPoints ?? '—'}
          </div>
        </div>
      </Column>

      {/* ---------- RIGHT: current (editable) ---------- */}
      <Column title="Refined">
        {/* Title */}
        <div style={changedAccent(titleChanged)}>
          <FieldHeader
            label="Title"
            changed={titleChanged}
            canReset={canResetTitle}
            onReset={() => patch({ title: suggested.title })}
          />
          <input
            value={current.title}
            onChange={e => patch({ title: e.target.value })}
            style={{ ...inputBase, border: fieldBorder(titleChanged), height: 32 }}
          />
        </div>

        {/* Description */}
        <div style={changedAccent(descChanged)}>
          <FieldHeader
            label="Description"
            changed={descChanged}
            canReset={canResetDesc}
            onReset={() => patch({ description: suggested.description })}
          />
          <textarea
            value={current.description}
            onChange={e => patch({ description: e.target.value })}
            rows={5}
            style={{
              ...inputBase,
              border: fieldBorder(descChanged),
              resize: 'vertical',
              minHeight: 80,
              lineHeight: 1.4,
            }}
          />
          {descTokens && (
            <div
              style={{
                marginTop: 6,
                padding: '6px 8px',
                background: 'var(--color-bg-secondary)',
                borderRadius: 'var(--radius-sm)',
                fontSize: 'var(--text-xs)',
                lineHeight: 1.5,
                color: 'var(--color-text-secondary)',
              }}
            >
              {descTokens.map((tok, i) => {
                if (tok.op === 'removed') {
                  return (
                    <span
                      key={i}
                      style={{
                        color: 'var(--color-danger)',
                        textDecoration: 'line-through',
                      }}
                    >
                      {tok.text}{' '}
                    </span>
                  )
                }
                if (tok.op === 'added') {
                  return (
                    <span
                      key={i}
                      style={{
                        color: 'var(--color-success)',
                        background: 'var(--color-success-bg)',
                        borderRadius: 2,
                      }}
                    >
                      {tok.text}{' '}
                    </span>
                  )
                }
                return <span key={i}>{tok.text}{' '}</span>
              })}
            </div>
          )}
        </div>

        {/* Acceptance Criteria */}
        <div style={changedAccent(acChanged)}>
          <FieldHeader
            label="Acceptance Criteria"
            changed={acChanged}
            canReset={canResetAc}
            onReset={() => patch({ acceptanceCriteria: suggested.acceptanceCriteria.slice() })}
          />
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {current.acceptanceCriteria.map((ac, i) => (
              <div key={i} style={{ display: 'flex', gap: 6, alignItems: 'flex-start' }}>
                <span
                  style={{
                    fontSize: 'var(--text-xs)',
                    color: 'var(--color-text-muted)',
                    paddingTop: 7,
                    minWidth: 14,
                    textAlign: 'right',
                  }}
                >
                  {i + 1}.
                </span>
                <input
                  value={ac}
                  onChange={e => setAc(i, e.target.value)}
                  onFocus={() => setFocusedAcIndex(i)}
                  onBlur={() => setFocusedAcIndex(prev => (prev === i ? null : prev))}
                  style={{
                    ...inputBase,
                    height: 30,
                    border:
                      focusedAcIndex === i
                        ? '1px solid var(--color-accent)'
                        : '1px solid var(--color-border-subtle)',
                  }}
                />
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => removeAc(i)}
                  style={{ height: 30, padding: '2px 8px' }}
                  title="Remove this criterion"
                >
                  ×
                </Button>
              </div>
            ))}
            <div>
              <Button
                size="sm"
                variant="ghost"
                onClick={addAc}
                style={{ color: 'var(--color-accent)' }}
              >
                + Add criterion
              </Button>
            </div>
          </div>
        </div>

        {/* Story Points */}
        <div style={changedAccent(pointsChanged)}>
          <FieldHeader
            label="Story Points"
            changed={pointsChanged}
            canReset={canResetPoints}
            onReset={() => patch({ storyPoints: suggested.storyPoints })}
          />
          <input
            type="number"
            min={0}
            value={current.storyPoints ?? ''}
            onChange={e => {
              const raw = e.target.value.trim()
              patch({ storyPoints: raw === '' ? null : Number(raw) })
            }}
            style={{
              ...inputBase,
              border: fieldBorder(pointsChanged),
              height: 32,
              width: 96,
            }}
          />
        </div>
      </Column>
    </div>
  )
}
