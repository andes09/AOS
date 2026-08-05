// apps/web/src/pages/planner/useDriftSignal.ts
//
// Data layer for the drift banner: where the plan and the repo disagree.
//
// Unlike useActivitySummary (whose GET has the side effect of refreshing
// last_active_at, so it must never refetch mid-session), this endpoint is
// purely computed — refetching is harmless. It still gets a generous staleTime
// because the underlying facts only move when a webhook lands or the 6-hourly
// reconciliation sweep runs, so polling harder would just cost round trips.
//
// The endpoint returns an empty signal list rather than 404ing while
// experimental.roadmap_drift is off, so the banner can mount unconditionally
// and self-gate — the same posture as WelcomeBackBanner.

import { useQuery } from '@tanstack/react-query'
import { useApi } from '../../lib/api'

export type DriftSeverity = 'warning' | 'info'

export type DriftSignalKind =
  | 'stalled_milestone'
  | 'unplanned_work'
  | 'silent_repo'
  | 'ahead_of_plan'

export interface DriftSignal {
  kind: DriftSignalKind
  severity: DriftSeverity
  headline: string
  detail: string
  milestoneIds: string[]
  evidence: string[]
}

export interface DriftReport {
  hasDrift: boolean
  computedAt?: string
  windowDays?: number
  repoConnected: boolean
  signals: DriftSignal[]
}

export const DRIFT_KEY = (projectId: string) => ['roadmap', 'drift', projectId] as const

export function useDriftSignal(projectId: string | undefined) {
  const { get } = useApi()
  return useQuery({
    queryKey: DRIFT_KEY(projectId ?? ''),
    enabled: Boolean(projectId),
    queryFn: () => get<DriftReport>(`/api/projects/${projectId}/roadmap/drift`),
    staleTime: 5 * 60 * 1000,
    retry: false,
  })
}

/** Milestone ids called out by any warning-level signal — used to mark the
 *  affected rings in MilestoneMap, so the banner's claim is traceable to a
 *  specific place on the plan rather than being an unanchored assertion. */
export function driftingMilestoneIds(report: DriftReport | undefined): Set<string> {
  const ids = new Set<string>()
  for (const signal of report?.signals ?? []) {
    if (signal.severity !== 'warning') continue
    for (const id of signal.milestoneIds) ids.add(id)
  }
  return ids
}
