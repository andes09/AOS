// Response shapes for /api/platform-admin/* (src/routers/platform_admin.py).
// A cross-org, founder-only view — distinct from the org-scoped exec
// dashboard types elsewhere in this app.

export type DashboardRange = '7d' | '30d' | '90d' | 'all'

export interface OverviewResponse {
  totalOrgs: number
  totalUsers: number
  cost: {
    allTimeUsd: number
    last30dUsd: number
  }
  commits: {
    allTime: number
    last30d: number
  }
}

export interface SignupsPoint {
  date: string
  newUsers: number
  newOrgs: number
  cumulativeUsers: number
  cumulativeOrgs: number
}

export interface SignupsResponse {
  range: DashboardRange
  series: SignupsPoint[]
}

export interface CostPoint {
  date: string
  anthropicUsd: number
  groqUsd: number
  totalUsd: number
}

export interface CostResponse {
  range: DashboardRange
  series: CostPoint[]
}

export interface CommitsPoint {
  date: string
  commits: number
}

export interface CommitsResponse {
  range: DashboardRange
  series: CommitsPoint[]
}

export interface OrgRollupRow {
  id: string
  name: string
  slug: string
  createdAt: string
  userCount: number
  costAllTimeUsd: number
  cost30dUsd: number
  commitsAllTime: number
  commits30d: number
  onboardingCompleted: boolean
}

export interface OrgRollupResponse {
  orgs: OrgRollupRow[]
}
