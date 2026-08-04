// Anti-dormancy re-engagement summary — payload for the "welcome back" banner.
// Mirrors src/services/activity.re_engagement_summary on the API. Org-scoped:
// last_active_at is a fact about a person, so the summary aggregates across the
// org's active projects. See docs/plans/2026-07-20-anti-dormancy-mvp.md.

export interface NextUpTask {
  id: string
  shortId: string | null
  title: string
  scheduledDate: string | null
}

export interface ActivitySummary {
  /** Away long enough to greet as returning (server-side threshold). */
  isReturning: boolean
  /** Whole days since the previous activity; null on a first-ever visit. */
  daysSinceLastActive: number | null
  tasksRemaining: number
  tasksCompletedSinceLastVisit: number
  overdueCount: number
  /** Capped next-step list — the antidote to an overwhelming full tree. */
  nextUp: NextUpTask[]
}
