import { ReactNode, useEffect } from 'react'
import { useOrganization } from '@clerk/clerk-react'
import { useNavigate } from 'react-router-dom'
import { useProvisionOrg } from '../hooks/useProvisionOrg'

interface Props {
  children: ReactNode
}

/**
 * Wraps authenticated app routes. Provisions the org in the local DB
 * on first load, then renders children. Redirects new orgs to onboarding.
 */
export function OrgProvider({ children }: Props) {
  const { organization, isLoaded } = useOrganization()
  const { provisioned, isNew, error } = useProvisionOrg()
  const navigate = useNavigate()

  useEffect(() => {
    if (provisioned && isNew) {
      navigate('/onboarding/team-setup', { replace: true })
    }
  }, [provisioned, isNew])

  if (!isLoaded) {
    return (
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        height: '100vh',
        color: '#64748b',
        fontSize: 14,
      }}>
        Setting up workspace…
      </div>
    )
  }

  if (!organization) {
    return (
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        height: '100vh',
        color: '#64748b',
        fontSize: 14,
      }}>
        No organisation found. Please sign in with an organisation account.
      </div>
    )
  }

  if (!provisioned && !error) {
    return (
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        height: '100vh',
        color: '#64748b',
        fontSize: 14,
      }}>
        Setting up workspace…
      </div>
    )
  }

  if (error) {
    return (
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        height: '100vh',
        color: '#64748b',
        fontSize: 14,
      }}>
        Failed to initialize workspace. Please refresh.
      </div>
    )
  }

  return <>{children}</>
}
