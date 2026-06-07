import { useState, useEffect } from 'react'
import { JIRA_BOARDS, JIRA_PEOPLE, boardById } from './data'

interface JiraConnectStepProps {
  onImport: (boardId: string) => void
  onBack: () => void
}

function JiraMark({ size = 40 }: { size?: number }) {
  return (
    <div style={{
      width: size, height: size, borderRadius: size * 0.26,
      background: 'linear-gradient(160deg, #2684FF, #0052CC)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      flexShrink: 0, boxShadow: '0 2px 6px rgba(0,82,204,0.3)',
    }}>
      <svg width={size * 0.56} height={size * 0.56} viewBox="0 0 24 24" fill="none">
        <path d="M11.5 2 L20 10.5 a2 2 0 0 1 0 3 L11.5 22 L7 17.5 a2 2 0 0 1 0-3 L11.5 10 L8.5 7 a2 2 0 0 1 0-3 Z" fill="#fff" opacity="0.95" />
      </svg>
    </div>
  )
}

function OmadaMark({ size = 40 }: { size?: number }) {
  return (
    <div style={{
      width: size, height: size, borderRadius: size * 0.26,
      background: '#1a1d23', flexShrink: 0,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontSize: size * 0.5, fontWeight: 800, color: '#fff', letterSpacing: '-1px',
    }}>O</div>
  )
}

// ── Connect screen ────────────────────────────────────────────────────────────

function ConnectScreen({ onAuthorize, busy }: { onAuthorize: () => void; busy: boolean }) {
  const scopes = [
    { title: 'View projects & boards', desc: 'Read your board names, types and sprint settings' },
    { title: 'View team members', desc: 'Read assignees on issues to build your roster' },
    { title: 'View sprint settings', desc: 'Detect your cadence and methodology' },
  ]

  return (
    <div className="anim" style={{ display: 'flex', flexDirection: 'column', gap: 22 }}>
      <div>
        <h2 style={{ fontSize: 21, fontWeight: 700, color: '#1a1d23', letterSpacing: '-0.3px', marginBottom: 5 }}>
          Connect your Jira workspace
        </h2>
        <p style={{ fontSize: 14, color: '#5b6470', lineHeight: 1.55 }}>
          Omada imports your team straight from the board you already work in — no forms to fill in.
        </p>
      </div>

      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 16,
        padding: '26px 0', background: '#fcfbf9', border: '1px solid #e3e6eb', borderRadius: 12,
      }}>
        <OmadaMark size={46} />
        <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
          {[0, 1, 2].map(i => <span key={i} style={{ width: 5, height: 5, borderRadius: '50%', background: '#c9cfd8', display: 'block' }} />)}
        </div>
        <JiraMark size={46} />
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        <div style={{ fontSize: 10, fontWeight: 700, color: '#8a93a0', letterSpacing: '.07em', textTransform: 'uppercase', marginBottom: 8 }}>
          Omada will be able to
        </div>
        {scopes.map(s => (
          <div key={s.title} style={{ display: 'flex', gap: 11, padding: '9px 0', borderBottom: '1px solid #edeff3' }}>
            <div style={{
              width: 18, height: 18, borderRadius: '50%', background: '#e8f5ee',
              border: '1px solid #1f7a4d', display: 'flex', alignItems: 'center',
              justifyContent: 'center', flexShrink: 0, marginTop: 1,
            }}>
              <svg width="9" height="9" viewBox="0 0 8 8" fill="none">
                <path d="M1 4 L3 6 L7 1" stroke="#1f7a4d" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
            <div>
              <div style={{ fontSize: 13.5, fontWeight: 600, color: '#1a1d23' }}>{s.title}</div>
              <div style={{ fontSize: 12.5, color: '#8a93a0', lineHeight: 1.4 }}>{s.desc}</div>
            </div>
          </div>
        ))}
      </div>

      <div style={{
        display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: '#5b6470',
        background: '#f7f8fa', borderRadius: 8, padding: '10px 12px',
      }}>
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#5b6470" strokeWidth="2">
          <rect x="4" y="11" width="16" height="10" rx="2" />
          <path d="M8 11V7a4 4 0 0 1 8 0v4" />
        </svg>
        <span><strong style={{ color: '#1a1d23', fontWeight: 600 }}>Read-only.</strong> Omada never writes to your boards, and you can revoke access anytime.</span>
      </div>

      <button
        onClick={onAuthorize}
        disabled={busy}
        style={{
          alignSelf: 'flex-start', display: 'inline-flex', alignItems: 'center', gap: 9,
          padding: '11px 26px', fontSize: 15, fontWeight: 600,
          border: 'none', borderRadius: 8,
          background: '#1a1d23', color: '#fff',
          cursor: busy ? 'wait' : 'pointer', opacity: busy ? 0.8 : 1,
          transition: 'opacity 0.12s',
        }}
      >
        {busy ? (
          <>
            <span style={{
              width: 14, height: 14, border: '2px solid rgba(255,255,255,0.4)',
              borderTopColor: '#fff', borderRadius: '50%',
              display: 'inline-block', animation: 'spin 0.8s linear infinite',
            }} />
            Connecting…
          </>
        ) : 'Authorize with Jira →'}
      </button>
    </div>
  )
}

// ── Board picker ──────────────────────────────────────────────────────────────

function BoardRow({ board, selected, onSelect }: {
  board: typeof JIRA_BOARDS[0]
  selected: boolean
  onSelect: (id: string) => void
}) {
  const isKanban = board.type === 'Kanban'
  const memberCount = (JIRA_PEOPLE as Record<string, unknown[]>)[board.id]?.length ?? 0

  return (
    <button
      onClick={() => onSelect(board.id)}
      style={{
        width: '100%', textAlign: 'left', display: 'flex', alignItems: 'center', gap: 13,
        cursor: 'pointer', background: selected ? '#eef0f3' : '#fff',
        border: `1.5px solid ${selected ? '#1a1d23' : '#e3e6eb'}`,
        borderRadius: 10, padding: '13px 14px', transition: 'all .12s',
      }}
    >
      <div style={{
        width: 18, height: 18, borderRadius: '50%', flexShrink: 0,
        border: `1.5px solid ${selected ? '#1a1d23' : '#c9cfd8'}`,
        background: selected ? '#1a1d23' : 'transparent',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}>
        {selected && <span style={{ width: 7, height: 7, borderRadius: '50%', background: '#fff', display: 'block' }} />}
      </div>
      <div style={{ minWidth: 0, flex: 1 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 2 }}>
          <span style={{ fontSize: 14, fontWeight: 600, color: '#1a1d23', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {board.name}
          </span>
          {board.recommended && (
            <span style={{
              fontSize: 10, fontWeight: 700, padding: '1px 7px', borderRadius: 20, whiteSpace: 'nowrap',
              color: 'oklch(0.56 0.11 45)', background: 'oklch(0.96 0.032 62)', border: '1px solid oklch(0.89 0.055 58)',
            }}>Most active</span>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: '#8a93a0', flexWrap: 'wrap' }}>
          <span style={{ fontFamily: 'monospace', fontSize: 11, color: '#5b6470', background: '#f0f2f5', padding: '1px 5px', borderRadius: 4 }}>{board.key}</span>
          <span style={{ fontWeight: 600, color: isKanban ? '#1f7a4d' : '#1a4db8' }}>{board.type}</span>
          <span>·</span><span>{memberCount} members</span>
          <span>·</span><span>{board.active}</span>
        </div>
      </div>
    </button>
  )
}

function BoardPicker({ onImport, onBack }: { onImport: (id: string) => void; onBack: () => void }) {
  const [sel, setSel] = useState('plat')

  return (
    <div className="anim" style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
        <span style={{
          display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12,
          fontWeight: 600, color: '#1f7a4d', background: '#e8f5ee',
          border: '1px solid #1f7a4d', padding: '3px 10px', borderRadius: 20,
        }}>
          <svg width="10" height="10" viewBox="0 0 8 8" fill="none">
            <path d="M1 4 L3 6 L7 1" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          Jira connected
        </span>
      </div>

      <div>
        <h2 style={{ fontSize: 21, fontWeight: 700, color: '#1a1d23', letterSpacing: '-0.3px', marginBottom: 5 }}>
          Which board is your team on?
        </h2>
        <p style={{ fontSize: 14, color: '#5b6470', lineHeight: 1.55 }}>
          We'll import the roster and sprint setup from the board you pick. You can add more later.
        </p>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
        {JIRA_BOARDS.map(b => (
          <BoardRow key={b.id} board={b} selected={sel === b.id} onSelect={setSel} />
        ))}
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', paddingTop: 4 }}>
        <button
          onClick={onBack}
          style={{ background: 'transparent', border: 'none', color: '#5b6470', fontSize: 13, fontWeight: 500, cursor: 'pointer', padding: '7px 0' }}
        >
          ← Back
        </button>
        <button
          onClick={() => onImport(sel)}
          style={{
            padding: '9px 20px', fontSize: 13, fontWeight: 600,
            border: 'none', borderRadius: 8, background: '#1a1d23', color: '#fff', cursor: 'pointer',
          }}
        >
          Import team →
        </button>
      </div>
    </div>
  )
}

// ── Scanning screen ───────────────────────────────────────────────────────────

function ScanningScreen({ boardId, onDone }: { boardId: string; onDone: () => void }) {
  const board = boardById(boardId)
  const memberCount = (JIRA_PEOPLE as Record<string, unknown[]>)[boardId]?.length ?? 0

  const steps = [
    'Reading board settings',
    `Detecting cadence — ${board.cadence} · ${board.methodology}`,
    `Importing ${memberCount} team members`,
    'Building velocity profiles',
  ]
  const [done, setDone] = useState(0)

  useEffect(() => {
    if (done < steps.length) {
      const t = setTimeout(() => setDone(d => d + 1), done === 0 ? 420 : 460)
      return () => clearTimeout(t)
    }
    const t = setTimeout(onDone, 520)
    return () => clearTimeout(t)
  }, [done])

  return (
    <div className="anim" style={{ display: 'flex', flexDirection: 'column', gap: 22, padding: '8px 0' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <JiraMark size={40} />
        <div>
          <div style={{ fontSize: 16, fontWeight: 700, color: '#1a1d23' }}>Scanning {board.name}</div>
          <div style={{ fontSize: 13, color: '#8a93a0', fontFamily: 'monospace' }}>{board.key}</div>
        </div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        {steps.map((s, i) => {
          const isDone = i < done
          const isCur = i === done
          return (
            <div key={i} style={{
              display: 'flex', alignItems: 'center', gap: 12, padding: '10px 0',
              opacity: i <= done ? 1 : 0.35, transition: 'opacity .3s',
            }}>
              <div style={{
                width: 22, height: 22, borderRadius: '50%', flexShrink: 0,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                background: isDone ? '#e8f5ee' : 'transparent',
                border: `1.5px solid ${isDone ? '#1f7a4d' : '#e3e6eb'}`,
              }}>
                {isDone && (
                  <svg width="10" height="10" viewBox="0 0 8 8" className="check-pop" fill="none">
                    <path d="M1 4 L3 6 L7 1" stroke="#1f7a4d" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                )}
                {isCur && (
                  <span style={{
                    width: 12, height: 12, border: '2px solid #1a1d23',
                    borderTopColor: 'transparent', borderRadius: '50%',
                    animation: 'spin 0.7s linear infinite', display: 'block',
                  }} />
                )}
              </div>
              <span style={{
                fontSize: 14, color: isDone ? '#1a1d23' : isCur ? '#1a1d23' : '#8a93a0',
                fontWeight: isCur ? 600 : 400,
              }}>{s}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Orchestrator ──────────────────────────────────────────────────────────────

export function JiraConnectStep({ onImport, onBack }: JiraConnectStepProps) {
  const [stage, setStage] = useState<'connect' | 'board' | 'scanning'>('connect')
  const [busy, setBusy] = useState(false)
  const [boardId, setBoardId] = useState('plat')

  function authorize() {
    setBusy(true)
    setTimeout(() => {
      setBusy(false)
      setStage('board')
    }, 1100)
  }

  function selectBoard(id: string) {
    setBoardId(id)
    setStage('scanning')
  }

  if (stage === 'connect') return <ConnectScreen onAuthorize={authorize} busy={busy} />
  if (stage === 'board')   return <BoardPicker onImport={selectBoard} onBack={onBack} />
  return <ScanningScreen boardId={boardId} onDone={() => onImport(boardId)} />
}
