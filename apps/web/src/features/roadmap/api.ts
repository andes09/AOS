// Framework-agnostic typed client for the roadmap API.
// No React, no styling — any UI (or even a CLI) can drive the roadmap with
// this. React apps will usually consume the hooks in ./hooks instead.

import type { RoadmapMilestone, RoadmapProject, RoadmapTask, TaskUpdate } from './types'

export type GetToken = () => Promise<string | null>

export class RoadmapApiError extends Error {
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

export function createRoadmapApi(getToken: GetToken, apiUrl: string = DEFAULT_API_URL) {
  async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const token = await getToken()
    if (!token) throw new RoadmapApiError('Not authenticated', 401)
    const response = await fetch(`${apiUrl}${path}`, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
        ...options.headers,
      },
    })
    if (!response.ok) {
      throw new RoadmapApiError(await parseErrorDetail(response), response.status)
    }
    if (response.status === 204) return undefined as T
    return response.json() as Promise<T>
  }

  return {
    /** The org's roadmap, or null if none has been generated yet. */
    getRoadmap: () => request<RoadmapProject | null>('/api/roadmap'),

    /**
     * Generate the roadmap from the onboarding brief. Idempotent: if one
     * already exists it is returned as-is. Long-running (LLM call) — expect
     * tens of seconds. 409 if onboarding hasn't produced a brief yet.
     */
    generate: () => request<RoadmapProject>('/api/roadmap/generate', { method: 'POST' }),

    /** Throw away the current roadmap and replan the whole thing. Long-running. */
    regenerate: () => request<RoadmapProject>('/api/roadmap/regenerate', { method: 'POST' }),

    /** Replan a single milestone's tasks, leaving the rest untouched. Long-running. */
    regenerateMilestone: (milestoneId: string) =>
      request<RoadmapMilestone>(`/api/roadmap/milestones/${milestoneId}/regenerate`, {
        method: 'POST',
      }),

    /** Patch a task; returns the updated task. See TaskUpdate for semantics. */
    updateTask: (taskId: string, patch: TaskUpdate) =>
      request<RoadmapTask>(`/api/roadmap/tasks/${taskId}`, {
        method: 'PATCH',
        body: JSON.stringify(patch),
      }),

    deleteTask: (taskId: string) =>
      request<void>(`/api/roadmap/tasks/${taskId}`, { method: 'DELETE' }),

    /** Self-heal for direct navigation before the org row exists (409 org_not_provisioned). */
    provisionOrganization: () => request<unknown>('/api/organizations', { method: 'POST' }),
  }
}

export type RoadmapApi = ReturnType<typeof createRoadmapApi>
