// useQuery wrappers over /api/platform-admin/* — same query-key/hook
// conventions as featureFlags.ts's useFeatureFlags (useApi() + react-query).

import { useQuery } from '@tanstack/react-query'

import { useApi } from '../lib/api'
import type {
  CommitsResponse,
  CostResponse,
  DashboardRange,
  OrgRollupResponse,
  OverviewResponse,
  SignupsResponse,
} from '../types/masterDashboard'

export function useOverview() {
  const api = useApi()
  return useQuery({
    queryKey: ['platform-admin', 'overview'],
    queryFn: () => api.get<OverviewResponse>('/api/platform-admin/overview'),
    staleTime: 60 * 1000,
  })
}

export function useSignupsSeries(range: DashboardRange) {
  const api = useApi()
  return useQuery({
    queryKey: ['platform-admin', 'signups', range],
    queryFn: () => api.get<SignupsResponse>(`/api/platform-admin/signups?range=${range}`),
    staleTime: 60 * 1000,
  })
}

export function useCostSeries(range: DashboardRange) {
  const api = useApi()
  return useQuery({
    queryKey: ['platform-admin', 'cost', range],
    queryFn: () => api.get<CostResponse>(`/api/platform-admin/cost?range=${range}`),
    staleTime: 60 * 1000,
  })
}

export function useCommitsSeries(range: DashboardRange) {
  const api = useApi()
  return useQuery({
    queryKey: ['platform-admin', 'commits', range],
    queryFn: () => api.get<CommitsResponse>(`/api/platform-admin/commits?range=${range}`),
    staleTime: 60 * 1000,
  })
}

export function useOrgRollup() {
  const api = useApi()
  return useQuery({
    queryKey: ['platform-admin', 'orgs'],
    queryFn: () => api.get<OrgRollupResponse>('/api/platform-admin/orgs'),
    staleTime: 60 * 1000,
  })
}
