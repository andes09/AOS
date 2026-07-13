// Onboarding v2 — headless public contract.
//
// This barrel is the integration surface for any UI: types, a framework-
// agnostic client, and React hooks. Nothing here renders or styles anything.
//
// Typical wiring:
//   const { state, skipGithub, saveProfile, savePurpose, complete } = useOnboardingState()
//   const { connect, redirectResult } = useGithubConnect('/onboarding')
//   const chat = useIdeaChat()  // render chat.messages + chat.streamingReply
//
// state.currentStep walks: github_connect -> profile -> purpose -> idea_chat -> done.
// `purpose` (hobby/startup/learning) steers the idea interview's system prompt
// server-side, so collect it with a simple 3-way choice, not free text.
//
// Non-React consumers can use createOnboardingApi(getToken) directly.

export * from './types'
export { createOnboardingApi, parseGithubRedirect, OnboardingApiError } from './api'
export type { OnboardingApi, GetToken } from './api'
export { useOnboardingState, ONBOARDING_STATE_KEY } from './hooks/useOnboardingState'
export { useGithubConnect } from './hooks/useGithubConnect'
export { useIdeaChat } from './hooks/useIdeaChat'
