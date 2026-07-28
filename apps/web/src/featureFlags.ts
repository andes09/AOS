import { useAuth } from '@clerk/clerk-react'
import { useQuery } from '@tanstack/react-query'

import { useApi } from './lib/api'

export type FeatureFlags = {
  slack_alerts: boolean
  roadmap_generation: boolean
  planner: boolean
  roadmap_chat: boolean
  experimental: {
    enabled: boolean
    import_artifacts?: boolean
    github_autocomplete?: boolean
    master_dashboard?: boolean
    mcp_server?: boolean
  }
}

type FeaturesResponse = {
  environment: string
  features: FeatureFlags
}

type FlatFlag = Exclude<keyof FeatureFlags, 'experimental'>
type ExperimentalFlag = keyof FeatureFlags['experimental']

/** "flag_name" for a top-level flag, or "experimental.sub_flag" for a grouped one. */
export type FlagPath = FlatFlag | `experimental.${ExperimentalFlag}`

function readFlag(data: FeatureFlags, path: FlagPath): boolean {
  if (path.startsWith('experimental.')) {
    const key = path.slice('experimental.'.length) as ExperimentalFlag
    return data.experimental[key] ?? false
  }
  return data[path as FlatFlag] ?? false
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

export function useFeature(flag: FlagPath): boolean {
  const { data } = useFeatureFlags()
  return data ? readFlag(data, flag) : false
}
