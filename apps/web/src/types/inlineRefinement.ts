// apps/web/src/types/inlineRefinement.ts
// Initiative B — Inline Ticket Refinement. Shared contracts consumed by
// ReviewRefineCarousel and the planner wiring.

// The persisted Scope Cop suggestion. Inner keys are snake_case because the
// payload is stored verbatim from Claude's tool output (see
// scope_cop.suggested_revision). All fields nullable/omittable.
export interface SuggestedRevision {
  title?: string | null
  description?: string | null
  acceptance_criteria?: string[] | null
  story_points?: number | null
}

// One entry in SprintPlanResponse.scopeCopResults[] (camelCase — see
// sprint_brain._sprint_plan_response).
export interface ScopeCopResult {
  ticketKey: string
  ticketTitle: string
  readinessScore: number
  status: 'ready' | 'needs_work' | 'blocked'
  issues: string[]
  suggestions: string[]
  stackAlignment: number | null
  matchedIdentifierCount: number | null
  suggestedRevision: SuggestedRevision | null
  fetchedUpdatedAt: string | null
}

// Normalized editable shape used throughout the editor UI (camelCase, AC as a
// string[]). Both the read-only "original" side and the editable "current"
// side use this shape.
export interface TicketFields {
  title: string
  description: string
  acceptanceCriteria: string[]
  storyPoints: number | null
}

// Per-ticket bundle the modal builds from plan.assignments + scopeCopResults.
export interface RefinementTicket {
  ticketKey: string
  developerId: string
  developerName: string
  assigneeAccountId?: string | null
  reasoning: string
  readinessScore: number | null
  status: ScopeCopResult['status'] | null
  original: TicketFields
  suggested: TicketFields
  fetchedUpdatedAt: string | null
}

// ---- Commit contract (SB-8). CommitPlanRequest has NO camel alias on the
// backend, so the request body must be snake_case. ----

export interface CommitRevision {
  title?: string
  description?: string
  acceptance_criteria?: string[]
  story_points?: number
}

export interface CommitApproval {
  ticket_key: string
  revision?: CommitRevision | null
  approved_at: string
  fetched_updated_at?: string | null
  assignee_account_id?: string | null
  developer_id?: string | null
}

export interface CommitPlanRequest {
  team_id: string
  sprint_id?: string | null
  approvals: CommitApproval[]
}

export interface CommitConflict {
  ticket_key: string
  reason: string
}

export interface CommitPlanResponse {
  plan_id: string
  committed: string[]
  conflicts: CommitConflict[]
}

// ---- Single-ticket "Refine" contract (SB-7). RevisionPreviewResponse uses
// camelCase aliases; PatchRevisionRequest accepts camelCase (populate_by_name). ----

export interface RevisionPreviewResponse {
  original: { title?: string | null; description?: string | null; story_points?: number | null }
  suggestedRevision: SuggestedRevision | null
  fetchedUpdatedAt: string | null
}

export interface PatchRevisionRequest {
  revision: {
    title?: string | null
    description?: string | null
    acceptanceCriteria?: string[] | null
    storyPoints?: number | null
  }
  fetchedUpdatedAt: string
  teamId: string
}
