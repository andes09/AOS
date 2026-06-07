import { MemberDraft, TeamDraft } from './types'
import { JiraBoard, roleHue, roleLabelOf } from './data'

interface ReviewStepProps {
  team: TeamDraft
  board: JiraBoard
  members: MemberDraft[]
  onBack: () => void
  onDone: () => void
  saving: boolean
}

function ReviewMemberRow({ member }: { member: MemberDraft }) {
  const hue = roleHue(member.role, member.customRole, member.name)
  const role = roleLabelOf(member.role, member.customRole)
  const initials = (member.name || '?').split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase()
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 13px', background: '#fff', border: '1px solid #e3e6eb', borderRadius: 9 }}>
      <div style={{
        width: 32, height: 32, borderRadius: '50%', flexShrink: 0,
        background: `oklch(0.95 0.03 ${hue})`, border: `1px solid oklch(0.86 0.05 ${hue})`,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: 12, fontWeight: 700, color: `oklch(0.42 0.1 ${hue})`,
      }}>{initials}</div>
      <div style={{ minWidth: 0, flex: 1 }}>
        <div style={{ fontSize: 13.5, fontWeight: 600, color: '#1a1d23', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
          {member.name}
        </div>
        <div style={{ fontSize: 12, color: '#8a93a0' }}>
          {member.handle && <span style={{ fontFamily: 'monospace' }}>@{member.handle}</span>}
          {role && <span> · <span style={{ color: `oklch(0.5 0.12 ${hue})`, fontWeight: 600 }}>{role}</span></span>}
          {member.strengths?.length ? ` · ${member.strengths.length} strength${member.strengths.length > 1 ? 's' : ''}` : ''}
        </div>
      </div>
      <div style={{ fontSize: 13, fontWeight: 700, color: '#1a1d23', flexShrink: 0 }}>
        {member.capacity}<span style={{ fontSize: 11, fontWeight: 500, color: '#8a93a0' }}> h/wk</span>
      </div>
    </div>
  )
}

export function ReviewStep({ team, board, members, onBack, onDone, saving }: ReviewStepProps) {
  const included = members.filter(m => m.included !== false)
  const totalCap = included.reduce((s, m) => s + (Number(m.capacity) || 0), 0)

  const stats = [
    { label: 'Team',     value: team.name || '—' },
    { label: 'Source',   value: board.name },
    { label: 'Method',   value: board.methodology },
    { label: 'Cadence',  value: board.cadence },
    { label: 'People',   value: `${included.length}` },
    { label: 'Capacity', value: `${totalCap}h / wk` },
  ]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 22 }}>
      <div>
        <h2 style={{ fontSize: 21, fontWeight: 700, color: '#1a1d23', letterSpacing: '-0.3px', marginBottom: 4 }}>
          Review &amp; start tracking
        </h2>
        <p style={{ fontSize: 14, color: '#5b6470', margin: 0 }}>
          This is what Omada will track. We'll sync sprint history from <strong style={{ color: '#1a1d23' }}>{board.name}</strong> next.
        </p>
      </div>

      {/* Stats bar */}
      <div style={{
        background: '#f7f8fa', border: '1px solid #e3e6eb', borderRadius: 8,
        padding: '16px 20px', display: 'flex', gap: 22, flexWrap: 'wrap',
      }}>
        {stats.map(s => (
          <div key={s.label}>
            <div style={{ fontSize: 10, fontWeight: 600, color: '#8a93a0', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 4 }}>{s.label}</div>
            <div style={{ fontSize: 15, fontWeight: 700, color: '#1a1d23' }}>{s.value}</div>
          </div>
        ))}
      </div>

      {/* Members */}
      <div>
        <div style={{ fontSize: 11, fontWeight: 600, color: '#8a93a0', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 10 }}>
          {included.length} Member{included.length !== 1 ? 's' : ''}
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
          {included.map((m, i) => <ReviewMemberRow key={i} member={m} />)}
        </div>
      </div>

      {/* Privacy note */}
      <div style={{ background: '#f7f8fa', border: '1px solid #e3e6eb', borderRadius: 8, padding: '12px 16px', fontSize: 12, color: '#5b6470', lineHeight: 1.6 }}>
        <strong style={{ color: '#1a1d23' }}>Privacy by default.</strong> Individual velocity data is visible only to each developer. Team leads see aggregate trends only — never used for performance reviews.
      </div>

      {/* Footer nav */}
      <div style={{ display: 'flex', justifyContent: 'space-between', paddingTop: 4 }}>
        <button
          onClick={onBack}
          disabled={saving}
          style={{
            background: 'transparent', border: 'none', color: '#5b6470',
            fontSize: 13, fontWeight: 500, cursor: saving ? 'not-allowed' : 'pointer',
            padding: '7px 0', opacity: saving ? 0.6 : 1,
          }}
        >← Back</button>
        <button
          onClick={onDone}
          disabled={saving}
          style={{
            padding: '11px 26px', fontSize: 15, fontWeight: 600,
            border: 'none', borderRadius: 8,
            background: '#1a1d23', color: '#fff',
            cursor: saving ? 'wait' : 'pointer',
            display: 'inline-flex', alignItems: 'center', gap: 8,
            opacity: saving ? 0.8 : 1, transition: 'opacity .12s',
          }}
        >
          {saving && (
            <span style={{
              width: 14, height: 14, border: '2px solid rgba(255,255,255,0.4)',
              borderTopColor: '#fff', borderRadius: '50%',
              animation: 'spin 0.7s linear infinite', display: 'inline-block',
            }} />
          )}
          {saving ? 'Saving…' : 'Sync sprint history →'}
        </button>
      </div>
    </div>
  )
}
