// Onboarding v2 — headless public contract.
//
// This barrel is the integration surface for any UI: types, a framework-
// agnostic client, and React hooks. Nothing here renders or styles anything.
//
// Typical wiring:
//   const { state, skipGithub, saveProfile, savePurpose, saveTechStack, savePlanSource, complete } = useOnboardingState()
//   const { connect, redirectResult } = useGithubConnect('/onboarding')
//   const chat = useIdeaChat()  // render chat.messages + chat.streamingReply
//   const importFlow = useImportArtifact()  // analyze/apply + per-milestone accept/reject
//   const repoSelect = useRepoSelect()  // list repos + setRepo/skipRepo
//
// state.currentStep walks: github_connect -> profile -> purpose -> tech_stack (flag-gated)
// -> build_plan -> repo_select -> done. build_plan forks on state.onboardingPath
// ('chat' | 'import' | null): its step id in state.steps is 'build_plan' while
// unset, then 'idea_chat' or 'import_artifact' once chosen via savePlanSource.
// repo_select is skippable and auto-completes when GitHub was never connected.
// `purpose` (hobby/startup/learning) steers the idea interview's system prompt
// server-side, so collect it with a simple 3-way choice, not free text.
// `tech_stack` (behind experimental.tech_stack_step) is similarly explicit —
// what the founder already knows, or 'new' for "I'm new to this" — and steers
// the roadmap generator's prompt instead.
//
// Non-React consumers can use createOnboardingApi(getToken) directly.

export * from './types'
export { createOnboardingApi, parseGithubRedirect, OnboardingApiError } from './api'
export type { OnboardingApi, GetToken } from './api'
export { useOnboardingState, ONBOARDING_STATE_KEY } from './hooks/useOnboardingState'
export { useGithubConnect } from './hooks/useGithubConnect'
export { useIdeaChat } from './hooks/useIdeaChat'
export { useImportArtifact, IMPORT_ARTIFACT_KEY } from './hooks/useImportArtifact'
export { useRepoSelect } from './hooks/useRepoSelect'
