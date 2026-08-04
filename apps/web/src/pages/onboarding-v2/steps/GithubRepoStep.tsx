/**
 * Step 5 — github_repo. One skippable step covering both connecting GitHub
 * and picking (or creating) a repo, rendered as two phases of the same
 * step rather than two separate components:
 *
 *   Phase A — GitHub isn't connected (or a legacy connection needs
 *   reconnecting through the App install flow): render GithubStep.
 *   Phase B — GitHub is connected: render RepoSelectStep.
 *
 * The backend only marks github_repo complete once both halves are done
 * (see STEP_GITHUB_REPO in onboarding_v2.py), so state.currentStep stays on
 * this step across the phase switch — no navigation, the component just
 * re-renders as `github.connected` flips to true.
 */
import { GithubStep } from './GithubStep'
import { RepoSelectStep } from './RepoSelectStep'
import type { PlanSource } from '../../../features/onboarding-v2'

export function GithubRepoStep({
  githubConnected,
  githubNeedsReconnect,
  onSkipGithub,
  skippingGithub,
  repoAvailable,
  onboardingPath,
  canCreate,
  ownerLogin,
}: {
  githubConnected: boolean
  githubNeedsReconnect: boolean
  onSkipGithub: () => void
  skippingGithub: boolean
  repoAvailable: boolean
  onboardingPath: PlanSource | null
  canCreate: boolean
  ownerLogin: string | null
}) {
  if (!githubConnected || githubNeedsReconnect) {
    return (
      <GithubStep
        onSkip={onSkipGithub}
        skipping={skippingGithub}
        needsReconnect={githubNeedsReconnect}
      />
    )
  }

  return (
    <RepoSelectStep
      repoAvailable={repoAvailable}
      onboardingPath={onboardingPath}
      canCreate={canCreate}
      ownerLogin={ownerLogin}
    />
  )
}
