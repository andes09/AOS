/**
 * Onboarding v2 — the real, styled flow.
 *
 * Composes the presentational pieces in `./onboarding-v2` (theme atoms,
 * SidebarStepper, and the step components) over the headless hooks in
 * `src/features/onboarding-v2`. Nothing here calls `fetch` or hardcodes step
 * order — it renders `state.currentStep` (or an earlier step the founder has
 * navigated Back to, via local `viewStep` override), so reordering or adding
 * a step on the backend needs no change here (see
 * docs/onboarding-v2-frontend-integration.md).
 */
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useOnboardingState } from '../features/onboarding-v2'
import type { OnboardingStepId } from '../features/onboarding-v2'
import { Alert, Btn, C, Spinner } from './onboarding-v2/theme'
import { SidebarStepper } from './onboarding-v2/SidebarStepper'
import { ProfileStep } from './onboarding-v2/steps/ProfileStep'
import { PurposeStep } from './onboarding-v2/steps/PurposeStep'
import { TechStackStep } from './onboarding-v2/steps/TechStackStep'
import { PlanSourceStep } from './onboarding-v2/steps/PlanSourceStep'
import { IdeaChatStep } from './onboarding-v2/steps/IdeaChatStep'
import { ImportArtifactStep } from './onboarding-v2/steps/ImportArtifactStep'
import { GithubRepoStep } from './onboarding-v2/steps/GithubRepoStep'
import { PlanReviewStep } from './onboarding-v2/steps/PlanReviewStep'

const shellFont = "'Inter', system-ui, sans-serif"

export function OnboardingV2Page() {
  const {
    state, isLoading, error, skipGithub, needsGithubSetup, saveProfile, savePurpose, saveTechStack,
    savePlanSource, complete,
  } = useOnboardingState()

  // Lets the founder step back to review or edit an earlier answer. The
  // backend has no notion of "previous step" — currentStep is always the
  // first incomplete step derived from saved data (see onboarding_v2.py's
  // _build_state) — so this is purely a client-side view override, never
  // sent to the server. Re-saving an already-complete step's data (e.g.
  // profile) doesn't change what's still incomplete, so currentStep lands
  // back in the same place once the override clears.
  const [viewStep, setViewStep] = useState<OnboardingStepId | null>(null)

  // Reaching 'done' is not a screen — the last real step (accepting the
  // roadmap, or skipping GitHub when plan_review is off) *is* the last click.
  // We finish onboarding and land on the project, rather than parking the
  // founder on an interstitial whose only job is one more button.
  const navigate = useNavigate()
  const [finishError, setFinishError] = useState<string | null>(null)
  const finishingRef = useRef(false)

  const finish = () => {
    finishingRef.current = true
    setFinishError(null)
    complete
      .mutateAsync()
      // No project means POST /complete's best-effort generation didn't
      // produce one; the hub can still create it.
      .then(({ projectId }) => navigate(projectId ? `/app/projects/${projectId}` : '/app', { replace: true }))
      .catch(err => {
        finishingRef.current = false
        setFinishError(err instanceof Error ? err.message : 'Something went wrong. Please try again.')
      })
  }

  const atDone = state?.currentStep === 'done' && viewStep === null
  useEffect(() => {
    if (atDone && !finishingRef.current) finish()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [atDone])

  if (isLoading) {
    return (
      <CenteredShell>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: C.t3, fontSize: 14 }}>
          <Spinner /> Loading onboarding…
        </div>
      </CenteredShell>
    )
  }

  if (error) {
    return (
      <CenteredShell>
        <div style={{ width: '100%', maxWidth: 420 }}>
          <Alert>Failed to load onboarding: {error instanceof Error ? error.message : String(error)}</Alert>
        </div>
      </CenteredShell>
    )
  }

  if (!state) return null

  // Onboarding is over — the effect above is finishing it. Show progress (or a
  // retry if POST /complete failed) instead of the sidebar shell.
  if (atDone) {
    return (
      <CenteredShell>
        {finishError ? (
          <div style={{ width: '100%', maxWidth: 420, display: 'flex', flexDirection: 'column', gap: 16, alignItems: 'center' }}>
            <Alert>{finishError}</Alert>
            <Btn size="lg" onClick={finish}>Try again</Btn>
          </div>
        ) : (
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: C.t3, fontSize: 14 }}>
            <Spinner /> Setting up your workspace…
          </div>
        )}
      </CenteredShell>
    )
  }

  // state.steps never includes 'done' — it's the fallback currentStep once
  // every real step is complete, so treat it as sitting one past the last one.
  const stepIds = state.steps.map(step => step.id)
  const activeStep = viewStep ?? state.currentStep
  const activeIndex = activeStep === 'done' ? stepIds.length : stepIds.indexOf(activeStep)
  const canGoBack = activeIndex > 0
  const isPreviewingPastStep = viewStep !== null && viewStep !== state.currentStep
  const goBack = () => setViewStep(stepIds[activeIndex - 1])
  const returnToCurrent = () => setViewStep(null)

  return (
    <div
      style={{
        display: 'flex',
        minHeight: '100vh',
        fontFamily: shellFont,
        WebkitFontSmoothing: 'antialiased',
      }}
    >
      {/* Left rail — step progress, driven entirely off state.steps */}
      <div
        style={{
          width: 238,
          flexShrink: 0,
          background: C.bg0,
          borderRight: `1px solid ${C.border}`,
          padding: '36px 28px',
        }}
      >
        <SidebarStepper state={state} />
      </div>

      {/* Main content — the current step */}
      <div
        style={{
          flex: 1,
          background: C.bg1,
          overflowY: 'auto',
          display: 'flex',
          alignItems: 'flex-start',
          justifyContent: 'center',
          padding: '52px 52px',
        }}
      >
        <div style={{ width: '100%', maxWidth: 580 }}>
          {(canGoBack || isPreviewingPastStep) && (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
              {canGoBack ? (
                <Btn variant="ghost" size="sm" onClick={goBack}>← Back</Btn>
              ) : <span />}
              {isPreviewingPastStep && (
                <Btn variant="ghost" size="sm" onClick={returnToCurrent}>Return to current step →</Btn>
              )}
            </div>
          )}
          {activeStep === 'profile' && (
            <ProfileStep
              onSave={(name, phone) => { setViewStep(null); saveProfile.mutate({ name, phone }) }}
              saving={saveProfile.isPending}
              saveError={saveProfile.error?.message ?? null}
            />
          )}
          {activeStep === 'purpose' && (
            <PurposeStep
              onSave={purpose => { setViewStep(null); savePurpose.mutate(purpose) }}
              saving={savePurpose.isPending}
            />
          )}
          {activeStep === 'tech_stack' && (
            <TechStackStep
              onSave={(stack, experience) => { setViewStep(null); saveTechStack.mutate({ stack, experience }) }}
              saving={saveTechStack.isPending}
              saveError={saveTechStack.error?.message ?? null}
            />
          )}
          {activeStep === 'build_plan' && (
            <PlanSourceStep
              onSave={source => { setViewStep(null); savePlanSource.mutate(source) }}
              saving={savePlanSource.isPending}
            />
          )}
          {activeStep === 'idea_chat' && <IdeaChatStep />}
          {activeStep === 'import_artifact' && <ImportArtifactStep />}
          {activeStep === 'github_repo' && (
            <GithubRepoStep
              githubConnected={state.github.connected}
              githubNeedsReconnect={state.github.needsReconnect}
              onSkipGithub={() => { setViewStep(null); skipGithub.mutate() }}
              skippingGithub={skipGithub.isPending}
              onNeedsGithubSetup={() => { setViewStep(null); needsGithubSetup.mutate() }}
              markingNeedsSetup={needsGithubSetup.isPending}
              repoAvailable={state.repo.available}
              onboardingPath={state.onboardingPath}
              canCreate={state.repo.canCreate}
              ownerLogin={state.repo.ownerLogin}
            />
          )}
          {activeStep === 'plan_review' && <PlanReviewStep />}
        </div>
      </div>
    </div>
  )
}

/** Full-height centered container for the loading and error states. */
function CenteredShell({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        display: 'flex',
        minHeight: '100vh',
        alignItems: 'center',
        justifyContent: 'center',
        background: C.bg1,
        fontFamily: shellFont,
        WebkitFontSmoothing: 'antialiased',
        padding: 24,
      }}
    >
      {children}
    </div>
  )
}
