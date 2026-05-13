import { ReactNode } from 'react'
import { Navigate } from 'react-router-dom'

import { FeatureFlags, useFeatureFlags } from '../featureFlags'

type Props = {
  flag: keyof FeatureFlags
  children: ReactNode
  redirectTo?: string
}

export function RequireFeature({ flag, children, redirectTo = '/app' }: Props) {
  const { data, isLoading } = useFeatureFlags()
  if (isLoading || !data) return null
  if (!data[flag]) return <Navigate to={redirectTo} replace />
  return <>{children}</>
}
