// apps/web/src/types/sprint.ts

export interface Assignment {
  ticket_id: string
  title: string
  developer_id: string
  developer_name: string
  reasoning: string
  confidence: number
  story_points: number
}

export interface ScopeWarning {
  ticketId: string
  status: string
  issues: string[]
}

export interface DependencyWarning {
  ticketId: string
  riskLevel: string
  description: string | null
}

export interface EnrichmentStatus {
  scopeCop: 'not_analyzed' | 'all_ready' | 'has_issues'
  dependencyRadar: 'not_scanned' | 'no_risks' | 'has_risks'
  retroPatterns: 'no_data' | 'no_active_patterns' | 'has_patterns'
}

export interface SprintPlanResponse {
  team_id: string
  sprint_start: string
  assignments: Assignment[]
  confidence_score: number
  summary: string
  warnings: string[]
  what_if_dropped: Record<string, number>
  developers: Record<string, string>
  scopeWarnings: ScopeWarning[]
  dependencyWarnings: DependencyWarning[]
  historicalWarnings: string[]
  enrichmentStatus: EnrichmentStatus
}

export interface WhatIfResponse {
  confidence_score: number
  what_if_dropped: Record<string, number>
}

export interface Ticket {
  ticket_id: string
  title: string
  developer_id: string
  developer_name: string
  story_points: number
  confidence: number
}

export interface JiraBoard {
  id: string
  name: string
  project_key: string
}

export interface PushToJiraResponse {
  jiraSprintId: number
  sprintUrl: string
  pushedTickets: number
  unassignedWarnings: string[]
}
