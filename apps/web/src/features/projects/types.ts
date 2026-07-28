// Project Hub API contract types — mirrors /api/projects/* payloads.
// See apps/api/src/routers/projects.py.

export type ProjectStatus = 'active' | 'finished' | 'archived'

export interface ProjectSummary {
  id: string
  name: string
  summary: string | null
  purpose: string | null
  status: ProjectStatus
  createdAt: string | null
  updatedAt: string | null
  hasRoadmap: boolean
}

export interface ProjectCreationChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  createdAt: string | null
}

export interface ProjectCreationSessionState {
  sessionId: string
  status: string
  messages: ProjectCreationChatMessage[]
  brief: Record<string, unknown> | null
  briefComplete: boolean
}
