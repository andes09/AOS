import { useState } from 'react'
import { MemberDraft, TeamDraft } from './types'
import { JiraBoard } from './data'
import { RosterCard } from './RosterCard'
import { MemberEditor } from './MemberEditor'

interface ConfirmTeamStepProps {
  board: JiraBoard
  team: TeamDraft
  onRenameTeam: (name: string) => void
  members: MemberDraft[]
  onUpdate: (i: number, patch: Partial<MemberDraft>) => void
  onExclude: (i: number) => void
  onInclude: (i: number) => void
  onAdd: (m: MemberDraft) => void
  onBack: () => void
  onNext: () => void
}

function ExcludedRow({ member, index, onInclude }: { member: MemberDraft; index: number; onInclude: (i: number) => void }) {
  const initials = (member.name || '?').split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase()
  const hue = (member.name || '').split('').reduce((a, c) => a + c.charCodeAt(0), 0) % 360
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 11px', background: '#f7f8fa', border: '1px solid #e3e6eb', borderRadius: 9 }}>
      <div style={{
        width: 28, height: 28, borderRadius: '50%', flexShrink: 0,
        background: `oklch(0.94 0.02 ${hue})`, border: `1px solid oklch(0.86 0.04 ${hue})`,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: 10, fontWeight: 600, color: `oklch(0.38 0.08 ${hue})`,
      }}>{initials}</div>
      <div style={{ minWidth: 0, flex: 1 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: '#5b6470', display: 'flex', alignItems: 'center', gap: 7 }}>
          {member.name}
          {member.bot && (
            <span style={{ fontSize: 9.5, fontWeight: 700, color: '#8a93a0', background: '#f0f2f5', border: '1px solid #e3e6eb', padding: '1px 6px', borderRadius: 20, letterSpacing: '.03em' }}>
              APP ACCOUNT
            </span>
          )}
        </div>
        {member.handle && (
          <div style={{ fontSize: 11.5, color: '#8a93a0', fontFamily: 'monospace' }}>@{member.handle}</div>
        )}
      </div>
      <button
        onClick={() => onInclude(index)}
        style={{ background: 'transparent', border: '1px solid #e3e6eb', borderRadius: 6, padding: '5px 11px', fontSize: 12, fontWeight: 600, color: '#5b6470', cursor: 'pointer' }}
      >Add to team</button>
    </div>
  )
}

export function ConfirmTeamStep({
  board, team, onRenameTeam, members, onUpdate, onExclude, onInclude, onAdd, onBack, onNext,
}: ConfirmTeamStepProps) {
  const [editorIdx, setEditorIdx] = useState<number | 'new' | null>(null)
  const [showExcluded, setShowExcluded] = useState(false)

  const withIdx = members.map((member, index) => ({ member, index }))
  const included = withIdx.filter(x => x.member.included !== false)
  const excluded = withIdx.filter(x => x.member.included === false)
  const totalCap = included.reduce((s, x) => s + (Number(x.member.capacity) || 0), 0)

  function saveEditor(m: MemberDraft) {
    if (editorIdx === 'new') onAdd({ ...m, included: true })
    else if (typeof editorIdx === 'number') onUpdate(editorIdx, m)
    setEditorIdx(null)
  }

  return (
    <div className="anim" style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
      {/* Imported badge */}
      <div>
        <span style={{
          display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12,
          fontWeight: 600, color: '#1f7a4d', background: '#e8f5ee',
          border: '1px solid #1f7a4d', padding: '3px 10px', borderRadius: 20,
        }}>
          <svg width="10" height="10" viewBox="0 0 8 8" fill="none">
            <path d="M1 4 L3 6 L7 1" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          Imported from Jira
        </span>
      </div>

      <div>
        <h2 style={{ fontSize: 21, fontWeight: 700, color: '#1a1d23', letterSpacing: '-0.3px', marginBottom: 5 }}>
          We found your team
        </h2>
        <p style={{ fontSize: 14, color: '#5b6470', lineHeight: 1.55 }}>
          Confirm who's on the sprint team and set each person's weekly capacity — the one thing Jira can't tell us. Everything else is optional.
        </p>
      </div>

      {/* Detected team meta */}
      <div style={{
        background: '#fcfbf9', border: '1px solid #e3e6eb', borderRadius: 12,
        padding: '13px 15px', display: 'flex', flexWrap: 'wrap', gap: 16, alignItems: 'center',
      }}>
        <div style={{ flex: '1 1 180px', minWidth: 160 }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: '#8a93a0', textTransform: 'uppercase', letterSpacing: '.06em', marginBottom: 4 }}>Team name</div>
          <input
            value={team.name}
            onChange={e => onRenameTeam(e.target.value)}
            style={{
              width: '100%', border: '1px solid transparent', background: 'transparent',
              fontSize: 15, fontWeight: 700, color: '#1a1d23', borderRadius: 6, padding: '3px 6px', marginLeft: -6,
              outline: 'none',
            }}
            onFocus={e => (e.target.style.background = '#fff')}
            onBlur={e => (e.target.style.background = 'transparent')}
          />
        </div>
        {[['Source', board.name], ['Methodology', board.methodology], ['Cadence', board.cadence]].map(([k, v]) => (
          <div key={k}>
            <div style={{ fontSize: 10, fontWeight: 700, color: '#8a93a0', textTransform: 'uppercase', letterSpacing: '.06em', marginBottom: 4 }}>{k}</div>
            <div style={{ fontSize: 14, fontWeight: 600, color: '#1a1d23' }}>{v}</div>
          </div>
        ))}
      </div>

      {/* Roster count + capacity */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: '#1a1d23' }}>{included.length} on the team</div>
        <div style={{ fontSize: 12, color: '#8a93a0' }}>{totalCap}h / week total capacity</div>
      </div>

      {/* Player cards grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 14 }}>
        {included.map(x => (
          <RosterCard
            key={x.index}
            member={x.member}
            index={x.index}
            onUpdate={onUpdate}
            onExclude={onExclude}
            onEditFull={idx => setEditorIdx(idx)}
          />
        ))}

        {/* Add tile */}
        <button
          onClick={() => setEditorIdx('new')}
          style={{
            height: 250, borderRadius: 14, border: '1.5px dashed #c9cfd8',
            background: '#fcfbf9', cursor: 'pointer',
            display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 9,
            color: '#5b6470', transition: 'all .12s',
          }}
          onMouseEnter={e => {
            const el = e.currentTarget as HTMLElement
            el.style.borderColor = '#1a1d23'
            el.style.background = '#eef0f3'
          }}
          onMouseLeave={e => {
            const el = e.currentTarget as HTMLElement
            el.style.borderColor = '#c9cfd8'
            el.style.background = '#fcfbf9'
          }}
        >
          <span style={{ width: 34, height: 34, borderRadius: '50%', border: '1.5px solid #c9cfd8', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 20, lineHeight: 1, color: '#8a93a0' }}>+</span>
          <span style={{ fontSize: 12.5, fontWeight: 600, textAlign: 'center', lineHeight: 1.3 }}>
            Add someone<br />Jira missed
          </span>
        </button>
      </div>

      {/* Excluded */}
      {excluded.length > 0 && (
        <div>
          <button
            onClick={() => setShowExcluded(s => !s)}
            style={{ background: 'none', border: 'none', color: '#5b6470', fontSize: 12.5, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6, padding: 0 }}
          >
            <svg width="9" height="9" viewBox="0 0 10 10" style={{ transform: showExcluded ? 'rotate(180deg)' : 'none', transition: 'transform .15s' }}>
              <path d="M1 3 L5 7 L9 3" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            Not on the team · {excluded.length}
            <span style={{ color: '#8a93a0' }}>— we excluded these automatically</span>
          </button>
          {showExcluded && (
            <div className="anim" style={{ display: 'flex', flexDirection: 'column', gap: 7, marginTop: 10 }}>
              {excluded.map(x => (
                <ExcludedRow key={x.index} member={x.member} index={x.index} onInclude={onInclude} />
              ))}
            </div>
          )}
        </div>
      )}

      {/* Footer nav */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', paddingTop: 6 }}>
        <button
          onClick={onBack}
          style={{ background: 'transparent', border: 'none', color: '#5b6470', fontSize: 13, fontWeight: 500, cursor: 'pointer', padding: '7px 0' }}
        >← Back</button>
        <button
          onClick={() => { if (included.length > 0) onNext() }}
          disabled={included.length === 0}
          style={{
            padding: '9px 20px', fontSize: 13, fontWeight: 600, border: 'none', borderRadius: 8,
            background: included.length > 0 ? '#1a1d23' : '#e3e6eb',
            color: included.length > 0 ? '#fff' : '#8a93a0',
            cursor: included.length > 0 ? 'pointer' : 'not-allowed', transition: 'all .12s',
          }}
        >Review team →</button>
      </div>

      {/* Member editor modal */}
      {editorIdx !== null && (
        <MemberEditor
          initial={editorIdx === 'new' ? {} : members[editorIdx as number]}
          titleText={editorIdx === 'new' ? 'Add teammate' : 'Edit teammate'}
          saveLabel={editorIdx === 'new' ? 'Add to team' : 'Save'}
          onSave={saveEditor}
          onClose={() => setEditorIdx(null)}
        />
      )}
    </div>
  )
}
