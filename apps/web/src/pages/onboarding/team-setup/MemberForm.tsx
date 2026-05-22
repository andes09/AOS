import { useState } from 'react'
import { MemberDraft, BLANK_MEMBER } from './types'
import { ROLES, STRENGTHS, SENIORITY, MEETING_HOURS } from './data'
import { MultiSelect } from './MultiSelect'

interface MemberFormProps {
  onSave: (m: MemberDraft) => void
  onCancel: () => void
  showCancel: boolean
}

const ENGINEERING_ROLES = ROLES.filter(r => r.group === 'Engineering')
const AGILE_ROLES = ROLES.filter(r => r.group === 'Agile')

const inputStyle = {
  width: '100%',
  height: 36,
  border: '1px solid var(--color-border)',
  borderRadius: 'var(--radius-md)',
  padding: '0 10px',
  fontSize: 'var(--text-sm)' as const,
  color: 'var(--color-text-primary)' as const,
  fontFamily: 'var(--font-sans)' as const,
  background: 'var(--color-bg-primary)' as const,
  outline: 'none',
  boxSizing: 'border-box' as const,
}

const labelStyle = {
  display: 'block' as const,
  fontSize: 'var(--text-sm)' as const,
  fontWeight: 600 as const,
  color: 'var(--color-text-primary)' as const,
  fontFamily: 'var(--font-sans)' as const,
  marginBottom: 6,
}

function RoleButton({ label, selected, onClick }: { label: string; selected: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        padding: '6px 10px',
        fontSize: 'var(--text-xs)',
        fontFamily: 'var(--font-sans)',
        fontWeight: selected ? 600 : 400,
        border: `1.5px solid ${selected ? 'var(--color-accent)' : 'var(--color-border)'}`,
        borderRadius: 'var(--radius-md)',
        background: selected ? 'rgba(12,102,228,0.08)' : 'transparent',
        color: selected ? 'var(--color-accent)' : 'var(--color-text-secondary)',
        cursor: 'pointer',
        transition: 'all 0.12s',
        whiteSpace: 'nowrap',
      }}
    >
      {label}
    </button>
  )
}

export function MemberForm({ onSave, onCancel, showCancel }: MemberFormProps) {
  const [draft, setDraft] = useState<MemberDraft>({ ...BLANK_MEMBER })
  const [showCustomRoleInput, setShowCustomRoleInput] = useState(false)

  function set<K extends keyof MemberDraft>(key: K, value: MemberDraft[K]) {
    setDraft(d => ({ ...d, [key]: value }))
  }

  function handleRoleClick(id: string) {
    if (id === draft.role) {
      set('role', '')
    } else {
      set('role', id)
    }
    if (showCustomRoleInput) setShowCustomRoleInput(false)
  }

  function handleCustomRoleToggle() {
    setShowCustomRoleInput(v => !v)
    if (!showCustomRoleInput) {
      set('role', 'custom')
    } else {
      set('role', '')
      set('customRole', '')
    }
  }

  const canSave = draft.name.trim() !== '' && (draft.role !== '' && (draft.role !== 'custom' || draft.customRole.trim() !== ''))

  return (
    <div style={{
      border: '1px solid var(--color-border)',
      borderRadius: 'var(--radius-lg)',
      padding: 20,
      background: '#f0f2f5',
      display: 'flex',
      flexDirection: 'column',
      gap: 18,
    }}>
      {/* Name + Email */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <div>
          <label style={labelStyle}>Full name</label>
          <input
            style={inputStyle}
            placeholder="Alex Johnson"
            value={draft.name}
            onChange={e => set('name', e.target.value)}
          />
        </div>
        <div>
          <label style={labelStyle}>Email <span style={{ fontWeight: 400, color: 'var(--color-text-muted)' }}>— optional</span></label>
          <input
            style={inputStyle}
            type="email"
            placeholder="alex@company.com"
            value={draft.email}
            onChange={e => set('email', e.target.value)}
          />
        </div>
      </div>

      {/* Role */}
      <div>
        <label style={labelStyle}>Role</label>

        <div style={{ marginBottom: 8 }}>
          <div style={{
            fontSize: 'var(--text-xs)',
            color: 'var(--color-text-muted)',
            fontFamily: 'var(--font-sans)',
            marginBottom: 6,
            textTransform: 'uppercase',
            letterSpacing: '0.05em',
            fontWeight: 600,
          }}>Engineering</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(120px, 1fr))', gap: 6 }}>
            {ENGINEERING_ROLES.map(r => (
              <RoleButton
                key={r.id}
                label={r.label}
                selected={draft.role === r.id}
                onClick={() => handleRoleClick(r.id)}
              />
            ))}
          </div>
        </div>

        <div style={{ marginBottom: 8 }}>
          <div style={{
            fontSize: 'var(--text-xs)',
            color: 'var(--color-text-muted)',
            fontFamily: 'var(--font-sans)',
            marginBottom: 6,
            textTransform: 'uppercase',
            letterSpacing: '0.05em',
            fontWeight: 600,
          }}>Agile</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(120px, 1fr))', gap: 6 }}>
            {AGILE_ROLES.map(r => (
              <RoleButton
                key={r.id}
                label={r.label}
                selected={draft.role === r.id}
                onClick={() => handleRoleClick(r.id)}
              />
            ))}
          </div>
        </div>

        <div>
          <div style={{
            fontSize: 'var(--text-xs)',
            color: 'var(--color-text-muted)',
            fontFamily: 'var(--font-sans)',
            marginBottom: 6,
            textTransform: 'uppercase',
            letterSpacing: '0.05em',
            fontWeight: 600,
          }}>Custom</div>
          {!showCustomRoleInput ? (
            <button
              type="button"
              onClick={handleCustomRoleToggle}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 4,
                padding: '6px 12px',
                fontSize: 'var(--text-xs)',
                fontFamily: 'var(--font-sans)',
                fontWeight: 500,
                border: '1.5px dashed var(--color-border)',
                borderRadius: 'var(--radius-md)',
                background: 'transparent',
                color: 'var(--color-text-muted)',
                cursor: 'pointer',
              }}
            >
              <span>+ Add custom role</span>
            </button>
          ) : (
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <input
                style={{ ...inputStyle, flex: 1 }}
                placeholder="e.g. ML Engineer"
                value={draft.customRole}
                onChange={e => set('customRole', e.target.value)}
                autoFocus
              />
              <button
                type="button"
                onClick={handleCustomRoleToggle}
                style={{
                  background: 'none',
                  border: 'none',
                  cursor: 'pointer',
                  color: 'var(--color-text-muted)',
                  fontSize: 16,
                  padding: '4px',
                  lineHeight: 1,
                }}
              >×</button>
            </div>
          )}
        </div>
      </div>

      {/* Strengths */}
      <MultiSelect
        label="Domain strengths"
        note="— up to 5"
        placeholder="Search strengths…"
        options={STRENGTHS}
        selected={draft.strengths}
        onChange={v => set('strengths', v)}
        max={5}
        allowCustom
      />

      {/* Seniority + Capacity */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <div>
          <label style={labelStyle}>Seniority</label>
          <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
            {SENIORITY.map(s => (
              <button
                key={s}
                type="button"
                onClick={() => set('seniority', s)}
                style={{
                  padding: '4px 10px',
                  fontSize: 'var(--text-xs)',
                  fontFamily: 'var(--font-sans)',
                  fontWeight: draft.seniority === s ? 600 : 400,
                  border: `1.5px solid ${draft.seniority === s ? 'var(--color-accent)' : 'var(--color-border)'}`,
                  borderRadius: 'var(--radius-sm)',
                  background: draft.seniority === s ? 'rgba(12,102,228,0.08)' : 'transparent',
                  color: draft.seniority === s ? 'var(--color-accent)' : 'var(--color-text-secondary)',
                  cursor: 'pointer',
                  transition: 'all 0.12s',
                }}
              >
                {s}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label style={labelStyle}>Capacity</label>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <input
              style={{ ...inputStyle, width: 80 }}
              type="number"
              min={1}
              max={80}
              value={draft.capacity}
              onChange={e => set('capacity', Number(e.target.value))}
            />
            <span style={{
              fontSize: 'var(--text-sm)',
              color: 'var(--color-text-muted)',
              fontFamily: 'var(--font-sans)',
            }}>h/wk</span>
          </div>
        </div>
      </div>

      {/* Meeting load */}
      <div>
        <label style={labelStyle}>Meeting load</label>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 6 }}>
          {MEETING_HOURS.map(m => (
            <button
              key={m.id}
              type="button"
              onClick={() => set('meetings', m.id)}
              style={{
                padding: '8px 4px',
                border: `1.5px solid ${draft.meetings === m.id ? 'var(--color-accent)' : 'var(--color-border)'}`,
                borderRadius: 'var(--radius-md)',
                background: draft.meetings === m.id ? 'rgba(12,102,228,0.08)' : 'transparent',
                cursor: 'pointer',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                gap: 2,
                transition: 'all 0.12s',
              }}
            >
              <span style={{
                fontSize: 'var(--text-xs)',
                fontWeight: 600,
                color: draft.meetings === m.id ? 'var(--color-accent)' : 'var(--color-text-primary)',
                fontFamily: 'var(--font-sans)',
              }}>{m.label}</span>
              <span style={{
                fontSize: 10,
                color: 'var(--color-text-muted)',
                fontFamily: 'var(--font-sans)',
              }}>{m.desc}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Actions */}
      <div style={{ display: 'flex', gap: 10, paddingTop: 4 }}>
        <button
          type="button"
          onClick={() => {
            if (canSave) onSave(draft)
          }}
          disabled={!canSave}
          style={{
            padding: '8px 18px',
            fontSize: 'var(--text-sm)',
            fontFamily: 'var(--font-sans)',
            fontWeight: 600,
            border: 'none',
            borderRadius: 'var(--radius-md)',
            background: canSave ? 'var(--color-accent)' : 'var(--color-border)',
            color: canSave ? '#ffffff' : 'var(--color-text-muted)',
            cursor: canSave ? 'pointer' : 'not-allowed',
            transition: 'background 0.12s',
          }}
        >
          Add member
        </button>
        {showCancel && (
          <button
            type="button"
            onClick={onCancel}
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
            Cancel
          </button>
        )}
      </div>
    </div>
  )
}
