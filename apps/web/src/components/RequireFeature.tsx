import { ReactNode } from 'react'
import { Navigate } from 'react-router-dom'

import { FlagPath, useFeature, useFeatureFlags } from '../featureFlags'

type Props = {
  flag: FlagPath
  children: ReactNode
  redirectTo?: string
}

export function RequireFeature({ flag, children, redirectTo = '/app' }: Props) {
  const { data, isLoading } = useFeatureFlags()
  const enabled = useFeature(flag)
  if (isLoading || !data) return null
  if (!enabled) return <Navigate to={redirectTo} replace />
  return <>{children}</>
}
