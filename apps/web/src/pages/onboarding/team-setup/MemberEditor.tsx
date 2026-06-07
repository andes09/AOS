import { useState, useEffect, useRef } from 'react'
import { MemberDraft, BLANK_MEMBER } from './types'
import { ROLES, STRENGTHS, SENIORITY, MEETING_HOURS, roleHue } from './data'
import { MultiSelect } from './MultiSelect'

interface MemberEditorProps {
  initial?: Partial<MemberDraft>
  titleText: string
  saveLabel: string
  onSave: (m: MemberDraft) => void
  onClose: () => void
}

function RoleSelect({ value, customRole, onChange }: {
  value: string
  customRole: string
  onChange: (id: string, custom: string) => void
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const wrapRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    function d(e: MouseEvent) {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false); setQuery('')
      }
    }
    document.addEventListener('mousedown', d)
    return () => document.removeEventListener('mousedown', d)
  }, [])

  useEffect(() => { if (open) setTimeout(() => inputRef.current?.focus(), 0) }, [open])

  const label = value === 'custom' ? (customRole || '') : (ROLES.find(r => r.id === value)?.label || '')
  const q = query.trim().toLowerCase()
  const matches = ROLES.filter(r => r.label.toLowerCase().includes(q))
  const showCustom = q.length > 0 && !ROLES.some(r => r.label.toLowerCase() === q)

  function pick(id: string) { onChange(id, ''); setOpen(false); setQuery('') }
  function pickCustom() {
    const v = query.trim()
    if (v) onChange('custom', v)
    setOpen(false); setQuery('')
  }

  return (
    <div ref={wrapRef} style={{ position: 'relative' }}>
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        style={{
          width: '100%', textAlign: 'left', display: 'flex', alignItems: 'center', gap: 8,
          background: '#fff', border: `1px solid ${open ? '#1a1d23' : '#e3e6eb'}`, borderRadius: 6,
          padding: '9px 12px', fontSize: 14, cursor: 'pointer',
          color: label ? '#1a1d23' : '#a8aeb8', transition: 'border-color .12s',
        }}
      >
        <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {label || 'Choose a role…'}
        </span>
        <svg width="10" height="10" viewBox="0 0 10 10" style={{ transform: open ? 'rotate(180deg)' : 'none', transition: 'transform .15s', flexShrink: 0 }}>
          <path d="M1 3 L5 7 L9 3" stroke="#5b6470" strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {open && (
        <div style={{
          position: 'absolute', top: 'calc(100% + 4px)', left: 0, right: 0, zIndex: 40,
          background: '#fff', border: '1px solid #c9cfd8', borderRadius: 8,
          boxShadow: '0 10px 28px rgba(15,18,25,0.10), 0 2px 6px rgba(15,18,25,0.06)',
          maxHeight: 260, overflowY: 'auto', padding: 5,
        }}>
          <input
            ref={inputRef}
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter') { e.preventDefault(); if (matches[0]) pick(matches[0].id); else if (showCustom) pickCustom() }
              if (e.key === 'Escape') setOpen(false)
            }}
            placeholder="Search roles…"
            style={{
              width: '100%', border: '1px solid #e3e6eb', borderRadius: 6,
              padding: '7px 10px', fontSize: 13, marginBottom: 5, outline: 'none',
            }}
          />
          {(['Engineering', 'Agile'] as const).map(g => {
            const items = matches.filter(r => r.group === g)
            if (items.length === 0) return null
            return (
              <div key={g} style={{ marginBottom: 2 }}>
                <div style={{ fontSize: 10, fontWeight: 600, color: '#8a93a0', letterSpacing: '.07em', textTransform: 'uppercase', padding: '6px 8px 3px' }}>{g}</div>
                {items.map(r => {
                  const sel = value === r.id
                  return (
                    <div
                      key={r.id}
                      onClick={() => pick(r.id)}
                      style={{
                        padding: '7px 10px', borderRadius: 5, cursor: 'pointer', fontSize: 13,
                        color: sel ? '#1a1d23' : '#1a1d23', background: sel ? '#eef0f3' : 'transparent',
                        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                      }}
                      onMouseEnter={e => { if (!sel) (e.currentTarget as HTMLElement).style.background = '#f0f2f5' }}
                      onMouseLeave={e => { if (!sel) (e.currentTarget as HTMLElement).style.background = 'transparent' }}
                    >
                      <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span style={{ width: 8, height: 8, borderRadius: '50%', background: `oklch(0.6 0.14 ${r.id === 'frontend' ? 235 : 240})`, display: 'block' }} />
                        {r.label}
                      </span>
                      {sel && (
                        <svg width="10" height="10" viewBox="0 0 8 8" fill="none">
                          <path d="M1 4 L3 6 L7 1" stroke="#1a1d23" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                      )}
                    </div>
                  )
                })}
              </div>
            )
          })}
          {matches.length === 0 && !showCustom && (
            <div style={{ padding: '10px', fontSize: 12, color: '#8a93a0' }}>No roles found</div>
          )}
          {showCustom && (
            <div
              onClick={pickCustom}
              style={{
                padding: '8px 10px', borderRadius: 5, cursor: 'pointer',
                borderTop: '1px solid #e3e6eb', marginTop: 4,
                display: 'flex', alignItems: 'center', gap: 8,
              }}
              onMouseEnter={e => (e.currentTarget as HTMLElement).style.background = '#f0f2f5'}
              onMouseLeave={e => (e.currentTarget as HTMLElement).style.background = 'transparent'}
            >
              <span style={{ width: 14, height: 14, borderRadius: 3, border: '1.5px dashed #8a93a0', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#5b6470', fontSize: 12, lineHeight: 1 }}>+</span>
              <span style={{ fontSize: 13, color: '#1a1d23' }}>Use "<strong style={{ color: '#1a1d23' }}>{query.trim()}</strong>"</span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export function MemberEditor({ initial = {}, titleText, saveLabel, onSave, onClose }: MemberEditorProps) {
  const [form, setForm] = useState<MemberDraft>({ ...BLANK_MEMBER, ...initial })
  const [detail, setDetail] = useState(false)
  const nameRef = useRef<HTMLInputElement>(null)

  const up = (patch: Partial<MemberDraft>) => setForm(p => ({ ...p, ...patch }))
  const valid = form.name.trim() && form.role && (form.role !== 'custom' || form.customRole.trim())
  const hue = roleHue(form.role, form.customRole, form.name)

  useEffect(() => { setTimeout(() => nameRef.current?.focus(), 30) }, [])
  useEffect(() => {
    function esc(e: KeyboardEvent) { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', esc)
    return () => document.removeEventListener('keydown', esc)
  }, [onClose])

  return (
    <div
      onMouseDown={onClose}
      style={{
        position: 'fixed', inset: 0, zIndex: 1000,
        background: 'rgba(20,24,32,0.34)', backdropFilter: 'blur(2px)',
        display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24,
      }}
    >
      <div
        onMouseDown={e => e.stopPropagation()}
        className="anim"
        style={{
          width: '100%', maxWidth: 440, maxHeight: '88vh', overflowY: 'auto',
          background: '#fff', borderRadius: 16, border: '1px solid #e3e6eb',
          boxShadow: '0 24px 60px rgba(15,18,25,0.22)',
        }}
      >
        {/* Color stripe */}
        <div style={{ height: 6, background: `linear-gradient(90deg, oklch(0.64 0.13 ${hue}), oklch(0.52 0.15 ${hue}))` }} />

        <div style={{ padding: '20px 22px', display: 'flex', flexDirection: 'column', gap: 16 }}>
          {/* Header */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <h3 style={{ fontSize: 16, fontWeight: 700, color: '#1a1d23' }}>{titleText}</h3>
            <button onClick={onClose} style={{ background: 'transparent', border: 'none', color: '#8a93a0', cursor: 'pointer', fontSize: 22, lineHeight: 1 }}>×</button>
          </div>

          {/* Name */}
          <div>
            <div style={{ fontSize: 11, fontWeight: 600, color: '#8a93a0', letterSpacing: '0.07em', textTransform: 'uppercase', marginBottom: 8 }}>Full name</div>
            <input
              ref={nameRef}
              value={form.name}
              onChange={e => up({ name: e.target.value })}
              onKeyDown={e => { if (e.key === 'Enter' && valid) onSave({ ...form }) }}
              placeholder="Jamie Chen"
              style={{ width: '100%', background: '#fff', border: '1px solid #e3e6eb', borderRadius: 6, padding: '9px 12px', fontSize: 14, color: '#1a1d23', outline: 'none' }}
            />
          </div>

          {/* Role + Capacity */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 116px', gap: 10 }}>
            <div>
              <div style={{ fontSize: 11, fontWeight: 600, color: '#8a93a0', letterSpacing: '0.07em', textTransform: 'uppercase', marginBottom: 8 }}>Role</div>
              <RoleSelect value={form.role} customRole={form.customRole} onChange={(id, c) => up({ role: id, customRole: c })} />
            </div>
            <div>
              <div style={{ fontSize: 11, fontWeight: 600, color: '#8a93a0', letterSpacing: '0.07em', textTransform: 'uppercase', marginBottom: 8 }}>Capacity</div>
              <div style={{ position: 'relative' }}>
                <input
                  type="number" min={1} max={60} value={form.capacity}
                  onChange={e => up({ capacity: Number(e.target.value) })}
                  style={{ width: '100%', background: '#fff', border: '1px solid #e3e6eb', borderRadius: 6, padding: '9px 40px 9px 12px', fontSize: 14, color: '#1a1d23', outline: 'none' }}
                />
                <span style={{ position: 'absolute', right: 10, top: '50%', transform: 'translateY(-50%)', fontSize: 12, color: '#8a93a0', pointerEvents: 'none' }}>h/wk</span>
              </div>
            </div>
          </div>

          {/* Optional detail toggle */}
          {!detail ? (
            <button
              onClick={() => setDetail(true)}
              style={{ alignSelf: 'flex-start', background: 'none', border: 'none', color: '#1a1d23', fontSize: 13, fontWeight: 500, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6, padding: 0 }}
            >
              <span style={{ fontSize: 16, lineHeight: 1 }}>+</span>
              Add strengths &amp; detail <span style={{ color: '#8a93a0', fontWeight: 400 }}>— optional</span>
            </button>
          ) : (
            <div className="anim" style={{ borderTop: '1px solid #edeff3', paddingTop: 16, display: 'flex', flexDirection: 'column', gap: 18 }}>
              <MultiSelect
                label="Strengths"
                note="— what are they great at? (up to 5)"
                placeholder="Search strengths…"
                options={STRENGTHS}
                selected={form.strengths}
                onChange={v => up({ strengths: v })}
                max={5}
                allowCustom
              />
              <div>
                <div style={{ fontSize: 11, fontWeight: 600, color: '#8a93a0', letterSpacing: '0.07em', textTransform: 'uppercase', marginBottom: 8 }}>Seniority</div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                  {SENIORITY.map(s => {
                    const sel = form.seniority === s
                    return (
                      <button
                        key={s}
                        onClick={() => up({ seniority: s })}
                        style={{
                          padding: '5px 11px', borderRadius: 6, fontSize: 12, fontWeight: 500, cursor: 'pointer',
                          border: `1px solid ${sel ? '#1a1d23' : '#e3e6eb'}`,
                          background: sel ? '#eef0f3' : 'transparent',
                          color: sel ? '#1a1d23' : '#5b6470', transition: 'all .12s',
                        }}
                      >{s}</button>
                    )
                  })}
                </div>
              </div>
              <div>
                <div style={{ fontSize: 11, fontWeight: 600, color: '#8a93a0', letterSpacing: '0.07em', textTransform: 'uppercase', marginBottom: 8 }}>
                  Meeting load <span style={{ fontWeight: 400, textTransform: 'none', letterSpacing: 0 }}>— weekly hours in meetings</span>
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                  {MEETING_HOURS.map(m => {
                    const sel = form.meetings === m.id
                    return (
                      <button
                        key={m.id}
                        onClick={() => up({ meetings: m.id })}
                        style={{
                          padding: '6px 12px', borderRadius: 20, fontSize: 12, fontWeight: 500, cursor: 'pointer',
                          border: `1px solid ${sel ? '#1a1d23' : '#e3e6eb'}`,
                          background: sel ? '#eef0f3' : 'transparent',
                          color: sel ? '#1a1d23' : '#5b6470', transition: 'all .12s',
                        }}
                      >{m.label}</button>
                    )
                  })}
                </div>
              </div>
              <div>
                <div style={{ fontSize: 11, fontWeight: 600, color: '#8a93a0', letterSpacing: '0.07em', textTransform: 'uppercase', marginBottom: 8 }}>
                  Email <span style={{ fontWeight: 400, textTransform: 'none', letterSpacing: 0 }}>— optional</span>
                </div>
                <input
                  type="email" placeholder="name@company.com" value={form.email}
                  onChange={e => up({ email: e.target.value })}
                  style={{ width: '100%', background: '#fff', border: '1px solid #e3e6eb', borderRadius: 6, padding: '9px 12px', fontSize: 14, color: '#1a1d23', outline: 'none' }}
                />
              </div>
            </div>
          )}

          {/* Actions */}
          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', paddingTop: 2 }}>
            <button
              onClick={onClose}
              style={{ padding: '7px 16px', fontSize: 13, fontWeight: 500, border: 'none', background: 'transparent', color: '#5b6470', cursor: 'pointer' }}
            >Cancel</button>
            <button
              onClick={() => { if (valid) onSave({ ...form }) }}
              disabled={!valid}
              style={{
                padding: '7px 16px', fontSize: 13, fontWeight: 600, border: 'none', borderRadius: 6,
                background: valid ? '#1a1d23' : '#e3e6eb', color: valid ? '#fff' : '#8a93a0',
                cursor: valid ? 'pointer' : 'not-allowed', transition: 'all .12s',
              }}
            >{saveLabel}</button>
          </div>
        </div>
      </div>
    </div>
  )
}
