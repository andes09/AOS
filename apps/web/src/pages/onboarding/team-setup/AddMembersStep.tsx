import { useState } from 'react'
import { MemberDraft } from './types'
import { MemberCard } from './MemberCard'
import { MemberForm } from './MemberForm'

interface AddMembersStepProps {
  members: MemberDraft[]
  onAdd: (m: MemberDraft) => void
  onRemove: (i: number) => void
  onNext: () => void
  onBack: () => void
}

export function AddMembersStep({ members, onAdd, onRemove, onNext, onBack }: AddMembersStepProps) {
  const [showForm, setShowForm] = useState(members.length === 0)

  function handleSave(m: MemberDraft) {
    onAdd(m)
    setShowForm(false)
  }

  function handleCancel() {
    setShowForm(false)
  }

  const canNext = members.length > 0

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <div>
          <h2 style={{
            fontSize: 'var(--text-xl)',
            fontWeight: 700,
            color: 'var(--color-text-primary)',
            fontFamily: 'var(--font-sans)',
            margin: '0 0 4px',
            letterSpacing: '-0.01em',
          }}>
            Add team members
          </h2>
          <p style={{
            fontSize: 'var(--text-sm)',
            color: 'var(--color-text-muted)',
            fontFamily: 'var(--font-sans)',
            margin: 0,
          }}>
            Profiles power Sprint Brain&rsquo;s assignment intelligence.
          </p>
        </div>
        {members.length > 0 && (
          <span style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 5,
            background: '#e8f5ee',
            color: 'var(--color-success)',
            border: '1px solid #b7dfcb',
            borderRadius: 20,
            padding: '3px 10px',
            fontSize: 'var(--text-xs)',
            fontFamily: 'var(--font-sans)',
            fontWeight: 600,
            marginLeft: 'auto',
          }}>
            <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
              <path d="M1.5 5L4 7.5L8.5 2.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            {members.length} added
          </span>
        )}
      </div>

      {/* Member list */}
      {members.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {members.map((m, i) => (
            <MemberCard key={i} member={m} index={i} onRemove={onRemove} />
          ))}
        </div>
      )}

      {/* Form */}
      {showForm && (
        <MemberForm
          onSave={handleSave}
          onCancel={handleCancel}
          showCancel={members.length > 0}
        />
      )}

      {/* Add another button */}
      {!showForm && (
        <button
          type="button"
          onClick={() => setShowForm(true)}
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 6,
            padding: '12px',
            border: '1.5px dashed var(--color-border)',
            borderRadius: 'var(--radius-lg)',
            background: 'transparent',
            color: 'var(--color-text-muted)',
            fontFamily: 'var(--font-sans)',
            fontSize: 'var(--text-sm)',
            fontWeight: 500,
            cursor: 'pointer',
            transition: 'border-color 0.12s, color 0.12s',
          }}
          onMouseEnter={e => {
            const el = e.currentTarget as HTMLElement
            el.style.borderColor = 'var(--color-accent)'
            el.style.color = 'var(--color-accent)'
          }}
          onMouseLeave={e => {
            const el = e.currentTarget as HTMLElement
            el.style.borderColor = 'var(--color-border)'
            el.style.color = 'var(--color-text-muted)'
          }}
        >
          <span style={{ fontSize: 16, lineHeight: 1 }}>+</span>
          {members.length === 0 ? 'Add member' : 'Add another member'}
        </button>
      )}

      {/* Footer nav */}
      <div style={{ display: 'flex', gap: 10, paddingTop: 4 }}>
        <button
          type="button"
          onClick={onBack}
          style={{
            padding: '8px 14px',
            fontSize: 'var(--text-sm)',
            fontFamily: 'var(--font-sans)',
            fontWeight: 500,
            border: '1px solid var(--color-border)',
            borderRadius: 'var(--radius-md)',
            background: 'transparent',
            color: 'var(--color-text-secondary)',
            cursor: 'pointer',
          }}
        >
          ← Back
        </button>
        <button
          type="button"
          onClick={() => { if (canNext) onNext() }}
          disabled={!canNext}
          style={{
            padding: '8px 20px',
            fontSize: 'var(--text-sm)',
            fontFamily: 'var(--font-sans)',
            fontWeight: 600,
            border: 'none',
            borderRadius: 'var(--radius-md)',
            background: canNext ? 'var(--color-accent)' : 'var(--color-border)',
            color: canNext ? '#ffffff' : 'var(--color-text-muted)',
            cursor: canNext ? 'pointer' : 'not-allowed',
            transition: 'background 0.12s',
          }}
        >
          Review team →
        </button>
      </div>
    </div>
  )
}
