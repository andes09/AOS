/**
 * Onboarding v2 — the real, styled flow.
 *
 * Composes the presentational pieces in `./onboarding-v2` (theme atoms,
 * SidebarStepper, and the five step components) over the headless hooks in
 * `src/features/onboarding-v2`. Nothing here calls `fetch` or hardcodes step
 * order — it renders whatever `state.currentStep` says, so reordering or adding
 * a step on the backend needs no change here (see
 * docs/onboarding-v2-frontend-integration.md).
 */
import { useOnboardingState } from '../features/onboarding-v2'
import { Alert, C, Spinner } from './onboarding-v2/theme'
import { SidebarStepper } from './onboarding-v2/SidebarStepper'
import { GithubStep } from './onboarding-v2/steps/GithubStep'
import { ProfileStep } from './onboarding-v2/steps/ProfileStep'
import { PurposeStep } from './onboarding-v2/steps/PurposeStep'
import { PlanSourceStep } from './onboarding-v2/steps/PlanSourceStep'
import { IdeaChatStep } from './onboarding-v2/steps/IdeaChatStep'
import { ImportArtifactStep } from './onboarding-v2/steps/ImportArtifactStep'
import { RepoSelectStep } from './onboarding-v2/steps/RepoSelectStep'
import { DoneStep } from './onboarding-v2/steps/DoneStep'

const shellFont = "'Inter', system-ui, sans-serif"

export function OnboardingV2Page() {
  const { state, isLoading, error, skipGithub, saveProfile, savePurpose, savePlanSource, complete } =
    useOnboardingState()

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
          {state.currentStep === 'github_connect' && (
            <GithubStep
              onSkip={() => skipGithub.mutate()}
              skipping={skipGithub.isPending}
              needsReconnect={state.github.needsReconnect}
            />
          )}
          {state.currentStep === 'profile' && (
            <ProfileStep
              onSave={(name, phone) => saveProfile.mutate({ name, phone })}
              saving={saveProfile.isPending}
              saveError={saveProfile.error?.message ?? null}
            />
          )}
          {state.currentStep === 'purpose' && (
            <PurposeStep
              onSave={purpose => savePurpose.mutate(purpose)}
              saving={savePurpose.isPending}
            />
          )}
          {state.currentStep === 'build_plan' && (
            <PlanSourceStep
              onSave={source => savePlanSource.mutate(source)}
              saving={savePlanSource.isPending}
            />
          )}
          {state.currentStep === 'idea_chat' && <IdeaChatStep />}
          {state.currentStep === 'import_artifact' && <ImportArtifactStep />}
          {state.currentStep === 'repo_select' && (
            <RepoSelectStep repoAvailable={state.repo.available} />
          )}
          {state.currentStep === 'done' && <DoneStep onFinish={() => complete.mutateAsync()} />}
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
