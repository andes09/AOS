// apps/web/src/pages/OnboardingPage.tsx

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { OnboardingLayout } from '../layouts/OnboardingLayout'
import { ConnectJiraStep } from './onboarding/ConnectJiraStep'
import { SelectBoardStep } from './onboarding/SelectBoardStep'
import { SaveAnthropicKeyStep } from './onboarding/SaveAnthropicKeyStep'

const STEPS = ['Connect Jira', 'Select Board', 'Anthropic Key'] as const
const STORAGE_KEY = 'aos_onboarding_step'

export function OnboardingPage() {
  const navigate = useNavigate()
  const [step, setStep] = useState<number>(() => {
    const saved = localStorage.getItem(STORAGE_KEY)
    return saved ? parseInt(saved, 10) : 0
  })

  function goTo(next: number) {
    localStorage.setItem(STORAGE_KEY, String(next))
    setStep(next)
  }

  function advance() {
    if (step === STEPS.length - 1) {
      localStorage.removeItem(STORAGE_KEY)
      navigate('/app/sprint-planner')
    } else {
      goTo(step + 1)
    }
  }

  function back() {
    goTo(step - 1)
  }

  return (
    <OnboardingLayout>
      {/* Step indicator */}
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: '2rem' }}>
        {STEPS.map((label, i) => (
          <div key={i} style={{ display: 'flex', alignItems: 'center' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <div style={{
                width: 28,
                height: 28,
                borderRadius: '50%',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                background: i < step ? '#6366f1' : 'transparent',
                border: i === step ? '2px solid #6366f1' : i < step ? 'none' : '2px solid #2d2f45',
                color: i < step ? '#fff' : i === step ? '#6366f1' : '#64748b',
                fontSize: 11,
                fontWeight: 700,
                flexShrink: 0,
              }}>
                {i < step ? '✓' : i + 1}
              </div>
              <span style={{ fontSize: 12, color: i === step ? '#e2e8f0' : '#64748b', whiteSpace: 'nowrap' }}>
                {label}
              </span>
            </div>
            {i < STEPS.length - 1 && (
              <div style={{ width: 24, height: 1, background: '#2d2f45', margin: '0 8px', flexShrink: 0 }} />
            )}
          </div>
        ))}
      </div>

      {step === 0 && <ConnectJiraStep onNext={advance} />}
      {step === 1 && <SelectBoardStep onNext={advance} onBack={back} />}
      {step === 2 && <SaveAnthropicKeyStep onNext={advance} onBack={back} />}
    </OnboardingLayout>
  )
}
