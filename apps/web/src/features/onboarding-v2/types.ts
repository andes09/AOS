// Onboarding v2 API contract types.
// These mirror the JSON shapes served by /api/onboarding/v2/* and
// /api/integrations/github/* — see apps/api/src/routers/onboarding_v2.py.

export type OnboardingStepId = 'github_connect' | 'profile' | 'purpose' | 'idea_chat'
export type OnboardingStepStatus = 'complete' | 'current' | 'pending'

/**
 * What the project is for. Collected explicitly (not chat-extracted) because
 * it determines the idea interview's whole strategy: a hobby project is
 * planned around free time and fun, a startup around a viable MVP and
 * market, a learning project around skill milestones. Ask for this with a
 * simple 3-way choice — don't bury it in free text.
 */
export type ProjectPurpose = 'hobby' | 'startup' | 'learning'

export type OnboardingStep = {
  id: OnboardingStepId
  status: OnboardingStepStatus
  skippable: boolean
}

export type ProjectBrief = {
  projectName?: string | null
  problemStatement?: string | null
  targetAudience?: string | null
  coreFeatures?: string[]
  scope?: string | null
  outOfScope?: string[]
  timeline?: string | null
  techConstraints?: string[]
  existingAssets?: string[]
  openQuestions?: string[]
}

export type ChatStatus = 'not_started' | 'in_progress' | 'completed'

export type OnboardingState = {
  currentStep: OnboardingStepId | 'done'
  steps: OnboardingStep[]
  github: {
    connected: boolean
    login: string | null
    skipped: boolean
    needsReconnect: boolean
  }
  profile: {
    name: string | null
    phone: string | null
    complete: boolean
  }
  purpose: {
    value: ProjectPurpose | null
    complete: boolean
  }
  ideaChat: {
    sessionId: string | null
    status: ChatStatus
    messageCount: number
    brief: ProjectBrief | null
    briefComplete: boolean
  }
  onboardingCompleted: boolean
}

export type ChatMessage = {
  id: string
  role: 'user' | 'assistant'
  content: string
  createdAt: string
}

export type ChatPayload = {
  sessionId: string | null
  status: ChatStatus
  messages: ChatMessage[]
  brief: ProjectBrief | null
  briefComplete: boolean
}

export type GithubStatus =
  | { connected: false }
  | {
      connected: true
      login: string
      avatarUrl: string | null
      scopes: string[]
      connectedAt: string
    }

export type GithubRepo = {
  id: number
  fullName: string
  private: boolean
  defaultBranch: string | null
  url: string
}

/** Result of the GitHub OAuth redirect, parsed from the return URL. */
export type GithubRedirectResult =
  | { outcome: 'connected' }
  | { outcome: 'error'; reason: string }
  | null

export type ChatStreamHandlers = {
  /** Fires per streamed token of the assistant reply. */
  onToken?: (text: string) => void
  /** Fires once per turn with the updated extracted brief. */
  onBrief?: (data: { brief: ProjectBrief; missingFields: string[]; briefComplete: boolean }) => void
  /** Fires when the turn finishes; status "completed" means the interview is over. */
  onDone?: (data: { messageId: string; status: ChatStatus }) => void
  onError?: (message: string) => void
}
