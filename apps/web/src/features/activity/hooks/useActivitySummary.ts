// The re-engagement banner's data layer. One GET; the request itself is what
// refreshes last_active_at server-side, so we deliberately do NOT refetch on
// window focus or treat the data as stale — a refetch mid-session would touch
// the timestamp again and make the banner vanish while the user is still here.
// A genuine "next visit" is a fresh page load, which starts a new query cache.

import { useQuery } from '@tanstack/react-query'
import { useApi } from '../../../lib/api'
import type { ActivitySummary } from '../types'

export const ACTIVITY_SUMMARY_KEY = ['activity', 'summary'] as const

export function useActivitySummary() {
  const { get } = useApi()
  return useQuery({
    queryKey: ACTIVITY_SUMMARY_KEY,
    queryFn: () => get<ActivitySummary>('/api/activity/summary'),
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    retry: false,
  })
}
