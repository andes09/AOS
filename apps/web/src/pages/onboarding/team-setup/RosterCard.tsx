import { useState } from 'react'
import { MemberDraft } from './types'
import { ROLES, QUICK_ROLES, roleHue, roleLabelOf } from './data'

interface RosterCardProps {
  member: MemberDraft
  index: number
  onUpdate: (i: number, patch: Partial<MemberDraft>) => void
  onExclude: (i: number) => void
  onEditFull: (i: number) => void
}

function CapacityStepper({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  const set = (v: number) => onChange(Math.max(5, Math.min(60, v)))
  const btn: React.CSSProperties = {
    width: 24, height: 24, borderRadius: 6, border: '1px solid #e3e6eb', background: '#fff',
    cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
    color: '#5b6470', fontSize: 15, lineHeight: 1, flexShrink: 0,
  }
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
      <button
        onClick={e => { e.stopPropagation(); set(value - 5) }}
        style={btn}
      >−</button>
      <div style={{ flex: 1, textAlign: 'center', fontSize: 13, fontWeight: 700, color: '#1a1d23' }}>
        {value}<span style={{ fontSize: 11, fontWeight: 500, color: '#8a93a0' }}> h/wk</span>
      </div>
      <button
        onClick={e => { e.stopPropagation(); set(value + 5) }}
        style={btn}
      >+</button>
    </div>
  )
}

export function RosterCard({ member, index, onUpdate, onExclude, onEditFull }: RosterCardProps) {
  const [flip, setFlip] = useState(false)
  const [hover, setHover] = useState(false)
  const hue = roleHue(member.role, member.customRole, member.name)
  const role = roleLabelOf(member.role, member.customRole)

  const initials = (member.name || '?').split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase()

  const faceBase: React.CSSProperties = {
    position: 'absolute', inset: 0, borderRadius: 14, overflow: 'hidden',
    backfaceVisibility: 'hidden', WebkitBackfaceVisibility: 'hidden' as never,
    border: '1px solid #e3e6eb', background: '#fff',
  }

  return (
    <div
      className="anim"
      style={{ perspective: 1000, height: 250 }}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
    >
      <div style={{
        position: 'relative', width: '100%', height: '100%',
        transformStyle: 'preserve-3d',
        transition: 'transform .55s cubic-bezier(.4,.1,.2,1), box-shadow .2s',
        transform: `${flip ? 'rotateY(180deg)' : 'rotateY(0)'} translateY(${hover ? -3 : 0}px)`,
        boxShadow: hover ? '0 16px 30px rgba(15,18,25,0.14)' : '0 2px 6px rgba(15,18,25,0.06)',
        borderRadius: 14,
      }}>

        {/* ── FRONT ── */}
        <div style={{ ...faceBase, opacity: flip ? 0 : 1, pointerEvents: flip ? 'none' : 'auto', transition: 'opacity 0s linear .27s' }}>
          {/* Color header */}
          <div style={{
            height: 70,
            background: `linear-gradient(135deg, oklch(0.66 0.13 ${hue}), oklch(0.5 0.16 ${hue}))`,
            position: 'relative',
          }}>
            <div style={{
              position: 'absolute', inset: 0,
              background: 'linear-gradient(115deg, rgba(255,255,255,.28) 0%, rgba(255,255,255,0) 42%)',
              opacity: hover ? 0.9 : 0.5, transition: 'opacity .3s',
            }} />
            <span style={{
              position: 'absolute', top: 10, left: 12,
              fontSize: 11, fontWeight: 600, color: 'rgba(255,255,255,.95)', fontFamily: 'monospace',
            }}>@{member.handle || 'member'}</span>
            {hover && (
              <button
                onClick={e => { e.stopPropagation(); onExclude(index) }}
                title="Not on this team"
                style={{
                  position: 'absolute', top: 7, right: 8,
                  background: 'rgba(0,0,0,.18)', border: 'none', color: '#fff',
                  cursor: 'pointer', fontSize: 15, lineHeight: 1, borderRadius: '50%', width: 20, height: 20,
                }}
              >×</button>
            )}
          </div>

          {/* Card body */}
          <div style={{ padding: '0 12px 11px', height: 'calc(100% - 70px)', display: 'flex', flexDirection: 'column' }}>
            <div style={{
              marginTop: -22, marginBottom: 5,
              display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between',
            }}>
              <div style={{
                width: 46, height: 46, borderRadius: '50%',
                background: `oklch(0.96 0.03 ${hue})`, border: '3px solid #fff',
                boxShadow: '0 2px 5px rgba(15,18,25,0.12)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 16, fontWeight: 700, color: `oklch(0.42 0.11 ${hue})`,
              }}>{initials}</div>
              {member.issues != null && (
                <span style={{ fontSize: 10.5, color: '#8a93a0', marginBottom: 2 }}>{member.issues} issues</span>
              )}
            </div>

            <div style={{ fontSize: 14, fontWeight: 700, color: '#1a1d23', lineHeight: 1.15, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {member.name}
            </div>
            <div style={{ fontSize: 11.5, marginTop: 1, fontWeight: role ? 600 : 400, color: role ? `oklch(0.5 0.12 ${hue})` : '#8a93a0' }}>
              {role || 'Role optional'}
            </div>

            <div style={{ marginTop: 'auto', display: 'flex', flexDirection: 'column', gap: 7 }}>
              <CapacityStepper value={member.capacity} onChange={v => onUpdate(index, { capacity: v })} />
              <button
                onClick={e => { e.stopPropagation(); setFlip(true) }}
                style={{
                  background: 'none', border: 'none',
                  color: `oklch(0.5 0.13 ${hue})`, fontSize: 11, fontWeight: 600,
                  cursor: 'pointer', padding: 0, alignSelf: 'center',
                }}
              >Flip to enrich ↻</button>
            </div>
          </div>
        </div>

        {/* ── BACK ── */}
        <div style={{
          ...faceBase,
          transform: 'rotateY(180deg)',
          background: `oklch(0.985 0.012 ${hue})`,
          opacity: flip ? 1 : 0,
          pointerEvents: flip ? 'auto' : 'none',
          transition: 'opacity 0s linear .27s',
        }}>
          <div style={{ padding: '11px 12px', height: '100%', display: 'flex', flexDirection: 'column' }}>
            <div style={{
              fontSize: 10, fontWeight: 700, letterSpacing: '.06em', textTransform: 'uppercase',
              color: `oklch(0.5 0.12 ${hue})`, marginBottom: 7,
            }}>
              Quick role <span style={{ fontWeight: 400, textTransform: 'none', letterSpacing: 0, color: '#8a93a0' }}>· optional</span>
            </div>

            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
              {QUICK_ROLES.map(rid => {
                const r = ROLES.find(x => x.id === rid)
                if (!r) return null
                const sel = member.role === rid
                return (
                  <button
                    key={rid}
                    onClick={() => onUpdate(index, { role: sel ? '' : rid, customRole: '' })}
                    style={{
                      fontSize: 10.5, fontWeight: 500, padding: '3px 8px', borderRadius: 20, cursor: 'pointer',
                      border: `1px solid ${sel ? `oklch(0.55 0.13 ${hue})` : '#e3e6eb'}`,
                      background: sel ? '#fff' : 'transparent',
                      color: sel ? `oklch(0.42 0.12 ${hue})` : '#5b6470',
                    }}
                  >{r.label}</button>
                )
              })}
            </div>

            <div style={{
              marginTop: 'auto', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              borderTop: `1px solid oklch(0.9 0.03 ${hue})`, paddingTop: 9,
            }}>
              <button
                onClick={() => onEditFull(index)}
                style={{ background: 'none', border: 'none', color: '#1a1d23', fontSize: 11, fontWeight: 600, cursor: 'pointer', padding: 0 }}
              >+ Strengths &amp; detail</button>
              <button
                onClick={() => setFlip(false)}
                style={{ background: 'none', border: 'none', color: `oklch(0.5 0.13 ${hue})`, fontSize: 11, fontWeight: 600, cursor: 'pointer', padding: 0 }}
              >↻ Back</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
