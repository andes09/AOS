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

export type ScopeCopStatus = 'not_analyzed' | 'all_ready' | 'has_issues'
export type DepRadarStatus = 'not_scanned' | 'no_risks' | 'has_risks'
export type RetroPatternStatus = 'no_data' | 'no_active_patterns' | 'has_patterns'

export interface ScopeWarning {
  ticketId: string
  status: 'needs_work' | 'blocked'
  issues: string[]
}

export interface DependencyWarning {
  ticketId: string
  riskLevel: 'high'
  description: string | null
}

export interface EnrichmentStatus {
  scopeCop: ScopeCopStatus
  dependencyRadar: DepRadarStatus
  retroPatterns: RetroPatternStatus
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
