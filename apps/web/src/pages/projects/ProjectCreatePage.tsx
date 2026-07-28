// New-project creation: starts a project-scoped onboarding session and drives
// it through purpose -> chat -> generate (see docs/plans/2026-07-20-project-hub.md).
// Its own route (not a modal) since the multi-step flow benefits from
// refresh-safety — losing an in-progress chat to an accidental dismiss would
// be a bad first impression for a second project.

import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Sparkles } from 'lucide-react'
import { Button } from '../../components/ui/Button'
import { Spinner } from '../../components/ui/Spinner'
import { Alert } from '../../components/ui/Alert'
import { PurposeStep } from '../onboarding-v2/steps/PurposeStep'
import type { ProjectPurpose } from '../../features/onboarding-v2'
import { useProjectCreation } from '../../features/projects/hooks/useProjectCreation'
import { PROJECTS_KEY } from '../../features/projects/hooks/useProjects'
import { useQueryClient } from '@tanstack/react-query'
import { ProjectCreateChatStep } from './ProjectCreateChatStep'

export function ProjectCreatePage() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { state, start, choosePurpose, generate, isStarting } = useProjectCreation()

  useEffect(() => {
    if (state.step === 'idle') void start()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (state.step === 'done') {
      qc.invalidateQueries({ queryKey: PROJECTS_KEY })
      navigate(`/app/projects/${state.project.id}`, { replace: true })
    }
  }, [state, qc, navigate])

  return (
    <div style={{ maxWidth: 680, margin: '0 auto', padding: 'var(--space-4) 0' }}>
      {(state.step === 'idle' || isStarting) && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '3rem 0', justifyContent: 'center' }}>
          <Spinner /> Starting a new project…
        </div>
      )}

      {state.step === 'purpose' && (
        <PurposeStep
          saving={false}
          onSave={(purpose: ProjectPurpose) => void choosePurpose(state.sessionId, purpose)}
        />
      )}

      {state.step === 'chat' && (
        <ProjectCreateChatStep
          sessionId={state.sessionId}
          onGenerate={() => void generate(state.sessionId)}
        />
      )}

      {state.step === 'generating' && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '3rem 0', justifyContent: 'center' }}>
          <Spinner /> <Sparkles size={16} /> Building your roadmap…
        </div>
      )}

      {state.step === 'error' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16, alignItems: 'center', padding: '3rem 0' }}>
          <Alert variant="danger">{state.message}</Alert>
          <Button variant="secondary" onClick={() => navigate('/app')}>
            Back to Projects
          </Button>
        </div>
      )}
    </div>
  )
}
