import { useState, useEffect, useRef } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useJiraOAuth } from '../hooks/useJiraOAuth'
import { useApi } from '../lib/api'

// ─── Design tokens ────────────────────────────────────────────────────────────
const C = {
  bg0:         '#ffffff',
  bg1:         '#f7f8fa',
  bg2:         '#ffffff',
  bg3:         '#f0f2f5',
  accent:      '#1a1d23',
  accentSubtle:'#eef0f3',
  accentBorder:'#1a1d23',
  border:      '#e3e6eb',
  borderStrong:'#c9cfd8',
  borderSubtle:'#edeff3',
  t1: '#1a1d23',
  t2: '#5b6470',
  t3: '#8a93a0',
  success:   '#1f7a4d',
  successBg: '#e8f5ee',
}

const WARM = {
  surface:  '#fcfbf9',
  accent:   'oklch(0.56 0.11 45)',
  accentBg: 'oklch(0.96 0.032 62)',
  accentBd: 'oklch(0.89 0.055 58)',
}

// ─── Data ─────────────────────────────────────────────────────────────────────
const ROLES = [
  { id: 'frontend',    label: 'Frontend Dev',   group: 'Engineering' },
  { id: 'backend',     label: 'Backend Dev',    group: 'Engineering' },
  { id: 'fullstack',   label: 'Fullstack Dev',  group: 'Engineering' },
  { id: 'mobile',      label: 'Mobile Dev',     group: 'Engineering' },
  { id: 'devops',      label: 'DevOps / Infra', group: 'Engineering' },
  { id: 'qa',          label: 'QA Engineer',    group: 'Engineering' },
  { id: 'data',        label: 'Data Engineer',  group: 'Engineering' },
  { id: 'scrummaster', label: 'Scrum Master',   group: 'Agile' },
  { id: 'po',          label: 'Product Owner',  group: 'Agile' },
  { id: 'techlead',    label: 'Tech Lead',      group: 'Agile' },
  { id: 'stakeholder', label: 'Stakeholder',    group: 'Agile' },
]

const STRENGTHS = [
  'API Design','System Architecture','Frontend','Backend','Mobile','Cloud Infra','DevOps',
  'Data Modeling','Machine Learning','UI / UX','Accessibility','Performance','Security',
  'Testing / QA','Mentorship','Code Review','Documentation','Incident Response',
  'Database Tuning','Distributed Systems','Observability','Refactoring','Estimation',
]

const SENIORITY = ['Intern','Junior','Mid','Senior','Staff']

const MEETING_HOURS = [
  { id: 'lt1',   label: '< 1 h',    desc: 'Heads-down' },
  { id: '1to3',  label: '1 – 3 h',  desc: 'Light' },
  { id: '3to6',  label: '3 – 6 h',  desc: 'Standard' },
  { id: '6to10', label: '6 – 10 h', desc: 'Heavy' },
  { id: 'gt10',  label: '10 h +',   desc: 'Manager-level' },
]

const STEP_LBLS = ['Connect Jira', 'Confirm team', 'Review']

const WHY = [
  'Omada reads the board your team already works in, so you never re-enter what Jira already knows — your roster, cadence and board setup.',
  'Velocity profiles are per-person. Confirming who is actually on the sprint team keeps capacity and assignment intelligence accurate.',
  'A last check before we sync. Profiles map to Jira assignees, so imported sprint history lines up with the right people.',
]

const ROLE_HUES: Record<string, number> = {
  frontend: 235, backend: 275, fullstack: 200, mobile: 330, devops: 35,
  qa: 150, data: 95, scrummaster: 50, po: 18, techlead: 260, stakeholder: 310,
}

const QUICK_ROLES = ['frontend','backend','fullstack','mobile','devops','qa','data','techlead','po','scrummaster']

// ─── Types ────────────────────────────────────────────────────────────────────
interface Member {
  name: string
  email?: string
  role: string
  customRole?: string
  strengths: string[]
  seniority: string
  capacity: number
  meetings: string
  handle?: string
  issues?: number
  included?: boolean
  bot?: boolean
  jira_account_id?: string
}

interface Board {
  id: string
  name: string
  project_key: string
  type: string
  connection_id: string
  recommended?: boolean
}

const BLANK_MEMBER: Member = {
  name: '', email: '', role: '', customRole: '', strengths: [],
  seniority: 'Mid', capacity: 40, meetings: '3to6',
}

// ─── Helpers ──────────────────────────────────────────────────────────────────
function roleHue(m: Member): number {
  if (!m.role || m.role === 'custom') {
    const s = m.customRole || m.name || 'x'
    return s.split('').reduce((a, c) => a + c.charCodeAt(0), 0) % 360
  }
  return ROLE_HUES[m.role] ?? 240
}

function roleLabelOf(m: Member): string {
  if (m.role === 'custom') return m.customRole || 'Custom role'
  return ROLES.find(r => r.id === m.role)?.label || ''
}

// ─── Atoms ────────────────────────────────────────────────────────────────────
function FieldLabel({ children, note }: { children: React.ReactNode; note?: string }) {
  return (
    <div style={{ fontSize: 11, fontWeight: 600, color: C.t3, letterSpacing: '0.07em', textTransform: 'uppercase', marginBottom: 8, display: 'flex', gap: 6, alignItems: 'center' }}>
      {children}
      {note && <span style={{ fontWeight: 400, textTransform: 'none', letterSpacing: 0, color: C.t3 }}>{note}</span>}
    </div>
  )
}

function OInput({ label, note, containerStyle, ...rest }: { label?: string; note?: string; containerStyle?: React.CSSProperties } & React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <div style={containerStyle}>
      {label && <FieldLabel note={note}>{label}</FieldLabel>}
      <input style={{ width: '100%', background: C.bg0, border: `1px solid ${C.border}`, borderRadius: 6, padding: '9px 12px', color: C.t1, fontSize: 14 }} {...rest} />
    </div>
  )
}

function Seg({ options, value, onChange, small }: { options: string[]; value: string; onChange: (v: string) => void; small?: boolean }) {
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
      {options.map(o => {
        const sel = value === o
        return (
          <button key={o} onClick={() => onChange(o)} style={{
            padding: small ? '5px 11px' : '7px 14px', borderRadius: 6, fontSize: small ? 12 : 13, fontWeight: 500, cursor: 'pointer',
            border: `1px solid ${sel ? C.accent : C.border}`, background: sel ? C.accentSubtle : 'transparent', color: sel ? C.accent : C.t2, transition: 'all 0.12s',
          }}>{o}</button>
        )
      })}
    </div>
  )
}

function Chips({ label, note, options, selected, onChange, max }: {
  label?: string; note?: string; options: string[]; selected: string[]; onChange: (v: string[]) => void; max?: number
}) {
  function toggle(o: string) {
    if (selected.includes(o)) onChange(selected.filter(s => s !== o))
    else if (!max || selected.length < max) onChange([...selected, o])
  }
  return (
    <div>
      {label && <FieldLabel note={note}>{label}</FieldLabel>}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
        {options.map(o => {
          const sel = selected.includes(o)
          const atMax = !!(max && selected.length >= max && !sel)
          return (
            <button key={o} onClick={() => toggle(o)} disabled={atMax} style={{
              padding: '5px 11px', borderRadius: 20, fontSize: 12, fontWeight: 500,
              cursor: atMax ? 'default' : 'pointer',
              border: `1px solid ${sel ? C.accent : C.border}`,
              background: sel ? C.accentSubtle : 'transparent',
              color: sel ? C.accent : atMax ? C.t3 : C.t2, transition: 'all 0.12s',
            }}>{o}</button>
          )
        })}
      </div>
    </div>
  )
}

function Btn({ children, variant = 'primary', size = 'md', onClick, disabled, style }: {
  children: React.ReactNode; variant?: 'primary' | 'secondary' | 'ghost' | 'outline';
  size?: 'sm' | 'md' | 'lg'; onClick?: () => void; disabled?: boolean; style?: React.CSSProperties
}) {
  const varMap = {
    primary:   { background: C.accent, color: '#fff', border: 'none' },
    secondary: { background: C.bg2, color: C.t1, border: `1px solid ${C.border}` },
    ghost:     { background: 'transparent', color: C.t2, border: 'none' },
    outline:   { background: 'transparent', color: C.accent, border: `1px solid ${C.accent}` },
  }
  const sizeMap = {
    sm: { fontSize: 12, padding: '5px 12px' },
    md: { fontSize: 13, padding: '7px 16px' },
    lg: { fontSize: 15, padding: '11px 26px' },
  }
  return (
    <button onClick={onClick} disabled={disabled} style={{
      borderRadius: 6, fontWeight: 600, cursor: disabled ? 'not-allowed' : 'pointer',
      opacity: disabled ? 0.5 : 1, transition: 'opacity 0.12s, background 0.12s',
      ...varMap[variant], ...sizeMap[size], ...style,
    }}>{children}</button>
  )
}

function Avatar({ name, size = 36 }: { name: string; size?: number }) {
  const initials = (name || '?').split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase()
  const hue = (name || '').split('').reduce((a, c) => a + c.charCodeAt(0), 0) % 360
  return (
    <div style={{ width: size, height: size, borderRadius: '50%', flexShrink: 0, background: `oklch(0.94 0.02 ${hue})`, border: `1px solid oklch(0.86 0.04 ${hue})`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: size * 0.34, fontWeight: 600, color: `oklch(0.38 0.08 ${hue})`, letterSpacing: '-0.02em' }}>{initials}</div>
  )
}

function RoleSelect({ value, customRole, onChange, placeholder = 'Choose a role…', dense }: {
  value: string; customRole?: string; onChange: (id: string, custom: string) => void; placeholder?: string; dense?: boolean
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const wrapRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    function d(e: MouseEvent) { if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) { setOpen(false); setQuery('') } }
    document.addEventListener('mousedown', d)
    return () => document.removeEventListener('mousedown', d)
  }, [])
  useEffect(() => { if (open) setTimeout(() => inputRef.current?.focus(), 0) }, [open])

  const label = value === 'custom' ? (customRole || '') : (ROLES.find(r => r.id === value)?.label || '')
  const q = query.trim().toLowerCase()
  const matches = ROLES.filter(r => r.label.toLowerCase().includes(q))
  const showCustom = q.length > 0 && !ROLES.some(r => r.label.toLowerCase() === q)

  function pick(r: { id: string }) { onChange(r.id, ''); setOpen(false); setQuery('') }
  function pickCustom() { const v = query.trim(); if (v) onChange('custom', v); setOpen(false); setQuery('') }

  return (
    <div ref={wrapRef} style={{ position: 'relative' }}>
      <button type="button" onClick={() => setOpen(o => !o)} style={{
        width: '100%', textAlign: 'left', display: 'flex', alignItems: 'center', gap: 8, background: C.bg0,
        border: `1px solid ${open ? C.accent : C.border}`, borderRadius: 6, padding: dense ? '8px 10px' : '9px 12px',
        fontSize: 14, cursor: 'pointer', color: label ? C.t1 : C.t3, transition: 'border-color .12s',
      }}>
        <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{label || placeholder}</span>
        <svg width="10" height="10" viewBox="0 0 10 10" style={{ transform: open ? 'rotate(180deg)' : 'none', transition: 'transform .15s', flexShrink: 0 }}>
          <path d="M1 3 L5 7 L9 3" stroke={C.t2} strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {open && (
        <div style={{ position: 'absolute', top: 'calc(100% + 4px)', left: 0, right: 0, zIndex: 40, background: C.bg2, border: `1px solid ${C.borderStrong}`, borderRadius: 8, boxShadow: '0 10px 28px rgba(15,18,25,0.10), 0 2px 6px rgba(15,18,25,0.06)', maxHeight: 260, overflowY: 'auto', padding: 5 }}>
          <input ref={inputRef} value={query} onChange={e => setQuery(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter') { e.preventDefault(); if (matches[0]) pick(matches[0]); else if (showCustom) pickCustom() }
              if (e.key === 'Escape') setOpen(false)
            }}
            placeholder="Search roles…" style={{ width: '100%', border: `1px solid ${C.border}`, borderRadius: 6, padding: '7px 10px', fontSize: 13, marginBottom: 5, outline: 'none' }} />
          {(['Engineering', 'Agile'] as const).map(g => {
            const items = matches.filter(r => r.group === g)
            if (items.length === 0) return null
            return (
              <div key={g} style={{ marginBottom: 2 }}>
                <div style={{ fontSize: 10, fontWeight: 600, color: C.t3, letterSpacing: '.07em', textTransform: 'uppercase', padding: '6px 8px 3px' }}>{g}</div>
                {items.map(r => {
                  const sel = value === r.id
                  return (
                    <div key={r.id} onClick={() => pick(r)} style={{ padding: '7px 10px', borderRadius: 5, cursor: 'pointer', fontSize: 13, color: sel ? C.accent : C.t1, background: sel ? C.accentSubtle : 'transparent', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}
                      onMouseEnter={e => { if (!sel) (e.currentTarget as HTMLElement).style.background = C.bg3 }}
                      onMouseLeave={e => { if (!sel) (e.currentTarget as HTMLElement).style.background = 'transparent' }}>
                      <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span style={{ width: 8, height: 8, borderRadius: '50%', background: `oklch(0.6 0.14 ${ROLE_HUES[r.id] ?? 240})` }} />
                        {r.label}
                      </span>
                      {sel && <svg width="10" height="10" viewBox="0 0 8 8"><path d="M1 4 L3 6 L7 1" stroke={C.accent} strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round" /></svg>}
                    </div>
                  )
                })}
              </div>
            )
          })}
          {matches.length === 0 && !showCustom && <div style={{ padding: '10px', fontSize: 12, color: C.t3 }}>No roles found</div>}
          {showCustom && (
            <div onClick={pickCustom} style={{ padding: '8px 10px', borderRadius: 5, cursor: 'pointer', borderTop: `1px solid ${C.border}`, marginTop: 4, display: 'flex', alignItems: 'center', gap: 8 }}
              onMouseEnter={e => (e.currentTarget as HTMLElement).style.background = C.bg3}
              onMouseLeave={e => (e.currentTarget as HTMLElement).style.background = 'transparent'}>
              <span style={{ width: 14, height: 14, borderRadius: 3, border: `1.5px dashed ${C.t3}`, display: 'flex', alignItems: 'center', justifyContent: 'center', color: C.t2, fontSize: 12, lineHeight: '1' }}>+</span>
              <span style={{ fontSize: 13, color: C.t1 }}>Use "<strong style={{ color: C.accent }}>{query.trim()}</strong>"</span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function CapacityField({ value, onChange, dense }: { value: number; onChange: (v: number) => void; dense?: boolean }) {
  return (
    <div style={{ position: 'relative' }}>
      <input type="number" min={1} max={60} value={value} onChange={e => onChange(Number(e.target.value))}
        style={{ width: '100%', background: C.bg0, border: `1px solid ${C.border}`, borderRadius: 6, padding: dense ? '8px 36px 8px 10px' : '9px 40px 9px 12px', fontSize: 14, color: C.t1 }} />
      <span style={{ position: 'absolute', right: 10, top: '50%', transform: 'translateY(-50%)', fontSize: 12, color: C.t3, pointerEvents: 'none' }}>h/wk</span>
    </div>
  )
}

function MeetingChips({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <div>
      <FieldLabel note="— weekly hours in meetings">Meeting load</FieldLabel>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
        {MEETING_HOURS.map(m => {
          const sel = value === m.id
          return (
            <button key={m.id} type="button" onClick={() => onChange(m.id)} style={{ padding: '6px 12px', borderRadius: 20, fontSize: 12, fontWeight: 500, cursor: 'pointer', border: `1px solid ${sel ? C.accent : C.border}`, background: sel ? C.accentSubtle : 'transparent', color: sel ? C.accent : C.t2, transition: 'all .12s' }}>{m.label}</button>
          )
        })}
      </div>
    </div>
  )
}

function MemberEditor({ initial, titleText, saveLabel, onSave, onClose }: {
  initial: Partial<Member>; titleText: string; saveLabel: string; onSave: (m: Member) => void; onClose: () => void
}) {
  const [form, setForm] = useState<Member>({ ...BLANK_MEMBER, ...initial })
  const [detail, setDetail] = useState(false)
  const nameRef = useRef<HTMLInputElement>(null)
  const up = (patch: Partial<Member>) => setForm(p => ({ ...p, ...patch }))
  const valid = form.name.trim() && form.role && (form.role !== 'custom' || (form.customRole || '').trim())

  useEffect(() => { setTimeout(() => nameRef.current?.focus(), 30) }, [])
  useEffect(() => {
    function esc(e: KeyboardEvent) { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', esc)
    return () => document.removeEventListener('keydown', esc)
  }, [onClose])

  const hue = roleHue(form)

  return (
    <div onMouseDown={onClose} style={{ position: 'fixed', inset: 0, zIndex: 1000, background: 'rgba(20,24,32,0.34)', backdropFilter: 'blur(2px)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}>
      <div onMouseDown={e => e.stopPropagation()} style={{ width: '100%', maxWidth: 440, maxHeight: '88vh', overflowY: 'auto', background: C.bg0, borderRadius: 16, border: `1px solid ${C.border}`, boxShadow: '0 24px 60px rgba(15,18,25,0.22)', animation: 'fadeUp 0.22s ease both' }}>
        <div style={{ height: 6, background: `linear-gradient(90deg, oklch(0.64 0.13 ${hue}), oklch(0.52 0.15 ${hue}))` }} />
        <div style={{ padding: '20px 22px', display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <h3 style={{ fontSize: 16, fontWeight: 700, color: C.t1 }}>{titleText}</h3>
            <button onClick={onClose} style={{ background: 'transparent', border: 'none', color: C.t3, cursor: 'pointer', fontSize: 22, lineHeight: '1' }}>×</button>
          </div>

          <div>
            <FieldLabel>Full name</FieldLabel>
            <input ref={nameRef} value={form.name} onChange={e => up({ name: e.target.value })}
              onKeyDown={e => { if (e.key === 'Enter' && valid) onSave({ ...form }) }}
              placeholder="Jamie Chen" style={{ width: '100%', background: C.bg0, border: `1px solid ${C.border}`, borderRadius: 6, padding: '9px 12px', fontSize: 14, color: C.t1 }} />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 116px', gap: 10 }}>
            <div>
              <FieldLabel>Role</FieldLabel>
              <RoleSelect value={form.role} customRole={form.customRole} onChange={(id, c) => up({ role: id, customRole: c })} />
            </div>
            <div>
              <FieldLabel>Capacity</FieldLabel>
              <CapacityField value={form.capacity} onChange={v => up({ capacity: v })} />
            </div>
          </div>

          {!detail ? (
            <button onClick={() => setDetail(true)} style={{ alignSelf: 'flex-start', background: 'none', border: 'none', color: C.accent, fontSize: 13, fontWeight: 500, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6, padding: 0 }}>
              <span style={{ fontSize: 16, lineHeight: '1' }}>+</span> Add strengths &amp; detail <span style={{ color: C.t3, fontWeight: 400 }}>— optional</span>
            </button>
          ) : (
            <div style={{ borderTop: `1px solid ${C.borderSubtle}`, paddingTop: 16, display: 'flex', flexDirection: 'column', gap: 18, animation: 'fadeUp 0.22s ease both' }}>
              <Chips label="Strengths" note="— what are they great at? (up to 5)" options={STRENGTHS} selected={form.strengths} onChange={v => up({ strengths: v })} max={5} />
              <div>
                <FieldLabel>Seniority</FieldLabel>
                <Seg small options={SENIORITY} value={form.seniority} onChange={v => up({ seniority: v })} />
              </div>
              <MeetingChips value={form.meetings} onChange={v => up({ meetings: v })} />
              <OInput label="Email" note="— optional" placeholder="name@company.com" type="email" value={form.email || ''} onChange={e => up({ email: e.target.value })} />
            </div>
          )}

          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', paddingTop: 2 }}>
            <Btn variant="ghost" onClick={onClose}>Cancel</Btn>
            <Btn onClick={() => onSave({ ...form })} disabled={!valid}>{saveLabel}</Btn>
          </div>
        </div>
      </div>
    </div>
  )
}

function CapacityStepper({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  const set = (v: number) => onChange(Math.max(5, Math.min(60, v)))
  const btn: React.CSSProperties = { width: 24, height: 24, borderRadius: 6, border: `1px solid ${C.border}`, background: C.bg0, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', color: C.t2, fontSize: 15, lineHeight: '1', flexShrink: 0 }
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
      <button onClick={e => { e.stopPropagation(); set(value - 5) }} style={btn}>−</button>
      <div style={{ flex: 1, textAlign: 'center', fontSize: 13, fontWeight: 700, color: C.t1 }}>{value}<span style={{ fontSize: 11, fontWeight: 500, color: C.t3 }}> h/wk</span></div>
      <button onClick={e => { e.stopPropagation(); set(value + 5) }} style={btn}>+</button>
    </div>
  )
}

function RosterCard({ member, index, onUpdate, onExclude, onEditFull }: {
  member: Member; index: number; onUpdate: (i: number, patch: Partial<Member>) => void;
  onExclude: (i: number) => void; onEditFull: (i: number) => void
}) {
  const [flip, setFlip] = useState(false)
  const [hover, setHover] = useState(false)
  const hue = roleHue(member)
  const role = roleLabelOf(member)
  const faceBase: React.CSSProperties = {
    position: 'absolute', inset: 0, borderRadius: 14, overflow: 'hidden',
    backfaceVisibility: 'hidden', border: `1px solid ${C.border}`, background: C.bg0,
  }
  return (
    <div style={{ perspective: 1000, height: 250 }} onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}>
      <div style={{
        position: 'relative', width: '100%', height: '100%', transformStyle: 'preserve-3d',
        transition: 'transform .55s cubic-bezier(.4,.1,.2,1), box-shadow .2s',
        transform: `${flip ? 'rotateY(180deg)' : 'rotateY(0)'} translateY(${hover ? -3 : 0}px)`,
        boxShadow: hover ? '0 16px 30px rgba(15,18,25,0.14)' : '0 2px 6px rgba(15,18,25,0.06)', borderRadius: 14,
      }}>
        {/* FRONT */}
        <div style={{ ...faceBase, opacity: flip ? 0 : 1, pointerEvents: flip ? 'none' : 'auto', transition: 'opacity 0s linear .27s' }}>
          <div style={{ height: 70, background: `linear-gradient(135deg, oklch(0.66 0.13 ${hue}), oklch(0.5 0.16 ${hue}))`, position: 'relative' }}>
            <div style={{ position: 'absolute', inset: 0, background: 'linear-gradient(115deg, rgba(255,255,255,.28) 0%, rgba(255,255,255,0) 42%)', opacity: hover ? 0.9 : 0.5, transition: 'opacity .3s' }} />
            <span style={{ position: 'absolute', top: 10, left: 12, fontSize: 11, fontWeight: 600, color: 'rgba(255,255,255,.95)', fontFamily: 'monospace' }}>@{member.handle || 'member'}</span>
            {hover && <button onClick={e => { e.stopPropagation(); onExclude(index) }} title="Not on this team" style={{ position: 'absolute', top: 7, right: 8, background: 'rgba(0,0,0,.18)', border: 'none', color: '#fff', cursor: 'pointer', fontSize: 15, lineHeight: '1', borderRadius: '50%', width: 20, height: 20 }}>×</button>}
          </div>
          <div style={{ padding: '0 12px 11px', height: 'calc(100% - 70px)', display: 'flex', flexDirection: 'column' }}>
            <div style={{ marginTop: -22, marginBottom: 5, display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between' }}>
              <div style={{ width: 46, height: 46, borderRadius: '50%', background: `oklch(0.96 0.03 ${hue})`, border: '3px solid #fff', boxShadow: '0 2px 5px rgba(15,18,25,0.12)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 16, fontWeight: 700, color: `oklch(0.42 0.11 ${hue})` }}>
                {(member.name || '?').split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase()}
              </div>
              {member.issues != null && <span style={{ fontSize: 10.5, color: C.t3, marginBottom: 2 }}>{member.issues} issues</span>}
            </div>
            <div style={{ fontSize: 14, fontWeight: 700, color: C.t1, lineHeight: 1.15, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{member.name}</div>
            <div style={{ fontSize: 11.5, color: role ? `oklch(0.5 0.12 ${hue})` : C.t3, marginTop: 1, fontWeight: role ? 600 : 400 }}>{role || 'Role optional'}</div>
            <div style={{ marginTop: 'auto', display: 'flex', flexDirection: 'column', gap: 7 }}>
              <CapacityStepper value={member.capacity} onChange={v => onUpdate(index, { capacity: v })} />
              <button onClick={e => { e.stopPropagation(); setFlip(true) }} style={{ background: 'none', border: 'none', color: `oklch(0.5 0.13 ${hue})`, fontSize: 11, fontWeight: 600, cursor: 'pointer', padding: 0, alignSelf: 'center' }}>
                Flip to enrich ↻
              </button>
            </div>
          </div>
        </div>
        {/* BACK */}
        <div style={{ ...faceBase, transform: 'rotateY(180deg)', background: `oklch(0.985 0.012 ${hue})`, opacity: flip ? 1 : 0, pointerEvents: flip ? 'auto' : 'none', transition: 'opacity 0s linear .27s' }}>
          <div style={{ padding: '11px 12px', height: '100%', display: 'flex', flexDirection: 'column' }}>
            <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: '.06em', textTransform: 'uppercase', color: `oklch(0.5 0.12 ${hue})`, marginBottom: 7 }}>
              Quick role <span style={{ fontWeight: 400, textTransform: 'none', letterSpacing: 0, color: C.t3 }}>· optional</span>
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
              {QUICK_ROLES.map(rid => {
                const r = ROLES.find(x => x.id === rid); const sel = member.role === rid
                return (
                  <button key={rid} onClick={() => onUpdate(index, { role: sel ? '' : rid, customRole: '' })} style={{ fontSize: 10.5, fontWeight: 500, padding: '3px 8px', borderRadius: 20, cursor: 'pointer', border: `1px solid ${sel ? `oklch(0.55 0.13 ${hue})` : C.border}`, background: sel ? '#fff' : 'transparent', color: sel ? `oklch(0.42 0.12 ${hue})` : C.t2 }}>{r?.label}</button>
                )
              })}
            </div>
            <div style={{ marginTop: 'auto', display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderTop: `1px solid oklch(0.9 0.03 ${hue})`, paddingTop: 9 }}>
              <button onClick={() => onEditFull(index)} style={{ background: 'none', border: 'none', color: C.accent, fontSize: 11, fontWeight: 600, cursor: 'pointer', padding: 0 }}>+ Strengths &amp; detail</button>
              <button onClick={() => setFlip(false)} style={{ background: 'none', border: 'none', color: `oklch(0.5 0.13 ${hue})`, fontSize: 11, fontWeight: 600, cursor: 'pointer', padding: 0 }}>↻ Back</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

function ExcludedRow({ member, index, onInclude }: { member: Member; index: number; onInclude: (i: number) => void }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 11px', background: C.bg1, border: `1px solid ${C.border}`, borderRadius: 9 }}>
      <Avatar name={member.name} size={28} />
      <div style={{ minWidth: 0, flex: 1 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: C.t2, display: 'flex', alignItems: 'center', gap: 7 }}>
          {member.name}
          {member.bot && <span style={{ fontSize: 9.5, fontWeight: 700, color: C.t3, background: C.bg3, border: `1px solid ${C.border}`, padding: '1px 6px', borderRadius: 20, letterSpacing: '.03em' }}>APP ACCOUNT</span>}
        </div>
        {member.handle && <div style={{ fontSize: 11.5, color: C.t3, fontFamily: 'monospace' }}>@{member.handle}</div>}
      </div>
      <button onClick={() => onInclude(index)} style={{ background: 'transparent', border: `1px solid ${C.border}`, borderRadius: 6, padding: '5px 11px', fontSize: 12, fontWeight: 600, color: C.t2, cursor: 'pointer' }}>Add to team</button>
    </div>
  )
}

// ─── Brand marks ──────────────────────────────────────────────────────────────
function JiraMark({ size = 34 }: { size?: number }) {
  return (
    <div style={{ width: size, height: size, borderRadius: size * 0.26, background: 'linear-gradient(160deg, #2684FF, #0052CC)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, boxShadow: '0 2px 6px rgba(0,82,204,0.3)' }}>
      <svg width={size * 0.56} height={size * 0.56} viewBox="0 0 24 24" fill="none">
        <path d="M11.5 2 L20 10.5 a2 2 0 0 1 0 3 L11.5 22 L7 17.5 a2 2 0 0 1 0-3 L11.5 10 L8.5 7 a2 2 0 0 1 0-3 Z" fill="#fff" opacity="0.95" />
      </svg>
    </div>
  )
}

function OmadaMark({ size = 34 }: { size?: number }) {
  return (
    <div style={{ width: size, height: size, borderRadius: size * 0.26, background: C.accent, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, fontSize: size * 0.5, fontWeight: 800, color: '#fff', letterSpacing: '-1px' }}>O</div>
  )
}

// ─── Step: Welcome ────────────────────────────────────────────────────────────
function WelcomeStep({ onStart }: { onStart: () => void }) {
  return (
    <div style={{ textAlign: 'center', padding: '24px 0 8px', animation: 'fadeUp 0.22s ease both' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 16, marginBottom: 26 }}>
        <OmadaMark size={52} />
        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          {[0, 1, 2].map(i => <span key={i} style={{ width: 5, height: 5, borderRadius: '50%', background: C.borderStrong }} />)}
        </div>
        <JiraMark size={52} />
      </div>
      <div style={{ fontSize: 11, fontWeight: 600, color: C.success, letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 14 }}>Account created</div>
      <h1 style={{ fontSize: 28, fontWeight: 700, color: C.t1, marginBottom: 12, letterSpacing: '-0.5px', lineHeight: 1.2 }}>Import your team from Jira</h1>
      <p style={{ fontSize: 15, color: C.t2, lineHeight: 1.65, maxWidth: 420, margin: '0 auto 36px' }}>
        Connect the board your team already works in — Omada pulls in your roster, sprint cadence, and setup automatically. No forms to fill in.
      </p>
      <div style={{ display: 'flex', justifyContent: 'center', maxWidth: 460, margin: '0 auto 40px' }}>
        {[
          { step: '01', title: 'Connect Jira', desc: 'Secure, read-only' },
          { step: '02', title: 'Confirm team', desc: 'Auto-imported roster' },
          { step: '03', title: 'Start tracking', desc: 'Cadence & capacity' },
        ].map((item, i) => (
          <div key={i} style={{ flex: 1, textAlign: 'center', padding: '0 12px', borderRight: i < 2 ? `1px solid ${C.border}` : 'none' }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: C.accent, letterSpacing: '0.1em', marginBottom: 4 }}>{item.step}</div>
            <div style={{ fontSize: 13, fontWeight: 600, color: C.t1, marginBottom: 2 }}>{item.title}</div>
            <div style={{ fontSize: 12, color: C.t3 }}>{item.desc}</div>
          </div>
        ))}
      </div>
      <Btn size="lg" onClick={onStart} style={{ display: 'inline-flex', alignItems: 'center', gap: 9 }}>Connect Jira →</Btn>
      <div style={{ marginTop: 14, fontSize: 12, color: C.t3 }}>Takes about a minute · Read-only access</div>
    </div>
  )
}

// ─── ConnectScreen ────────────────────────────────────────────────────────────
function ConnectScreen({ onConnected, onBack }: { onConnected: (id: string) => void; onBack: () => void }) {
  const { connect, isConnecting, error } = useJiraOAuth('/onboarding', onConnected)

  const scopes = [
    ['View projects & boards', 'Read your board names, types and sprint settings'],
    ['View team members', 'Read assignees on issues to build your roster'],
    ['View sprint settings', 'Detect your cadence and methodology'],
  ]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 22, animation: 'fadeUp 0.22s ease both' }}>
      <div>
        <h2 style={{ fontSize: 21, fontWeight: 700, color: C.t1, letterSpacing: '-0.3px', marginBottom: 5 }}>Connect your Jira workspace</h2>
        <p style={{ fontSize: 14, color: C.t2, lineHeight: 1.55 }}>Omada imports your team straight from the board you already work in — no forms to fill in.</p>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 16, padding: '26px 0', background: WARM.surface, border: `1px solid ${C.border}`, borderRadius: 12 }}>
        <OmadaMark size={46} />
        <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
          {[0, 1, 2].map(i => <span key={i} style={{ width: 5, height: 5, borderRadius: '50%', background: C.borderStrong }} />)}
        </div>
        <JiraMark size={46} />
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        <div style={{ fontSize: 10, fontWeight: 700, color: C.t3, letterSpacing: '.07em', textTransform: 'uppercase', marginBottom: 8 }}>Omada will be able to</div>
        {scopes.map(([t, d]) => (
          <div key={t} style={{ display: 'flex', gap: 11, padding: '9px 0', borderBottom: `1px solid ${C.borderSubtle}` }}>
            <div style={{ width: 18, height: 18, borderRadius: '50%', background: C.successBg, border: `1px solid ${C.success}`, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, marginTop: 1 }}>
              <svg width="9" height="9" viewBox="0 0 8 8"><path d="M1 4 L3 6 L7 1" stroke={C.success} strokeWidth="1.6" fill="none" strokeLinecap="round" strokeLinejoin="round" /></svg>
            </div>
            <div>
              <div style={{ fontSize: 13.5, fontWeight: 600, color: C.t1 }}>{t}</div>
              <div style={{ fontSize: 12.5, color: C.t3, lineHeight: 1.4 }}>{d}</div>
            </div>
          </div>
        ))}
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: C.t2, background: C.bg1, borderRadius: 8, padding: '10px 12px' }}>
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke={C.t2} strokeWidth="2"><rect x="4" y="11" width="16" height="10" rx="2" /><path d="M8 11V7a4 4 0 0 1 8 0v4" /></svg>
        <span><strong style={{ color: C.t1, fontWeight: 600 }}>Read-only.</strong> Omada never writes to your boards, and you can revoke access anytime.</span>
      </div>

      {error && <div style={{ background: '#fef2f2', border: '1px solid #fca5a5', borderRadius: 8, padding: '10px 14px', fontSize: 13, color: '#dc2626' }}>{error}</div>}

      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <Btn variant="ghost" onClick={onBack}>← Back</Btn>
        <Btn size="lg" onClick={connect} disabled={isConnecting} style={{ display: 'inline-flex', alignItems: 'center', gap: 9 }}>
          {isConnecting ? (
            <><span style={{ width: 14, height: 14, border: '2px solid rgba(255,255,255,0.5)', borderTopColor: '#fff', borderRadius: '50%', display: 'inline-block', animation: 'spin 0.8s linear infinite' }} /> Connecting…</>
          ) : <>Authorize with Jira →</>}
        </Btn>
      </div>
    </div>
  )
}

// ─── BoardPicker ──────────────────────────────────────────────────────────────

// ─── ScanningScreen ───────────────────────────────────────────────────────────
function ScanningScreen({ boardId, boardName, boardKey, connectionId, onDone, onReset }: {
  boardId: string; boardName: string; boardKey: string; connectionId: string;
  onDone: (members: Member[]) => void
  onReset: () => void
}) {
  const { post, get } = useApi()
  const [done, setDone] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [retryKey, setRetryKey] = useState(0)
  const steps = ['Reading board settings', 'Detecting sprint cadence…', 'Importing team members', 'Building velocity profiles']

  useEffect(() => {
    let cancelled = false
    let pollTimer: ReturnType<typeof setInterval> | null = null

    async function pollSyncStatus(teamId: string): Promise<void> {
      return new Promise((resolve, reject) => {
        let attempts = 0
        pollTimer = setInterval(async () => {
          if (cancelled) { if (pollTimer) clearInterval(pollTimer); resolve(); return }
          attempts++
          if (attempts > 60) { // 2 min timeout
            if (pollTimer) clearInterval(pollTimer)
            reject(new Error('Sync timed out — please try again'))
            return
          }
          try {
            const status = await get<{ state: string; error_message?: string }>(
              `/api/integrations/jira/sync-status/${teamId}`
            )
            if (status.state === 'complete' || status.state === 'unknown') {
              if (pollTimer) clearInterval(pollTimer)
              resolve()
            } else if (status.state === 'failed') {
              if (pollTimer) clearInterval(pollTimer)
              reject(new Error(status.error_message || 'Sync failed'))
            }
          } catch { /* network blip — keep polling */ }
        }, 2000)
      })
    }

    async function run() {
      try {
        // Step 0 → 1: save board selection (triggers Celery sync in background)
        await new Promise(r => setTimeout(r, 420))
        if (cancelled) return
        const sel = await post<{ saved: boolean; team_id?: string }>('/api/integrations/jira/board-selection', {
          connection_id: connectionId, board_id: boardId, project_key: boardKey,
        })
        if (cancelled) return
        setDone(1)

        // Step 1 → 2: wait for background sync via polling
        if (sel.team_id) {
          await pollSyncStatus(sel.team_id)
        } else {
          await new Promise(r => setTimeout(r, 460))
        }
        if (cancelled) return
        setDone(2)

        const raw = await get<Array<{ id: string; name: string; handle: string; email?: string; jira_account_id: string; issues: number }>>(
          `/api/integrations/jira/team-members?connection_id=${encodeURIComponent(connectionId)}`
        )
        if (cancelled) return
        setDone(3)

        await new Promise(r => setTimeout(r, 460))
        if (cancelled) return
        setDone(4)

        await new Promise(r => setTimeout(r, 520))
        if (cancelled) return

        const members: Member[] = raw.map(m => ({
          ...BLANK_MEMBER,
          name: m.name,
          handle: m.handle,
          issues: m.issues,
          jira_account_id: m.jira_account_id,
          email: m.email,
          included: true,
        }))
        onDone(members)
      } catch (e) {
        if (!cancelled) setError((e as any)?.response?.data?.detail ?? (e instanceof Error ? e.message : 'Import failed'))
      }
    }

    run()
    return () => { cancelled = true; if (pollTimer) clearInterval(pollTimer) }
  }, [retryKey])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 22, padding: '8px 0', animation: 'fadeUp 0.22s ease both' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <JiraMark size={40} />
        <div>
          <div style={{ fontSize: 16, fontWeight: 700, color: C.t1 }}>Scanning {boardName}</div>
          <div style={{ fontSize: 13, color: C.t3, fontFamily: 'monospace' }}>{boardKey}</div>
        </div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        {steps.map((s, i) => {
          const isDone = i < done
          const isCur = i === done
          return (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 0', opacity: i <= done ? 1 : 0.35, transition: 'opacity .3s' }}>
              <div style={{ width: 22, height: 22, borderRadius: '50%', flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', background: isDone ? C.successBg : 'transparent', border: `1.5px solid ${isDone ? C.success : C.border}` }}>
                {isDone
                  ? <svg width="10" height="10" viewBox="0 0 8 8" style={{ animation: 'checkPop 0.3s ease both' }}><path d="M1 4 L3 6 L7 1" stroke={C.success} strokeWidth="1.6" fill="none" strokeLinecap="round" strokeLinejoin="round" /></svg>
                  : isCur ? <span style={{ width: 12, height: 12, border: `2px solid ${C.accent}`, borderTopColor: 'transparent', borderRadius: '50%', animation: 'spin 0.7s linear infinite' }} /> : null}
              </div>
              <span style={{ fontSize: 14, color: isDone ? C.t1 : isCur ? C.t1 : C.t3, fontWeight: isCur ? 600 : 400 }}>{s}</span>
            </div>
          )
        })}
      </div>

      {error && (
        <div style={{ background: '#fef2f2', border: '1px solid #fca5a5', borderRadius: 8, padding: '12px 16px', fontSize: 13, color: '#dc2626' }}>
          <strong>Import failed:</strong> {error}
          <div style={{ marginTop: 8, display: 'flex', gap: 8 }}>
            <Btn size="sm" onClick={() => { setError(null); setDone(0); setRetryKey(k => k + 1) }}>Try again</Btn>
            <Btn size="sm" onClick={() => { if (window.confirm('Reset Jira connection and start over?')) onReset() }}>Reset connection</Btn>
          </div>
        </div>
      )}
    </div>
  )
}

// ─── ConnectFlow ──────────────────────────────────────────────────────────────
type ConnectStage = 'connect' | 'project' | 'board' | 'scanning'

function ConnectFlowFull({ onImport, onBack, onReset, initialConnectionId }: {
  onImport: (members: Member[], boardId: string, boardName: string, boardKey: string) => void
  onBack: () => void
  onReset: () => void
  initialConnectionId?: string
}) {
  // After OAuth lands back here, we already have a connection — start at project picker, not board.
  const [stage, setStage] = useState<ConnectStage>(initialConnectionId ? 'project' : 'connect')
  const [connectionId, setConnectionId] = useState(initialConnectionId ?? '')
  const [projectKey, setProjectKey] = useState('')
  const [boardId, setBoardId] = useState('')
  const [boardName, setBoardName] = useState('')
  const [boardKey, setBoardKey] = useState('')

  function onConnected(id: string) {
    setConnectionId(id)
    setStage('project')
  }

  function onProjectSelected(p: { key: string; connection_id: string }) {
    setProjectKey(p.key)
    // Narrow from possibly-multi connection_ids down to the single connection that owns this project.
    setConnectionId(p.connection_id)
    setStage('board')
  }

  function onBoardSelected(board: { id: string; name: string; project_key: string; connection_id: string }) {
    setBoardId(board.id)
    setBoardName(board.name)
    setBoardKey(board.project_key || projectKey)
    setConnectionId(board.connection_id)
    setStage('scanning')
  }

  if (stage === 'connect') return <ConnectScreen onConnected={onConnected} onBack={onBack} />
  if (stage === 'project') return (
    <ProjectPickerInner
      connectionId={connectionId}
      onPick={onProjectSelected}
      onBack={() => setStage('connect')}
    />
  )
  if (stage === 'board') return (
    <BoardPickerInner
      connectionId={connectionId}
      projectKey={projectKey}
      onImport={onBoardSelected}
      onBack={() => setStage('project')}
    />
  )
  return (
    <ScanningScreen
      boardId={boardId} boardName={boardName} boardKey={boardKey} connectionId={connectionId}
      onDone={members => onImport(members, boardId, boardName, boardKey)}
      onReset={onReset}
    />
  )
}

interface JiraProject { id: string; key: string; name: string; connection_id: string }

function ProjectPickerInner({ connectionId, onPick, onBack }: {
  connectionId: string
  onPick: (p: JiraProject) => void
  onBack: () => void
}) {
  const { get } = useApi()
  const [projects, setProjects] = useState<JiraProject[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [sel, setSel] = useState<string>('')

  useEffect(() => {
    setLoading(true)
    setError(null)
    const isMulti = connectionId.includes(',')
    const param = isMulti
      ? `connection_ids=${encodeURIComponent(connectionId)}`
      : `connection_id=${encodeURIComponent(connectionId)}`
    get<JiraProject[]>(`/api/integrations/jira/projects?${param}`)
      .then(data => {
        setProjects(data)
        if (data.length > 0) setSel(data[0].key)
      })
      .catch(e => setError(e.message || 'Failed to load projects'))
      .finally(() => setLoading(false))
  }, [connectionId])

  const selected = projects.find(p => p.key === sel)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18, animation: 'fadeUp 0.22s ease both' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, fontWeight: 600, color: C.success, background: C.successBg, border: `1px solid ${C.success}`, padding: '3px 10px', borderRadius: 20 }}>
          <svg width="10" height="10" viewBox="0 0 8 8"><path d="M1 4 L3 6 L7 1" stroke={C.success} strokeWidth="1.6" fill="none" strokeLinecap="round" strokeLinejoin="round" /></svg>
          Jira connected
        </span>
      </div>
      <div>
        <h2 style={{ fontSize: 21, fontWeight: 700, color: C.t1, letterSpacing: '-0.3px', marginBottom: 5 }}>Which Jira project is your team working in?</h2>
        <p style={{ fontSize: 14, color: C.t2, lineHeight: 1.55 }}>Pick a project and we'll show you the boards inside it next.</p>
      </div>

      {loading && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '24px 0', color: C.t3, fontSize: 14 }}>
          <div style={{ width: 18, height: 18, border: `2px solid ${C.accent}`, borderTopColor: 'transparent', borderRadius: '50%', animation: 'spin 0.8s linear infinite' }} />
          Loading projects…
        </div>
      )}
      {error && (
        <div style={{ background: '#fef2f2', border: '1px solid #fca5a5', borderRadius: 8, padding: '14px 16px', fontSize: 13, color: '#dc2626' }}>
          <strong>Couldn't load projects:</strong> {error}
        </div>
      )}
      {!loading && !error && projects.length === 0 && (
        <div style={{ background: C.bg1, border: `1px solid ${C.border}`, borderRadius: 8, padding: '20px', textAlign: 'center', color: C.t3, fontSize: 14 }}>
          No projects found in this Jira account. Make sure you have access to at least one project, then reconnect.
        </div>
      )}
      {!loading && projects.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
          {projects.map(p => {
            const isSel = sel === p.key
            return (
              <button key={p.id} onClick={() => setSel(p.key)} style={{
                width: '100%', textAlign: 'left', display: 'flex', alignItems: 'center', gap: 13, cursor: 'pointer',
                background: isSel ? C.accentSubtle : C.bg0, border: `1.5px solid ${isSel ? C.accent : C.border}`, borderRadius: 10, padding: '13px 14px', transition: 'all .12s',
              }}>
                <div style={{ width: 18, height: 18, borderRadius: '50%', flexShrink: 0, border: `1.5px solid ${isSel ? C.accent : C.borderStrong}`, background: isSel ? C.accent : 'transparent', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  {isSel && <span style={{ width: 7, height: 7, borderRadius: '50%', background: '#fff' }} />}
                </div>
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div style={{ fontSize: 14, fontWeight: 600, color: C.t1, marginBottom: 2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{p.name}</div>
                  <div style={{ fontFamily: 'monospace', fontSize: 11, color: C.t2, background: C.bg3, padding: '1px 5px', borderRadius: 4, display: 'inline-block' }}>{p.key}</div>
                </div>
              </button>
            )
          })}
        </div>
      )}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', paddingTop: 4 }}>
        <Btn variant="ghost" onClick={onBack}>← Back</Btn>
        <Btn onClick={() => { if (selected) onPick(selected) }} disabled={!selected || loading}>Next →</Btn>
      </div>
    </div>
  )
}

function BoardPickerInner({ connectionId, projectKey, onImport, onBack }: {
  connectionId: string
  projectKey: string
  onImport: (board: Board) => void
  onBack: () => void
}) {
  const { get } = useApi()
  const [boards, setBoards] = useState<Board[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [sel, setSel] = useState<string>('')

  useEffect(() => {
    setLoading(true)
    setError(null)
    const isMulti = connectionId.includes(',')
    const connParam = isMulti
      ? `connection_ids=${encodeURIComponent(connectionId)}`
      : `connection_id=${encodeURIComponent(connectionId)}`
    get<Board[]>(`/api/integrations/jira/boards?${connParam}&project_key=${encodeURIComponent(projectKey)}`)
      .then(data => {
        const withRec = data.map((b, i) => ({ ...b, recommended: i === 0 }))
        setBoards(withRec)
        if (withRec.length > 0) setSel(withRec[0].id)
      })
      .catch(e => setError(e.message || 'Failed to load boards'))
      .finally(() => setLoading(false))
  }, [connectionId, projectKey])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18, animation: 'fadeUp 0.22s ease both' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, fontWeight: 600, color: C.success, background: C.successBg, border: `1px solid ${C.success}`, padding: '3px 10px', borderRadius: 20 }}>
          <svg width="10" height="10" viewBox="0 0 8 8"><path d="M1 4 L3 6 L7 1" stroke={C.success} strokeWidth="1.6" fill="none" strokeLinecap="round" strokeLinejoin="round" /></svg>
          Jira connected
        </span>
      </div>
      <div>
        <h2 style={{ fontSize: 21, fontWeight: 700, color: C.t1, letterSpacing: '-0.3px', marginBottom: 5 }}>Which board is your team on?</h2>
        <p style={{ fontSize: 14, color: C.t2, lineHeight: 1.55 }}>We'll import the roster and sprint setup from the board you pick.</p>
      </div>

      {loading && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '24px 0', color: C.t3, fontSize: 14 }}>
          <div style={{ width: 18, height: 18, border: `2px solid ${C.accent}`, borderTopColor: 'transparent', borderRadius: '50%', animation: 'spin 0.8s linear infinite' }} />
          Loading boards…
        </div>
      )}
      {error && (() => {
        const isSuspended = /suspended|suspended-inactivity/i.test(error)
        return (
          <div style={{ background: '#fef2f2', border: '1px solid #fca5a5', borderRadius: 8, padding: '14px 16px', fontSize: 13, color: '#dc2626' }}>
            {isSuspended ? (
              <>
                <div style={{ fontWeight: 600, marginBottom: 5 }}>Jira site suspended</div>
                <div style={{ color: '#7f1d1d', lineHeight: 1.5 }}>
                  Your Jira cloud site has been suspended due to inactivity. Log in to{' '}
                  <span style={{ fontFamily: 'monospace' }}>admin.atlassian.com</span> to reactivate it, then reconnect here.
                </div>
              </>
            ) : (
              <><strong>Couldn't load boards:</strong> {error}</>
            )}
          </div>
        )
      })()}
      {!loading && !error && boards.length === 0 && (
        <div style={{ background: C.bg1, border: `1px solid ${C.border}`, borderRadius: 8, padding: '20px', color: C.t2, fontSize: 14, lineHeight: 1.55 }}>
          <div style={{ fontWeight: 600, color: C.t1, marginBottom: 6 }}>No boards in this project yet</div>
          Project <span style={{ fontFamily: 'monospace', fontSize: 12, color: C.t1, background: C.bg3, padding: '1px 5px', borderRadius: 4 }}>{projectKey}</span> doesn't have any Scrum or Kanban boards. Create one in Jira (Boards → Create board), then come back and pick it.
        </div>
      )}
      {!loading && boards.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
          {boards.map(b => {
            const selected = sel === b.id
            const isKanban = b.type?.toLowerCase() === 'kanban'
            return (
              <button key={b.id} onClick={() => setSel(b.id)} style={{
                width: '100%', textAlign: 'left', display: 'flex', alignItems: 'center', gap: 13, cursor: 'pointer',
                background: selected ? C.accentSubtle : C.bg0, border: `1.5px solid ${selected ? C.accent : C.border}`, borderRadius: 10, padding: '13px 14px', transition: 'all .12s',
              }}>
                <div style={{ width: 18, height: 18, borderRadius: '50%', flexShrink: 0, border: `1.5px solid ${selected ? C.accent : C.borderStrong}`, background: selected ? C.accent : 'transparent', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  {selected && <span style={{ width: 7, height: 7, borderRadius: '50%', background: '#fff' }} />}
                </div>
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 2 }}>
                    <span style={{ fontSize: 14, fontWeight: 600, color: C.t1, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{b.name}</span>
                    {b.recommended && <span style={{ fontSize: 10, fontWeight: 700, color: WARM.accent, background: WARM.accentBg, border: `1px solid ${WARM.accentBd}`, padding: '1px 7px', borderRadius: 20, whiteSpace: 'nowrap' }}>Most active</span>}
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: C.t3, flexWrap: 'wrap' }}>
                    {b.project_key && <span style={{ fontFamily: 'monospace', fontSize: 11, color: C.t2, background: C.bg3, padding: '1px 5px', borderRadius: 4 }}>{b.project_key}</span>}
                    {b.type && <span style={{ color: isKanban ? 'oklch(0.5 0.12 150)' : 'oklch(0.5 0.13 235)', fontWeight: 600 }}>{b.type}</span>}
                  </div>
                </div>
              </button>
            )
          })}
        </div>
      )}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', paddingTop: 4 }}>
        <Btn variant="ghost" onClick={onBack}>← Back to projects</Btn>
        <Btn
          onClick={() => {
            const b = boards.find(x => x.id === sel)
            if (b) onImport(b)
          }}
          disabled={!sel || loading}
        >
          Import team →
        </Btn>
      </div>
    </div>
  )
}

// ─── ConfirmTeamStep ──────────────────────────────────────────────────────────
function ConfirmTeamStep({ boardName, teamName, onRenameTeam, members, onUpdate, onExclude, onInclude, onAdd, onBack, onNext }: {
  boardName: string; teamName: string; onRenameTeam: (n: string) => void;
  members: Member[]; onUpdate: (i: number, patch: Partial<Member>) => void;
  onExclude: (i: number) => void; onInclude: (i: number) => void; onAdd: (m: Member) => void;
  onBack: () => void; onNext: () => void
}) {
  const [editorIdx, setEditorIdx] = useState<number | 'new' | null>(null)
  const [showExcluded, setShowExcluded] = useState(false)
  const withIdx = members.map((member, index) => ({ member, index }))
  const included = withIdx.filter(x => x.member.included !== false)
  const excluded = withIdx.filter(x => x.member.included === false)
  const totalCap = included.reduce((s, x) => s + (Number(x.member.capacity) || 0), 0)

  function saveEditor(m: Member) {
    if (editorIdx === 'new') onAdd({ ...m, included: true })
    else if (editorIdx !== null) onUpdate(editorIdx, m)
    setEditorIdx(null)
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18, animation: 'fadeUp 0.22s ease both' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, fontWeight: 600, color: C.success, background: C.successBg, border: `1px solid ${C.success}`, padding: '3px 10px', borderRadius: 20 }}>
          <svg width="10" height="10" viewBox="0 0 8 8"><path d="M1 4 L3 6 L7 1" stroke={C.success} strokeWidth="1.6" fill="none" strokeLinecap="round" strokeLinejoin="round" /></svg>
          Imported from Jira
        </span>
      </div>

      <div>
        <h2 style={{ fontSize: 21, fontWeight: 700, color: C.t1, letterSpacing: '-0.3px', marginBottom: 5 }}>We found your team</h2>
        <p style={{ fontSize: 14, color: C.t2, lineHeight: 1.55 }}>Confirm who's on the sprint team and set each person's weekly capacity — the one thing Jira can't tell us. Everything else is optional.</p>
      </div>

      <div style={{ background: WARM.surface, border: `1px solid ${C.border}`, borderRadius: 12, padding: '13px 15px', display: 'flex', flexWrap: 'wrap', gap: 16, alignItems: 'center' }}>
        <div style={{ flex: '1 1 180px', minWidth: 160 }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: C.t3, textTransform: 'uppercase', letterSpacing: '.06em', marginBottom: 4 }}>Team name</div>
          <input value={teamName} onChange={e => onRenameTeam(e.target.value)} style={{ width: '100%', border: '1px solid transparent', background: 'transparent', fontSize: 15, fontWeight: 700, color: C.t1, borderRadius: 6, padding: '3px 6px', marginLeft: -6 }}
            onFocus={e => (e.target.style.background = C.bg0)} onBlur={e => (e.target.style.background = 'transparent')} />
        </div>
        {boardName && (
          <div>
            <div style={{ fontSize: 10, fontWeight: 700, color: C.t3, textTransform: 'uppercase', letterSpacing: '.06em', marginBottom: 4 }}>Source</div>
            <div style={{ fontSize: 14, fontWeight: 600, color: C.t1 }}>{boardName}</div>
          </div>
        )}
      </div>

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: C.t1 }}>{included.length} on the team</div>
        <div style={{ fontSize: 12, color: C.t3 }}>{totalCap}h / week total capacity</div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 14 }}>
        {included.map(x => (
          <RosterCard key={x.index} member={x.member} index={x.index} onUpdate={onUpdate} onExclude={onExclude} onEditFull={idx => setEditorIdx(idx)} />
        ))}
        <button onClick={() => setEditorIdx('new')} style={{
          height: 250, borderRadius: 14, border: `1.5px dashed ${C.borderStrong}`, background: WARM.surface, cursor: 'pointer',
          display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 9, color: C.t2,
        }}
          onMouseEnter={e => { (e.currentTarget as HTMLElement).style.borderColor = C.accent; (e.currentTarget as HTMLElement).style.background = C.accentSubtle }}
          onMouseLeave={e => { (e.currentTarget as HTMLElement).style.borderColor = C.borderStrong; (e.currentTarget as HTMLElement).style.background = WARM.surface }}>
          <span style={{ width: 34, height: 34, borderRadius: '50%', border: `1.5px solid ${C.borderStrong}`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 20, lineHeight: '1', color: C.t3 }}>+</span>
          <span style={{ fontSize: 12.5, fontWeight: 600, textAlign: 'center', lineHeight: 1.3 }}>Add someone<br />Jira missed</span>
        </button>
      </div>

      {excluded.length > 0 && (
        <div>
          <button onClick={() => setShowExcluded(s => !s)} style={{ background: 'none', border: 'none', color: C.t2, fontSize: 12.5, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6, padding: 0 }}>
            <svg width="9" height="9" viewBox="0 0 10 10" style={{ transform: showExcluded ? 'rotate(180deg)' : 'none', transition: 'transform .15s' }}><path d="M1 3 L5 7 L9 3" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round" /></svg>
            Not on the team · {excluded.length}
            <span style={{ color: C.t3 }}>— we excluded these automatically</span>
          </button>
          {showExcluded && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 7, marginTop: 10, animation: 'fadeUp 0.22s ease both' }}>
              {excluded.map(x => <ExcludedRow key={x.index} member={x.member} index={x.index} onInclude={onInclude} />)}
            </div>
          )}
        </div>
      )}

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', paddingTop: 6 }}>
        <Btn variant="ghost" onClick={onBack}>← Back</Btn>
        <Btn onClick={onNext} disabled={included.length === 0}>Review team →</Btn>
      </div>

      {editorIdx !== null && (
        <MemberEditor
          initial={editorIdx === 'new' ? {} : members[editorIdx as number]}
          titleText={editorIdx === 'new' ? 'Add teammate' : 'Edit teammate'}
          saveLabel={editorIdx === 'new' ? 'Add to team' : 'Save'}
          onSave={saveEditor} onClose={() => setEditorIdx(null)}
        />
      )}
    </div>
  )
}

// ─── ReviewStep ───────────────────────────────────────────────────────────────
function ReviewMemberRow({ member }: { member: Member }) {
  const hue = roleHue(member)
  const role = roleLabelOf(member)
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 13px', background: C.bg0, border: `1px solid ${C.border}`, borderRadius: 9 }}>
      <div style={{ width: 32, height: 32, borderRadius: '50%', flexShrink: 0, background: `oklch(0.95 0.03 ${hue})`, border: `1px solid oklch(0.86 0.05 ${hue})`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 12, fontWeight: 700, color: `oklch(0.42 0.1 ${hue})` }}>
        {(member.name || '?').split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase()}
      </div>
      <div style={{ minWidth: 0, flex: 1 }}>
        <div style={{ fontSize: 13.5, fontWeight: 600, color: C.t1, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{member.name}</div>
        <div style={{ fontSize: 12, color: C.t3 }}>
          {member.handle && <span style={{ fontFamily: 'monospace' }}>@{member.handle}</span>}
          {role ? <> · <span style={{ color: `oklch(0.5 0.12 ${hue})`, fontWeight: 600 }}>{role}</span></> : ''}
          {member.strengths?.length ? ` · ${member.strengths.length} strength${member.strengths.length > 1 ? 's' : ''}` : ''}
        </div>
      </div>
      <div style={{ fontSize: 13, fontWeight: 700, color: C.t1, flexShrink: 0 }}>{member.capacity}<span style={{ fontSize: 11, fontWeight: 500, color: C.t3 }}> h/wk</span></div>
    </div>
  )
}

function ReviewStep({ teamName, boardName, members, onBack, onDone, saving, error }: {
  teamName: string; boardName: string; members: Member[]; onBack: () => void; onDone: () => void; saving: boolean; error?: string | null
}) {
  const included = members.filter(m => m.included !== false)
  const totalCap = included.reduce((s, m) => s + (Number(m.capacity) || 0), 0)
  const stats = [
    { label: 'Team', value: teamName || '—' },
    { label: 'Source', value: boardName || '—' },
    { label: 'People', value: `${included.length}` },
    { label: 'Capacity', value: `${totalCap}h / wk` },
  ]
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 22, animation: 'fadeUp 0.22s ease both' }}>
      <div>
        <h2 style={{ fontSize: 21, fontWeight: 700, color: C.t1, letterSpacing: '-0.3px', marginBottom: 4 }}>Review &amp; start tracking</h2>
        <p style={{ fontSize: 14, color: C.t2 }}>This is what Omada will track. We'll sync sprint history from <strong style={{ color: C.t1 }}>{boardName || 'your board'}</strong> next.</p>
      </div>

      <div style={{ background: C.bg1, border: `1px solid ${C.border}`, borderRadius: 8, padding: '16px 20px', display: 'flex', gap: 22, flexWrap: 'wrap' }}>
        {stats.map(s => (
          <div key={s.label}>
            <div style={{ fontSize: 10, fontWeight: 600, color: C.t3, textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 4 }}>{s.label}</div>
            <div style={{ fontSize: 15, fontWeight: 700, color: C.t1 }}>{s.value}</div>
          </div>
        ))}
      </div>

      <div>
        <FieldLabel>{included.length} Member{included.length !== 1 ? 's' : ''}</FieldLabel>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
          {included.map((m, i) => <ReviewMemberRow key={i} member={m} />)}
        </div>
      </div>

      <div style={{ background: C.bg1, border: `1px solid ${C.border}`, borderRadius: 8, padding: '12px 16px', fontSize: 12, color: C.t2, lineHeight: 1.6 }}>
        <strong style={{ color: C.accent }}>Privacy by default.</strong> Individual velocity data is visible only to each developer. Team leads see aggregate trends only — never used for performance reviews.
      </div>

      {error && (
        <div style={{ background: '#fef2f2', border: '1px solid #fca5a5', borderRadius: 8, padding: '10px 14px', fontSize: 13, color: '#dc2626' }}>
          <strong>Couldn't save:</strong> {error}
        </div>
      )}

      <div style={{ display: 'flex', justifyContent: 'space-between', paddingTop: 4 }}>
        <Btn variant="ghost" onClick={onBack} disabled={saving}>← Back</Btn>
        <Btn size="lg" onClick={onDone} disabled={saving} style={{ display: 'inline-flex', alignItems: 'center', gap: 9 }}>
          {saving ? (
            <><span style={{ width: 14, height: 14, border: '2px solid rgba(255,255,255,0.5)', borderTopColor: '#fff', borderRadius: '50%', display: 'inline-block', animation: 'spin 0.8s linear infinite' }} /> Saving…</>
          ) : error ? <>Retry →</> : <>Sync sprint history →</>}
        </Btn>
      </div>
    </div>
  )
}

// ─── DoneStep ─────────────────────────────────────────────────────────────────
function DoneStep() {
  return (
    <div style={{ textAlign: 'center', padding: '32px 0', animation: 'fadeUp 0.22s ease both' }}>
      <div style={{ width: 56, height: 56, borderRadius: '50%', background: C.successBg, border: `1px solid ${C.success}`, display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 24px', fontSize: 24, color: C.success, animation: 'checkPop 0.3s ease both' }}>✓</div>
      <h2 style={{ fontSize: 22, fontWeight: 700, color: C.t1, marginBottom: 8 }}>You're all set!</h2>
      <p style={{ fontSize: 14, color: C.t2, lineHeight: 1.6, marginBottom: 32 }}>Omada is syncing your recent sprints to build velocity baselines for the team.</p>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, justifyContent: 'center', background: C.bg1, border: `1px solid ${C.border}`, borderRadius: 8, padding: '12px 20px', fontSize: 13, color: C.t2 }}>
        <div style={{ width: 16, height: 16, border: `2px solid ${C.accent}`, borderTopColor: 'transparent', borderRadius: '50%', animation: 'spin 0.8s linear infinite' }} />
        Importing sprint history…
      </div>
    </div>
  )
}

// ─── Layout A: Split sidebar ──────────────────────────────────────────────────
function SidebarStepper({ step }: { step: number }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ marginBottom: 48 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
          <div style={{ width: 30, height: 30, borderRadius: 7, background: C.accent, border: `1px solid ${C.accent}`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 14, fontWeight: 800, color: '#fff' }}>O</div>
          <span style={{ fontSize: 16, fontWeight: 700, color: C.t1 }}>Omada</span>
        </div>
        <div style={{ fontSize: 12, color: C.t3, paddingLeft: 40 }}>Team setup</div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        {STEP_LBLS.map((label, i) => {
          const done = step > i
          const cur = step === i
          return (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '7px 0' }}>
              <div style={{ width: 22, height: 22, borderRadius: '50%', flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', background: done ? C.accent : cur ? C.accentSubtle : 'transparent', border: `1px solid ${done ? C.accent : cur ? C.accent : C.border}`, fontSize: 10, fontWeight: 700, color: done ? '#fff' : cur ? C.accent : C.t3 }}>{done ? '✓' : i + 1}</div>
              <span style={{ fontSize: 13, fontWeight: cur ? 600 : 400, color: cur ? C.t1 : done ? C.t2 : C.t3 }}>{label}</span>
            </div>
          )
        })}
      </div>

      {step >= 0 && step <= 2 && (
        <div style={{ marginTop: 'auto', paddingTop: 32 }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: C.t3, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 8 }}>Why we ask</div>
          <p style={{ fontSize: 12, color: C.t3, lineHeight: 1.65 }}>{WHY[step]}</p>
        </div>
      )}
    </div>
  )
}

// ─── Main page ────────────────────────────────────────────────────────────────
export function OnboardingPage() {
  const navigate = useNavigate()
  const { post } = useApi()
  const [searchParams, setSearchParams] = useSearchParams()

  // Detect OAuth callback: ?connection_id or ?pending_sites means the user
  // just returned from Atlassian. Skip the welcome screen and go straight to
  // board picker, passing the connection ID so ConnectFlowFull starts at 'board'.
  const callbackConnectionId = (() => {
    const connId = searchParams.get('connection_id')
    if (connId) return connId
    const pending = searchParams.get('pending_sites')
    if (pending) return pending.split(',').map(e => e.split('|')[0]).join(',')
    return null
  })()

  const [step, setStep] = useState(callbackConnectionId ? 0 : -1)
  const [oauthConnectionId] = useState(callbackConnectionId)
  const [teamName, setTeamName] = useState('')
  const [boardName, setBoardName] = useState('')
  const [members, setMembers] = useState<Member[]>([])
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  // Clear the OAuth params from the URL so they don't linger.
  useEffect(() => {
    if (callbackConnectionId) {
      setSearchParams({}, { replace: true })
    }
  }, [])

  const stepperIdx = Math.max(0, Math.min(2, step))

  function onImport(imported: Member[], _boardId: string, bName: string, _bKey: string) {
    setBoardName(bName)
    setTeamName(bName.replace(/\s*(Sprint\s*)?Board$/i, '').trim() || bName)
    setMembers(imported)
    setStep(1)
  }

  function addMember(m: Member) { setMembers(p => [...p, m]) }
  function updateMember(i: number, patch: Partial<Member>) { setMembers(p => p.map((m, j) => j === i ? { ...m, ...patch } : m)) }
  function excludeMember(i: number) { updateMember(i, { included: false }) }
  function includeMember(i: number) { updateMember(i, { included: true }) }

  async function handleDone() {
    setSaving(true)
    setSaveError(null)
    try {
      const included = members.filter(m => m.included !== false)
      await post('/api/onboarding/confirm-team', {
        members: included.map(m => ({
          name: m.name,
          jiraAccountId: m.jira_account_id,
          capacity: m.capacity,
          role: m.role || null,
          seniority: m.seniority || null,
          strengths: m.strengths.length > 0 ? m.strengths : null,
          meetings: m.meetings || null,
          email: m.email || null,
        })),
      })
    } catch (err) {
      setSaving(false)
      setSaveError((err as any)?.response?.data?.detail ?? (err instanceof Error ? err.message : 'Failed to save team. Please try again.'))
      return
    }
    setSaving(false)
    setStep(99)
    setTimeout(() => navigate('/app/sprint-planner'), 1500)
  }

  return (
    <div style={{ display: 'flex', minHeight: '100vh', fontFamily: "'Inter', system-ui, sans-serif", WebkitFontSmoothing: 'antialiased' }}>
      {/* Sidebar */}
      <div style={{ width: 238, flexShrink: 0, background: C.bg0, borderRight: `1px solid ${C.border}`, padding: '36px 28px' }}>
        <SidebarStepper step={stepperIdx} />
      </div>

      {/* Main content */}
      <div style={{ flex: 1, background: C.bg1, overflowY: 'auto', display: 'flex', alignItems: 'flex-start', justifyContent: 'center', padding: '52px 52px' }}>
        <div style={{ width: '100%', maxWidth: 580 }}>
          {step === -1 && <WelcomeStep onStart={() => setStep(0)} />}
          {step === 0 && (
            <ConnectFlowFull
              onImport={onImport}
              onBack={() => setStep(-1)}
              onReset={async () => {
                try { await post('/api/onboarding/reset', {}) } catch { /* best-effort */ }
                setStep(-1)
              }}
              initialConnectionId={oauthConnectionId ?? undefined}
            />
          )}
          {step === 1 && (
            <ConfirmTeamStep
              boardName={boardName}
              teamName={teamName}
              onRenameTeam={setTeamName}
              members={members}
              onUpdate={updateMember}
              onExclude={excludeMember}
              onInclude={includeMember}
              onAdd={addMember}
              onBack={() => setStep(0)}
              onNext={() => setStep(2)}
            />
          )}
          {step === 2 && (
            <ReviewStep
              teamName={teamName}
              boardName={boardName}
              members={members}
              onBack={() => setStep(1)}
              onDone={handleDone}
              saving={saving}
              error={saveError}
            />
          )}
          {step === 99 && <DoneStep />}
        </div>
      </div>
    </div>
  )
}
