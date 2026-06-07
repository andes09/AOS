import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApi } from '../lib/api'
import { TeamDraft, MemberDraft } from './onboarding/team-setup/types'
import { STEP_LABELS, WHY, boardById, importRoster, deriveTeamName } from './onboarding/team-setup/data'
import { WelcomeStep } from './onboarding/team-setup/WelcomeStep'
import { JiraConnectStep } from './onboarding/team-setup/JiraConnectStep'
import { ConfirmTeamStep } from './onboarding/team-setup/ConfirmTeamStep'
import { ReviewStep } from './onboarding/team-setup/ReviewStep'

const STORAGE_KEY = 'aos_team_setup_step'

const defaultTeam: TeamDraft = {
  name: '',
  boardId: '',
  boardName: '',
  cadence: '',
  methodology: '',
  size: '',
  techStack: [],
}

function DoneStep({ onRestart }: { onRestart: () => void }) {
  return (
    <div className="anim" style={{ textAlign: 'center', padding: '32px 0' }}>
      <div className="check-pop" style={{
        width: 56, height: 56, borderRadius: '50%', background: '#e8f5ee',
        border: '1px solid #1f7a4d', display: 'flex', alignItems: 'center',
        justifyContent: 'center', margin: '0 auto 24px', fontSize: 24, color: '#1f7a4d',
      }}>✓</div>
      <h2 style={{ fontSize: 22, fontWeight: 700, color: '#1a1d23', marginBottom: 8 }}>You're all set!</h2>
      <p style={{ fontSize: 14, color: '#5b6470', lineHeight: 1.6, marginBottom: 32 }}>
        Omada is syncing your recent sprints to build velocity baselines for the team.
      </p>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 10, justifyContent: 'center',
        background: '#f7f8fa', border: '1px solid #e3e6eb', borderRadius: 8,
        padding: '12px 20px', fontSize: 13, color: '#5b6470', marginBottom: 32,
      }}>
        <div style={{ width: 16, height: 16, border: '2px solid #1a1d23', borderTopColor: 'transparent', borderRadius: '50%', animation: 'spin 0.8s linear infinite' }} />
        Importing sprint history…
      </div>
      <button
        onClick={onRestart}
        style={{ background: 'none', border: 'none', color: '#8a93a0', fontSize: 12, cursor: 'pointer', textDecoration: 'underline' }}
      >← Restart demo</button>
    </div>
  )
}

export function TeamSetupPage() {
  const navigate = useNavigate()
  const { get, post } = useApi()

  const [step, setStep] = useState<number>(() => {
    const saved = localStorage.getItem(STORAGE_KEY)
    return saved ? parseInt(saved, 10) : -1
  })
  const [team, setTeam] = useState<TeamDraft>(defaultTeam)
  const [members, setMembers] = useState<MemberDraft[]>([])
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    get<{ setupComplete: boolean }>('/api/teams/setup-status')
      .then(data => {
        if (data.setupComplete) navigate('/onboarding', { replace: true })
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    if (step === -1) localStorage.removeItem(STORAGE_KEY)
    else localStorage.setItem(STORAGE_KEY, String(step))
  }, [step])

  function loadBoard(boardId: string) {
    const b = boardById(boardId)
    setTeam({
      name: deriveTeamName(b),
      boardId: b.id,
      boardName: b.name,
      cadence: b.cadence,
      methodology: b.methodology,
      size: '',
      techStack: [],
    })
    setMembers(importRoster(boardId))
  }

  function importTeam(boardId: string) {
    loadBoard(boardId)
    setStep(1)
  }

  function addMember(m: MemberDraft) { setMembers(p => [...p, m]) }
  function updateMember(i: number, patch: Partial<MemberDraft>) {
    setMembers(p => p.map((m, j) => j === i ? { ...m, ...patch } : m))
  }
  function excludeMember(i: number) { updateMember(i, { included: false }) }
  function includeMember(i: number) { updateMember(i, { included: true }) }

  async function handleDone() {
    setSaving(true)
    try {
      const included = members.filter(m => m.included !== false)
      await post('/api/teams/setup', {
        name: team.name,
        boardId: team.boardId,
        boardName: team.boardName,
        cadence: team.cadence,
        methodology: team.methodology,
        members: included.map(m => ({
          name: m.name,
          email: m.email || null,
          handle: m.handle || null,
          role: m.role,
          customRole: m.customRole || null,
          seniority: m.seniority,
          capacityHoursPerWeek: m.capacity,
          domainStrengths: m.strengths,
          meetingHoursBucket: m.meetings,
        })),
      })
      localStorage.removeItem(STORAGE_KEY)
      setStep(99)
    } catch (err) {
      console.error('Team setup failed:', err)
      setSaving(false)
    }
  }

  function restart() {
    setStep(-1)
    setTeam(defaultTeam)
    setMembers([])
    localStorage.removeItem(STORAGE_KEY)
    navigate('/onboarding')
  }

  const board = boardById(team.boardId || 'plat')
  const stepperIdx = step // 0=Connect Jira, 1=Confirm team, 2=Review

  const sidebar = (
    <div style={{
      width: 238, flexShrink: 0, background: '#ffffff',
      borderRight: '1px solid #e3e6eb', padding: '36px 28px',
      position: 'sticky', top: 0, height: '100vh', boxSizing: 'border-box' as const,
      display: 'flex', flexDirection: 'column',
    }}>
      {/* Logo */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 48 }}>
        <div style={{
          width: 30, height: 30, borderRadius: 7, background: '#1a1d23',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 14, fontWeight: 800, color: '#fff',
        }}>O</div>
        <div>
          <div style={{ fontSize: 16, fontWeight: 700, color: '#1a1d23' }}>Omada</div>
          <div style={{ fontSize: 12, color: '#8a93a0', paddingLeft: 0 }}>Team setup</div>
        </div>
      </div>

      {/* Stepper */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        {STEP_LABELS.map((label, i) => {
          const done = stepperIdx > i
          const cur  = stepperIdx === i
          return (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '7px 0' }}>
              <div style={{
                width: 22, height: 22, borderRadius: '50%', flexShrink: 0,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 10, fontWeight: 700,
                background: done ? '#1a1d23' : cur ? '#eef0f3' : 'transparent',
                border: `1px solid ${done ? '#1a1d23' : cur ? '#1a1d23' : '#e3e6eb'}`,
                color: done ? '#fff' : cur ? '#1a1d23' : '#8a93a0',
              }}>{done ? '✓' : i + 1}</div>
              <span style={{
                fontSize: 13, fontWeight: cur ? 600 : 400,
                color: cur ? '#1a1d23' : done ? '#5b6470' : '#8a93a0',
              }}>{label}</span>
            </div>
          )
        })}
      </div>

      {/* Why we ask */}
      {stepperIdx >= 0 && stepperIdx <= 2 && (
        <div style={{ marginTop: 'auto', paddingTop: 32 }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: '#8a93a0', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 8 }}>Why we ask</div>
          <p style={{ fontSize: 12, color: '#8a93a0', lineHeight: 1.65, margin: 0 }}>{WHY[stepperIdx]}</p>
        </div>
      )}
    </div>
  )

  // Welcome — full centered layout, no sidebar
  if (step === -1) {
    return (
      <>
        <style>{`
          @keyframes spin { to { transform: rotate(360deg); } }
          @keyframes fadeUp { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
          @keyframes checkPop { 0% { transform: scale(0.5); opacity: 0; } 60% { transform: scale(1.15); } 100% { transform: scale(1); opacity: 1; } }
          .anim { animation: fadeUp 0.22s ease both; }
          .check-pop { animation: checkPop 0.3s ease both; }
        `}</style>
        <div style={{ minHeight: '100vh', background: '#f7f8fa', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}>
          <div style={{
            background: '#ffffff', borderRadius: 16, border: '1px solid #e3e6eb',
            boxShadow: '0 1px 4px rgba(0,0,0,0.06)', width: '100%', maxWidth: 520,
          }} className="anim">
            <WelcomeStep onStart={() => setStep(0)} />
          </div>
        </div>
      </>
    )
  }

  // Done screen — centered, no sidebar
  if (step === 99) {
    return (
      <>
        <style>{`
          @keyframes spin { to { transform: rotate(360deg); } }
          @keyframes fadeUp { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
          @keyframes checkPop { 0% { transform: scale(0.5); opacity: 0; } 60% { transform: scale(1.15); } 100% { transform: scale(1); opacity: 1; } }
          .anim { animation: fadeUp 0.22s ease both; }
          .check-pop { animation: checkPop 0.3s ease both; }
        `}</style>
        <div style={{ minHeight: '100vh', background: '#f7f8fa', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}>
          <div style={{
            background: '#ffffff', borderRadius: 16, border: '1px solid #e3e6eb',
            boxShadow: '0 1px 4px rgba(0,0,0,0.06)', width: '100%', maxWidth: 480, padding: '0 40px',
          }} className="anim">
            <DoneStep onRestart={restart} />
          </div>
        </div>
      </>
    )
  }

  return (
    <>
      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
        @keyframes fadeUp { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
        @keyframes checkPop { 0% { transform: scale(0.5); opacity: 0; } 60% { transform: scale(1.15); } 100% { transform: scale(1); opacity: 1; } }
        .anim { animation: fadeUp 0.22s ease both; }
        .check-pop { animation: checkPop 0.3s ease both; }
      `}</style>
      <div style={{ display: 'flex', minHeight: '100vh' }}>
        {sidebar}

        <div style={{
          flex: 1, background: '#f7f8fa', overflowY: 'auto',
          display: 'flex', alignItems: 'flex-start', justifyContent: 'center',
          padding: '52px 52px',
        }}>
          <div style={{ width: '100%', maxWidth: 580 }} className="anim">
            {step === 0 && (
              <JiraConnectStep
                onImport={importTeam}
                onBack={() => setStep(-1)}
              />
            )}
            {step === 1 && (
              <ConfirmTeamStep
                board={board}
                team={team}
                onRenameTeam={name => setTeam(t => ({ ...t, name }))}
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
                team={team}
                board={board}
                members={members}
                onBack={() => setStep(1)}
                onDone={handleDone}
                saving={saving}
              />
            )}
          </div>
        </div>
      </div>
    </>
  )
}
