import { useAuth } from '@clerk/clerk-react'
import { useQuery } from '@tanstack/react-query'

import { useApi } from './lib/api'

export type FeatureFlags = {
  roadmap_generation: boolean
  roadmap_chat: boolean
  experimental: {
    enabled: boolean
    import_artifacts?: boolean
    github_autocomplete?: boolean
    master_dashboard?: boolean
    mcp_server?: boolean
    tech_stack_step?: boolean
    roadmap_drift?: boolean
  }
  /** The planner's own kill switch, plus one sub-flag per view in the
   *  switcher (see VIEW_OPTIONS) — 'day' has no flag, it's the fallback
   *  every view degrades to when its own flag is off. */
  planner: {
    enabled: boolean
    week_view?: boolean
    daily_calendar_view?: boolean
    board_view?: boolean
  }
}

type FeaturesResponse = {
  environment: string
  features: FeatureFlags
}

type FlatFlag = Exclude<keyof FeatureFlags, 'experimental' | 'planner'>
type ExperimentalFlag = keyof FeatureFlags['experimental']
type PlannerFlag = keyof FeatureFlags['planner']

/** "flag_name" for a top-level flag, or "group.sub_flag" for a grouped one. */
export type FlagPath = FlatFlag | `experimental.${ExperimentalFlag}` | `planner.${PlannerFlag}`

function readFlag(data: FeatureFlags, path: FlagPath): boolean {
  if (path.startsWith('experimental.')) {
    const key = path.slice('experimental.'.length) as ExperimentalFlag
    return data.experimental[key] ?? false
  }
  if (path.startsWith('planner.')) {
    const key = path.slice('planner.'.length) as PlannerFlag
    return data.planner[key] ?? false
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
