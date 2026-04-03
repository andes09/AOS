import { useQuery } from '@tanstack/react-query'
import { useAuth } from '@clerk/clerk-react'
import { useApi } from '../lib/api'

interface RoleResponse {
  role: string
}

export function useAppRole() {
  const { isLoaded, isSignedIn } = useAuth()
  const { get } = useApi()

  const { data } = useQuery<RoleResponse>({
    queryKey: ['app-role'],
    queryFn: () => get<RoleResponse>('/api/users/me/role'),
    enabled: isLoaded && isSignedIn,
    staleTime: 5 * 60 * 1000,
  })

  return { appRole: data?.role ?? '' }
}
