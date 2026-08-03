/**
 * Left-rail step progress for the onboarding v2 flow.
 *
 * Drives entirely off `state.steps` / `state.currentStep` — the order and
 * completeness come from the backend, so reordering or adding a step needs no
 * change here. Unknown step ids fall back to a prettified label.
 */
import type { OnboardingState, OnboardingStepId } from '../../features/onboarding-v2'
import { C, OmadaMark } from './theme'

const STEP_LABELS: Record<OnboardingStepId, string> = {
  github_connect: 'Connect GitHub',
  profile: 'Your details',
  purpose: 'Project purpose',
  tech_stack: 'Your tools',
  build_plan: 'Build your plan',
  idea_chat: 'Your idea',
  import_artifact: 'Import your plan',
  repo_select: 'Connect a repo',
  plan_review: 'Review your plan',
}

const WHY: Partial<Record<OnboardingState['currentStep'], string>> = {
  github_connect: 'Connecting GitHub lets the roadmap AI read your repos and plan around what already exists. You can skip it and connect later.',
  profile: 'We use your name and phone to personalize your workspace and reach you about your projects — nothing more.',
  purpose: 'A hobby, a startup, and a learning project each need a different roadmap. Your answer steers the AI interview that comes next.',
  tech_stack: "Telling us what you already know means the plan uses tools you're comfortable with — and if you're starting fresh, we'll build in time to get set up.",
  build_plan: 'Chat with the AI, or import an existing plan (a PRD, a validation summary, even a rough brainstorm) — either way you end up with a reviewable roadmap.',
  idea_chat: 'The more the AI understands your idea, the sharper your first roadmap. Answer a few questions and we build the brief live.',
  import_artifact: 'We extract a project brief and draft a roadmap from what you upload. Review each proposed milestone before anything is created.',
  repo_select: 'Connecting a specific repo lets Omada tie tasks to real code later — you can also skip this and connect one anytime.',
  plan_review: 'This is your roadmap before anything is locked in. Regenerate it if it misses the mark, or accept it and start building.',
}

function labelFor(id: string): string {
  if (id in STEP_LABELS) return STEP_LABELS[id as OnboardingStepId]
  return id.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

export function SidebarStepper({ state }: { state: OnboardingState }) {
  const why = WHY[state.currentStep]
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ marginBottom: 48 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
          <OmadaMark size={30} />
          <span style={{ fontSize: 16, fontWeight: 700, color: C.t1 }}>Omada</span>
        </div>
        <div style={{ fontSize: 12, color: C.t3, paddingLeft: 40 }}>Get started</div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        {state.steps.map((step, i) => {
          const done = step.status === 'complete'
          const cur = step.status === 'current'
          return (
            <div key={step.id} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '7px 0' }}>
              <div style={{ width: 22, height: 22, borderRadius: '50%', flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', background: done ? C.accent : cur ? C.accentSubtle : 'transparent', border: `1px solid ${done ? C.accent : cur ? C.accent : C.border}`, fontSize: 10, fontWeight: 700, color: done ? '#fff' : cur ? C.accent : C.t3 }}>{done ? '✓' : i + 1}</div>
              <span style={{ fontSize: 13, fontWeight: cur ? 600 : 400, color: cur ? C.t1 : done ? C.t2 : C.t3 }}>
                {labelFor(step.id)}
                {step.skippable && cur && <span style={{ fontSize: 11, fontWeight: 400, color: C.t3 }}> · optional</span>}
              </span>
            </div>
          )
        })}
      </div>

      {why && (
        <div style={{ marginTop: 'auto', paddingTop: 32 }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: C.t3, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 8 }}>Why we ask</div>
          <p style={{ fontSize: 12, color: C.t3, lineHeight: 1.65 }}>{why}</p>
        </div>
      )}
    </div>
  )
}
