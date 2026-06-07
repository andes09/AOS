import { MemberDraft } from './types'
import { ROLES, MEETING_HOURS } from './data'
import { MemberAvatar } from './MemberAvatar'

interface MemberCardProps {
  member: MemberDraft
  onRemove?: (i: number) => void
  index: number
  readOnly?: boolean
}

export function MemberCard({ member, onRemove, index, readOnly }: MemberCardProps) {
  const roleLabel =
    member.role === 'custom'
      ? member.customRole || 'Custom'
      : ROLES.find(r => r.id === member.role)?.label ?? member.role

  const meetingLabel =
    MEETING_HOURS.find(m => m.id === member.meetings)?.label ?? member.meetings

  const shownStrengths = member.strengths.slice(0, 3)
  const extra = member.strengths.length - 3

  return (
    <div style={{
      display: 'flex',
      alignItems: 'flex-start',
      gap: 12,
      padding: '12px 14px',
      background: '#ffffff',
      border: '1px solid var(--color-border)',
      borderRadius: 'var(--radius-lg)',
    }}>
      <MemberAvatar name={member.name} size={38} />

      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
          <span style={{
            fontSize: 'var(--text-base)',
            fontWeight: 600,
            color: 'var(--color-text-primary)',
            fontFamily: 'var(--font-sans)',
          }}>
            {member.name}
          </span>
        </div>

        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 4, alignItems: 'center' }}>
          {roleLabel && (
            <span style={{
              fontSize: 'var(--text-xs)',
              color: 'var(--color-accent)',
              background: 'rgba(12,102,228,0.08)',
              borderRadius: 'var(--radius-sm)',
              padding: '1px 6px',
              fontFamily: 'var(--font-sans)',
              fontWeight: 500,
            }}>
              {roleLabel}
            </span>
          )}
          <span style={{
            fontSize: 'var(--text-xs)',
            color: 'var(--color-text-secondary)',
            fontFamily: 'var(--font-sans)',
          }}>
            {member.capacity} h/wk
          </span>
          <span style={{
            fontSize: 'var(--text-xs)',
            color: 'var(--color-text-muted)',
            fontFamily: 'var(--font-sans)',
          }}>
            · {meetingLabel} meetings
          </span>
        </div>

        {member.strengths.length > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 6 }}>
            {shownStrengths.map(s => (
              <span key={s} style={{
                fontSize: 'var(--text-xs)',
                color: 'var(--color-text-secondary)',
                background: 'var(--color-bg-secondary)',
                border: '1px solid var(--color-border)',
                borderRadius: 'var(--radius-sm)',
                padding: '1px 6px',
                fontFamily: 'var(--font-sans)',
              }}>
                {s}
              </span>
            ))}
            {extra > 0 && (
              <span style={{
                fontSize: 'var(--text-xs)',
                color: 'var(--color-text-muted)',
                fontFamily: 'var(--font-sans)',
                padding: '1px 0',
              }}>
                +{extra} more
              </span>
            )}
          </div>
        )}
      </div>

      {!readOnly && onRemove && (
        <button
          type="button"
          onClick={() => onRemove(index)}
          style={{
            background: 'none',
            border: 'none',
            cursor: 'pointer',
            color: 'var(--color-text-muted)',
            fontSize: 16,
            padding: '2px 4px',
            lineHeight: 1,
            borderRadius: 'var(--radius-sm)',
            flexShrink: 0,
          }}
          title="Remove member"
        >
          ×
        </button>
      )}
    </div>
  )
}
