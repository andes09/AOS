// Framework-agnostic typed client for the onboarding v2 API.
// No React, no styling — any UI (or even a CLI) can drive the flow with this.
// React apps will usually consume the hooks in ./hooks instead.

import type {
  ChatPayload,
  ChatStatus,
  ChatStreamHandlers,
  GithubRedirectResult,
  GithubRepo,
  GithubStatus,
  ImportArtifactState,
  OnboardingState,
  PlanSource,
  ProjectBrief,
  ProjectPurpose,
  TechExperience,
} from './types'

export type GetToken = () => Promise<string | null>

export class OnboardingApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

const DEFAULT_API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

async function parseErrorDetail(response: Response): Promise<string> {
  const error = await response.json().catch(() => ({}))
  const detail = (error as { detail?: unknown }).detail
  return Array.isArray(detail)
    ? detail.map((e: { msg?: string }) => e.msg ?? JSON.stringify(e)).join(', ')
    : ((typeof detail === 'string' ? detail : null) ?? `API error ${response.status}`)
}

export function createOnboardingApi(getToken: GetToken, apiUrl: string = DEFAULT_API_URL) {
  async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const token = await getToken()
    if (!token) throw new OnboardingApiError('Not authenticated', 401)
    const response = await fetch(`${apiUrl}${path}`, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
        ...options.headers,
      },
    })
    if (!response.ok) {
      throw new OnboardingApiError(await parseErrorDetail(response), response.status)
    }
    return response.json() as Promise<T>
  }

  return {
    // --- flow state ---
    getState: () => request<OnboardingState>('/api/onboarding/v2/state'),
    skipGithub: () => request<OnboardingState>('/api/onboarding/v2/github/skip', { method: 'POST' }),
    /** "I don't have GitHub yet" — advances the step like skipGithub, and also
     *  gets a GitHub setup milestone prepended to the generated roadmap. */
    needsGithubSetup: () =>
      request<OnboardingState>('/api/onboarding/v2/github/needs-setup', { method: 'POST' }),
    saveProfile: (profile: { name: string; phone: string }) =>
      request<OnboardingState>('/api/onboarding/v2/profile', {
        method: 'PUT',
        body: JSON.stringify(profile),
      }),
    savePurpose: (purpose: ProjectPurpose) =>
      request<OnboardingState>('/api/onboarding/v2/purpose', {
        method: 'PUT',
        body: JSON.stringify({ purpose }),
      }),
    saveTechStack: (stack: string[], experience: TechExperience) =>
      request<OnboardingState>('/api/onboarding/v2/tech-stack', {
        method: 'PUT',
        body: JSON.stringify({ stack, experience }),
      }),
    savePlanSource: (source: PlanSource) =>
      request<OnboardingState>('/api/onboarding/v2/plan-source', {
        method: 'PUT',
        body: JSON.stringify({ source }),
      }),
    completeOnboarding: () =>
      request<{ completedAt: string; projectId: string | null }>(
        '/api/onboarding/v2/complete',
        { method: 'POST' },
      ),

    // --- plan review (experimental.plan_review) ---
    /**
     * Ensure a drafted roadmap exists and return its projectId. Idempotent.
     *
     * When a project already exists (import path, or a second call) the
     * server returns plain JSON immediately — no generation, nothing to
     * report progress on. When generation actually has to happen, the
     * response streams back as SSE so `onProgress` gets real 0-95% updates
     * as the roadmap comes in from Groq, instead of a fake timer.
     */
    async draftPlan(
      handlers: { onProgress?: (pct: number) => void } = {},
      signal?: AbortSignal,
    ): Promise<{ projectId: string }> {
      const token = await getToken()
      if (!token) throw new OnboardingApiError('Not authenticated', 401)

      const response = await fetch(`${apiUrl}/api/onboarding/v2/plan/draft`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'text/event-stream',
          Authorization: `Bearer ${token}`,
        },
        signal,
      })

      if (!response.ok) {
        throw new OnboardingApiError(await parseErrorDetail(response), response.status)
      }

      const contentType = response.headers.get('content-type') ?? ''
      if (!contentType.includes('text/event-stream')) {
        return response.json() as Promise<{ projectId: string }>
      }
      if (!response.body) throw new Error('No response body for SSE stream')

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let projectId: string | null = null
      let streamError: string | null = null

      try {
        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          const events = buffer.split('\n\n')
          buffer = events.pop() ?? ''
          for (const evt of events) {
            const lines = evt.split('\n')
            const eventLine = lines.find(l => l.startsWith('event:'))?.slice(6).trim()
            const dataLine = lines.find(l => l.startsWith('data:'))?.slice(5).trim()
            if (!eventLine || !dataLine) continue
            let data: unknown
            try {
              data = JSON.parse(dataLine)
            } catch {
              continue
            }
            if (eventLine === 'progress') {
              handlers.onProgress?.((data as { pct: number }).pct)
            } else if (eventLine === 'done') {
              projectId = (data as { projectId: string }).projectId
            } else if (eventLine === 'error') {
              streamError = (data as { message?: string }).message || 'Roadmap generation failed'
            }
          }
        }
      } finally {
        reader.cancel().catch(() => {})
      }

      if (streamError) throw new OnboardingApiError(streamError, 502)
      if (!projectId) throw new OnboardingApiError('Roadmap generation failed', 502)
      return { projectId }
    },
    /** Accept the drafted roadmap, completing the plan-review step. */
    confirmPlan: () =>
      request<OnboardingState>('/api/onboarding/v2/plan/confirm', { method: 'POST' }),

    /** Self-heal for direct navigation before the org row exists (409
     * org_not_provisioned). POST /api/organizations requires a `name` — the
     * caller supplies the Clerk org's name (this module has no Clerk
     * context of its own), matching what useProvisionOrg's normal-path call
     * sends. */
    provisionOrganization: (name: string) =>
      request<unknown>('/api/organizations', {
        method: 'POST',
        body: JSON.stringify({ name }),
      }),

    // --- GitHub connection ---
    getGithubConnectUrl: (returnTo: string) =>
      request<{ auth_url: string }>(
        `/api/integrations/github/connect?return_to=${encodeURIComponent(returnTo)}`,
      ),
    getGithubStatus: () => request<GithubStatus>('/api/integrations/github/status'),
    disconnectGithub: () =>
      request<{ disconnected: boolean }>('/api/integrations/github/disconnect', { method: 'DELETE' }),
    listGithubRepos: (page = 1, perPage = 30) =>
      request<GithubRepo[]>(`/api/integrations/github/repos?page=${page}&per_page=${perPage}`),
    setRepo: (repoFullName: string) =>
      request<OnboardingState>('/api/onboarding/v2/repo', {
        method: 'PUT',
        body: JSON.stringify({ repoFullName }),
      }),
    skipRepo: () => request<OnboardingState>('/api/onboarding/v2/repo/skip', { method: 'POST' }),
    /** Create a new repo (org installs only) and select it. */
    createRepo: (name: string, isPrivate: boolean) =>
      request<OnboardingState>('/api/onboarding/v2/repo/create', {
        method: 'POST',
        body: JSON.stringify({ name, private: isPrivate }),
      }),

    // --- import artifacts ---
    /**
     * Analyze pasted text and/or uploaded files into a project brief + a
     * proposed roadmap. The one place this client sends multipart form data
     * instead of JSON, so it bypasses `request()` (which always sets
     * Content-Type: application/json).
     */
    async analyzeImport(formData: FormData): Promise<ImportArtifactState> {
      const token = await getToken()
      if (!token) throw new OnboardingApiError('Not authenticated', 401)
      const response = await fetch(`${apiUrl}/api/onboarding/v2/import/analyze`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: formData,
      })
      if (!response.ok) {
        throw new OnboardingApiError(await parseErrorDetail(response), response.status)
      }
      return response.json() as Promise<ImportArtifactState>
    },
    getImportState: () => request<ImportArtifactState>('/api/onboarding/v2/import'),
    applyImport: (body: { acceptedMilestoneIndexes: number[]; briefOverrides?: Record<string, unknown> }) =>
      request<OnboardingState>('/api/onboarding/v2/import/apply', {
        method: 'POST',
        body: JSON.stringify(body),
      }),

    // --- idea interview chat ---
    startChat: () => request<ChatPayload>('/api/onboarding/v2/chat/start', { method: 'POST' }),
    getChat: () => request<ChatPayload>('/api/onboarding/v2/chat'),
    completeChat: () =>
      request<OnboardingState>('/api/onboarding/v2/chat/complete', { method: 'POST' }),
    /** Recovery path: reopen a session stuck "completed" with no usable brief. */
    reopenChat: () =>
      request<OnboardingState>('/api/onboarding/v2/chat/reopen', { method: 'POST' }),

    /**
     * Send a user message; the assistant reply streams back over SSE.
     * Resolves with the final turn outcome after the stream ends.
     */
    async streamChatMessage(
      content: string,
      handlers: ChatStreamHandlers = {},
      signal?: AbortSignal,
    ): Promise<{
      reply: string
      brief: ProjectBrief | null
      briefComplete: boolean
      awaitingConfirmation: boolean
      status: ChatStatus
    }> {
      const token = await getToken()
      if (!token) throw new OnboardingApiError('Not authenticated', 401)

      const response = await fetch(`${apiUrl}/api/onboarding/v2/chat/message`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'text/event-stream',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ content }),
        signal,
      })

      if (!response.ok) {
        throw new OnboardingApiError(await parseErrorDetail(response), response.status)
      }
      if (!response.body) throw new Error('No response body for SSE stream')

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let reply = ''
      let brief: ProjectBrief | null = null
      let briefComplete = false
      let awaitingConfirmation = false
      let status: ChatStatus = 'in_progress'
      let streamError: string | null = null

      try {
        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          const events = buffer.split('\n\n')
          buffer = events.pop() ?? ''
          for (const evt of events) {
            const lines = evt.split('\n')
            const eventLine = lines.find(l => l.startsWith('event:'))?.slice(6).trim()
            const dataLine = lines.find(l => l.startsWith('data:'))?.slice(5).trim()
            if (!eventLine || !dataLine) continue
            let data: unknown
            try {
              data = JSON.parse(dataLine)
            } catch {
              continue
            }
            if (eventLine === 'token') {
              const text = (data as { text: string }).text
              reply += text
              handlers.onToken?.(text)
            } else if (eventLine === 'brief') {
              const d = data as {
                brief: ProjectBrief
                missingFields: string[]
                briefComplete: boolean
                awaitingConfirmation: boolean
              }
              brief = d.brief
              briefComplete = d.briefComplete
              awaitingConfirmation = d.awaitingConfirmation
              handlers.onBrief?.(d)
            } else if (eventLine === 'done') {
              const d = data as { messageId: string; status: ChatStatus }
              status = d.status
              handlers.onDone?.(d)
            } else if (eventLine === 'error') {
              streamError = (data as { message?: string }).message || 'Interview turn failed'
            }
          }
        }
      } finally {
        reader.cancel().catch(() => {})
      }

      if (streamError) {
        handlers.onError?.(streamError)
        throw new Error(streamError)
      }
      return { reply, brief, briefComplete, awaitingConfirmation, status }
    },
  }
}

export type OnboardingApi = ReturnType<typeof createOnboardingApi>

/** Parse the ?github=... query params GitHub's OAuth callback redirects back with. */
export function parseGithubRedirect(search: string): GithubRedirectResult {
  const params = new URLSearchParams(search)
  const github = params.get('github')
  if (github === 'connected') return { outcome: 'connected' }
  if (github === 'error') return { outcome: 'error', reason: params.get('reason') ?? 'unknown' }
  return null
}
