import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApi } from '../lib/api'
import { TeamDraft, MemberDraft } from './onboarding/team-setup/types'
import { STEP_LABELS, WHY } from './onboarding/team-setup/data'
import { WelcomeStep } from './onboarding/team-setup/WelcomeStep'
import { TeamBasicsStep } from './onboarding/team-setup/TeamBasicsStep'
import { AddMembersStep } from './onboarding/team-setup/AddMembersStep'
import { ReviewStep } from './onboarding/team-setup/ReviewStep'

const STORAGE_KEY = 'aos_team_setup_step'

const defaultTeam: TeamDraft = {
  name: '',
  size: '6–10',
  cadence: '2-week',
  methodology: 'Scrum',
  techStack: [],
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

  // Check if setup is already complete on mount
  useEffect(() => {
    get<{ setupComplete: boolean }>('/api/teams/setup-status')
      .then(data => {
        if (data.setupComplete) {
          navigate('/onboarding', { replace: true })
        }
      })
      .catch(() => {
        // If the endpoint doesn't exist yet, proceed normally
      })
  }, [])

  // Persist step to localStorage whenever it changes
  useEffect(() => {
    if (step === -1) {
      localStorage.removeItem(STORAGE_KEY)
    } else {
      localStorage.setItem(STORAGE_KEY, String(step))
    }
  }, [step])

  function goTo(s: number) {
    setStep(s)
  }

  function handleAddMember(m: MemberDraft) {
    setMembers(prev => [...prev, m])
  }

  function handleRemoveMember(i: number) {
    setMembers(prev => prev.filter((_, idx) => idx !== i))
  }

  async function handleDone() {
    setSaving(true)
    try {
      await post('/api/teams/setup', {
        name: team.name,
        sizeTier: team.size,
        cadence: team.cadence,
        methodology: team.methodology,
        techStack: team.techStack,
        members: members.map(m => ({
          name: m.name,
          email: m.email || null,
          role: m.role,
          customRole: m.customRole || null,
          seniority: m.seniority,
          capacityHoursPerWeek: m.capacity,
          domainStrengths: m.strengths,
          meetingHoursBucket: m.meetings,
          skillRatings: Object.keys(m.skillRatings).length > 0 ? m.skillRatings : null,
        })),
      })
      localStorage.removeItem(STORAGE_KEY)
      navigate('/onboarding')
    } catch (err) {
      console.error('Team setup failed:', err)
      setSaving(false)
    }
  }

  const currentStepIndex = step // step 0,1,2 maps to STEP_LABELS

  const sidebar = (
    <div style={{
      width: 240,
      flexShrink: 0,
      background: '#ffffff',
      borderRight: '1px solid var(--color-border)',
      display: 'flex',
      flexDirection: 'column',
      padding: '28px 20px',
      position: 'sticky',
      top: 0,
      height: '100vh',
      boxSizing: 'border-box',
    }}>
      {/* Logo */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 36 }}>
        <div style={{
          width: 30,
          height: 30,
          borderRadius: 7,
          background: '#1a1d23',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          flexShrink: 0,
        }}>
          <span style={{
            color: '#ffffff',
            fontFamily: 'var(--font-sans)',
            fontWeight: 800,
            fontSize: 14,
          }}>O</span>
        </div>
        <div>
          <div style={{
            fontSize: 'var(--text-sm)',
            fontWeight: 700,
            color: 'var(--color-text-primary)',
            fontFamily: 'var(--font-sans)',
            lineHeight: 1.2,
          }}>Omada</div>
          <div style={{
            fontSize: 'var(--text-xs)',
            color: 'var(--color-text-muted)',
            fontFamily: 'var(--font-sans)',
          }}>Team setup</div>
        </div>
      </div>

      {/* Stepper */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        {STEP_LABELS.map((label, i) => {
          const isDone = i < currentStepIndex
          const isCurrent = i === currentStepIndex
          const isFuture = i > currentStepIndex

          return (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '6px 0' }}>
              <div style={{
                width: 22,
                height: 22,
                borderRadius: '50%',
                flexShrink: 0,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontFamily: 'var(--font-sans)',
                fontWeight: 700,
                fontSize: 10,
                background: isDone
                  ? 'var(--color-accent)'
                  : isCurrent
                  ? 'rgba(12,102,228,0.1)'
                  : 'transparent',
                border: isDone
                  ? 'none'
                  : isCurrent
                  ? '2px solid var(--color-accent)'
                  : '2px solid var(--color-border)',
                color: isDone
                  ? '#ffffff'
                  : isCurrent
                  ? 'var(--color-accent)'
                  : 'var(--color-text-muted)',
              }}>
                {isDone ? '✓' : i + 1}
              </div>
              <span style={{
                fontSize: 'var(--text-sm)',
                fontFamily: 'var(--font-sans)',
                fontWeight: isCurrent ? 600 : 400,
                color: isCurrent
                  ? 'var(--color-text-primary)'
                  : isFuture
                  ? 'var(--color-text-muted)'
                  : 'var(--color-text-secondary)',
              }}>
                {label}
              </span>
            </div>
          )
        })}
      </div>

      {/* Why we ask */}
      {currentStepIndex >= 0 && currentStepIndex <= 2 && (
        <div style={{
          marginTop: 'auto',
          padding: '14px',
          background: '#f0f2f5',
          borderRadius: 'var(--radius-md)',
          border: '1px solid var(--color-border)',
        }}>
          <div style={{
            fontSize: 10,
            fontWeight: 700,
            color: 'var(--color-text-muted)',
            fontFamily: 'var(--font-sans)',
            textTransform: 'uppercase',
            letterSpacing: '0.07em',
            marginBottom: 6,
          }}>Why we ask</div>
          <p style={{
            fontSize: 'var(--text-xs)',
            color: 'var(--color-text-secondary)',
            fontFamily: 'var(--font-sans)',
            margin: 0,
            lineHeight: 1.6,
          }}>
            {WHY[currentStepIndex]}
          </p>
        </div>
      )}
    </div>
  )

  // Welcome step — full centered layout, no sidebar
  if (step === -1) {
    return (
      <>
        <style>{`
          @keyframes spin { to { transform: rotate(360deg); } }
          @keyframes fadeUp {
            from { opacity: 0; transform: translateY(10px); }
            to   { opacity: 1; transform: translateY(0); }
          }
        `}</style>
        <div style={{
          minHeight: '100vh',
          background: '#f7f8fa',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: 24,
        }}>
          <div style={{
            background: '#ffffff',
            borderRadius: 16,
            border: '1px solid var(--color-border)',
            boxShadow: '0 1px 4px rgba(0,0,0,0.06)',
            width: '100%',
            maxWidth: 520,
            animation: 'fadeUp 0.22s ease',
          }}>
            <WelcomeStep onStart={() => goTo(0)} />
          </div>
        </div>
      </>
    )
  }

  return (
    <>
      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
        @keyframes fadeUp {
          from { opacity: 0; transform: translateY(10px); }
          to   { opacity: 1; transform: translateY(0); }
        }
      `}</style>
      <div style={{ display: 'flex', minHeight: '100vh' }}>
        {sidebar}

        {/* Main content */}
        <div style={{
          flex: 1,
          background: '#f7f8fa',
          display: 'flex',
          justifyContent: 'center',
          padding: '48px 24px',
          overflowY: 'auto',
        }}>
          <div style={{
            width: '100%',
            maxWidth: 580,
            animation: 'fadeUp 0.22s ease',
          }}>
            {step === 0 && (
              <TeamBasicsStep
                data={team}
                setData={setTeam}
                onNext={() => goTo(1)}
              />
            )}
            {step === 1 && (
              <AddMembersStep
                members={members}
                onAdd={handleAddMember}
                onRemove={handleRemoveMember}
                onNext={() => goTo(2)}
                onBack={() => goTo(0)}
                techStack={team.techStack}
              />
            )}
            {step === 2 && (
              <ReviewStep
                team={team}
                members={members}
                onBack={() => goTo(1)}
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
