import { useAuth } from '@clerk/clerk-react'
import { useQuery } from '@tanstack/react-query'

import { useApi } from './lib/api'

export type FeatureFlags = {
  push_to_jira: boolean
  scope_check_v2: boolean
  multi_team_dashboard: boolean
  exec_dashboard: boolean
  data_collection_phase: boolean
  retro_pattern_detection: boolean
  skill_based_assignment: boolean
  slack_alerts: boolean
  dependency_radar: boolean
  omada_simulator: boolean
}

type FeaturesResponse = {
  environment: string
  features: FeatureFlags
}

export function useFeatureFlags() {
  const { isLoaded, isSignedIn } = useAuth()
  const api = useApi()

  return useQuery<FeatureFlags>({
    queryKey: ['feature-flags'],
    enabled: isLoaded && isSignedIn,
    queryFn: async () => {
      const data = await api.get<FeaturesResponse>('/api/features')
      return data.features
    },
    staleTime: 5 * 60 * 1000,
  })
}

export function useFeature(flagName: keyof FeatureFlags): boolean {
  const { data } = useFeatureFlags()
  return data?.[flagName] ?? false
}
