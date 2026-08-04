// Onboarding v2 API contract types.
// These mirror the JSON shapes served by /api/onboarding/v2/* and
// /api/integrations/github/* — see apps/api/src/routers/onboarding_v2.py.

// The 4th step's id depends on which build_plan sub-flow was chosen (see
// PUT /plan-source): 'build_plan' while unset, then 'idea_chat' or
// 'import_artifact'. 'github_repo' covers connecting GitHub and picking (or
// creating) a repo as one step — see `github` / `repo` below for the two
// halves' own state.
export type OnboardingStepId =
  | 'profile'
  | 'purpose'
  | 'tech_stack'
  | 'build_plan'
  | 'idea_chat'
  | 'import_artifact'
  | 'github_repo'
  // Gated behind experimental.plan_review — review/regenerate the drafted
  // roadmap before it's committed. The last step before 'done'.
  | 'plan_review'
export type OnboardingStepStatus = 'complete' | 'current' | 'pending'

export type PlanSource = 'chat' | 'import'

/**
 * What the founder already knows, collected via an explicit step (like
 * ProjectPurpose) so the roadmap generator can prefer familiar tools or,
 * for 'new', build in setup/learning tasks instead of assuming prior
 * knowledge. Gated behind the experimental.tech_stack_step flag.
 */
export type TechExperience = 'experienced' | 'new'

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
  techStack: {
    stack: string[]
    experience: TechExperience | null
    complete: boolean
  }
  ideaChat: {
    sessionId: string | null
    status: ChatStatus
    messageCount: number
    brief: ProjectBrief | null
    briefComplete: boolean
  }
  onboardingPath: PlanSource | null
  importArtifact: ImportArtifactState | null
  repo: RepoState
  /** The drafted project's id — which roadmap the plan-review step shows. Null
   *  until a project exists (chat path drafts it in the plan-review step). */
  projectId: string | null
  planReview: { confirmed: boolean }
  onboardingCompleted: boolean
}

export type ProposedTask = {
  title: string
  description?: string | null
  dayOffset: number
  startTime?: string | null
  durationMinutes?: number | null
  key?: string | null
  dependsOn: string[]
}

export type ProposedMilestone = {
  title: string
  description?: string | null
  tasks: ProposedTask[]
}

export type ImportArtifactState = {
  analyzed: boolean
  projectName: string | null
  summary: string | null
  milestones: ProposedMilestone[]
  missingFields: string[]
  /** Only meaningful right after a POST /import/analyze call. */
  truncated?: boolean
}

export type RepoState = {
  /** The full "owner/repo" name, once picked via PUT /repo. */
  selected: string | null
  skipped: boolean
  /** True once GitHub is actually connected — repo_select auto-completes when false. */
  available: boolean
  /** Whether the chat path can offer "create a new repo": an Organization
   *  install with experimental.repo_create on. Personal-account installs are
   *  connect-only (see github_app_repo_create_constraint). */
  canCreate: boolean
  /** The account (org) login new repos would be created under, or null. */
  ownerLogin: string | null
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
