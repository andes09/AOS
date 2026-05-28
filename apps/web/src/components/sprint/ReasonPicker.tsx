/**
 * Override reason picker (M8a).
 *
 * Shown when a lead reassigns / removes / adds a ticket on a sprint plan.
 * The reason is skippable — saving without a chosen chip is allowed and the
 * PATCH endpoint accepts `reasonCode: null`.
 *
 * A one-time tooltip nudges the user to add a reason on their first 3
 * overrides (localStorage-backed; cap at 3).
 */
import { useEffect, useState } from 'react'
import { useApi } from '../../lib/api'

export type OverrideAction = 'reassign' | 'remove' | 'add'
export type OverrideReason =
  | 'skill_fit'
  | 'capacity'
  | 'mentorship'
  | 'pto'
  | 'priority_change'
  | 'other'

const REASON_OPTIONS: { code: OverrideReason; label: string }[] = [
  { code: 'skill_fit',       label: 'Skill fit' },
  { code: 'capacity',        label: 'Capacity' },
  { code: 'mentorship',      label: 'Mentorship' },
  { code: 'pto',             label: 'PTO' },
  { code: 'priority_change', label: 'Priority change' },
  { code: 'other',           label: 'Other' },
]

const TOOLTIP_KEY = 'aos_override_tooltip_shown_count'
const TOOLTIP_CAP = 3

interface ReasonPickerProps {
  sprintId: string
  ticketId: string
  /** When action is 'remove', new_developer_id is ignored server-side. */
  newDeveloperId: string | null
  action: OverrideAction
  onClose: () => void
  onSaved?: () => void
}

export interface PatchAssignmentResponse {
  ticketId: string
  sprintId: string
  assigneeId: string | null
  overrideId: string
}

export function ReasonPicker({
  sprintId, ticketId, newDeveloperId, action, onClose, onSaved,
}: ReasonPickerProps) {
  const api = useApi()
  const [selected, setSelected] = useState<OverrideReason | null>(null)
  const [text, setText] = useState('')
  const [showTooltip, setShowTooltip] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    // One-time nudge on the user's first 3 overrides.
    try {
      const raw = window.localStorage.getItem(TOOLTIP_KEY)
      const count = raw ? Math.max(0, parseInt(raw, 10) || 0) : 0
      if (count < TOOLTIP_CAP) setShowTooltip(true)
    } catch {
      // localStorage unavailable — fail open (no tooltip).
    }
  }, [])

  async function save(skip = false) {
    setSaving(true)
    setError(null)
    try {
      await api.patch<PatchAssignmentResponse>(
        `/api/sprints/${sprintId}/assignments/${ticketId}`,
        {
          newDeveloperId: action === 'remove' ? null : newDeveloperId,
          action,
          reasonCode: skip ? null : selected,
          reasonText: skip ? null : (text.trim() || null),
        },
      )
      // Bump tooltip count regardless of skip — the user has seen it.
      try {
        const raw = window.localStorage.getItem(TOOLTIP_KEY)
        const count = raw ? Math.max(0, parseInt(raw, 10) || 0) : 0
        if (count < TOOLTIP_CAP) {
          window.localStorage.setItem(TOOLTIP_KEY, String(count + 1))
        }
      } catch {
        // ignore
      }
      onSaved?.()
      onClose()
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to save override'
      setError(msg)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.35)',
        zIndex: 200,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      <div
        onClick={e => e.stopPropagation()}
        role="dialog"
        aria-label="Override reason"
        style={{
          width: 360,
          maxWidth: '92vw',
          background: 'var(--color-bg-primary)',
          border: '1px solid var(--color-border)',
          borderRadius: 'var(--radius-md)',
          padding: 16,
          boxShadow: '0 12px 32px rgba(0,0,0,0.2)',
          fontFamily: 'var(--font-sans)',
        }}
      >
        <div style={{
          color: 'var(--color-text-primary)',
          fontSize: 'var(--text-sm)',
          fontWeight: 600,
          marginBottom: showTooltip ? 4 : 10,
        }}>
          Why is this changing?
        </div>

        {showTooltip && (
          <div style={{
            color: 'var(--color-text-muted)',
            fontSize: 'var(--text-xs)',
            marginBottom: 10,
            fontStyle: 'italic',
          }}>
            Add a reason to help Sprint Brain learn.
          </div>
        )}

        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 12 }}>
          {REASON_OPTIONS.map(opt => {
            const active = selected === opt.code
            return (
              <button
                key={opt.code}
                type="button"
                onClick={() => setSelected(active ? null : opt.code)}
                style={{
                  padding: '4px 10px',
                  borderRadius: 9999,
                  border: `1px solid ${active ? 'var(--color-accent)' : 'var(--color-border)'}`,
                  background: active ? 'var(--color-accent-subtle)' : 'transparent',
                  color: active ? 'var(--color-accent)' : 'var(--color-text-secondary)',
                  fontSize: 'var(--text-xs)',
                  fontWeight: 600,
                  cursor: 'pointer',
                }}
              >
                {opt.label}
              </button>
            )
          })}
        </div>

        <textarea
          value={text}
          onChange={e => setText(e.target.value)}
          rows={2}
          placeholder="Optional note"
          style={{
            width: '100%',
            boxSizing: 'border-box',
            padding: 8,
            borderRadius: 'var(--radius-sm)',
            border: '1px solid var(--color-border)',
            background: 'var(--color-bg-secondary)',
            color: 'var(--color-text-primary)',
            fontFamily: 'var(--font-sans)',
            fontSize: 'var(--text-xs)',
            resize: 'vertical',
            marginBottom: 12,
          }}
        />

        {error && (
          <div style={{
            color: 'var(--color-danger)',
            fontSize: 'var(--text-xs)',
            marginBottom: 8,
          }}>
            {error}
          </div>
        )}

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <button
            type="button"
            onClick={() => save(true)}
            disabled={saving}
            style={{
              padding: '6px 12px',
              borderRadius: 'var(--radius-sm)',
              border: '1px solid var(--color-border)',
              background: 'transparent',
              color: 'var(--color-text-secondary)',
              fontSize: 'var(--text-xs)',
              fontWeight: 600,
              cursor: saving ? 'wait' : 'pointer',
            }}
          >
            Skip
          </button>
          <button
            type="button"
            onClick={() => save(false)}
            disabled={saving}
            style={{
              padding: '6px 12px',
              borderRadius: 'var(--radius-sm)',
              border: 'none',
              background: 'var(--color-accent)',
              color: 'var(--color-bg-primary, #fff)',
              fontSize: 'var(--text-xs)',
              fontWeight: 600,
              cursor: saving ? 'wait' : 'pointer',
            }}
          >
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  )
}
