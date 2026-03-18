import { ReactNode } from 'react'
import { useOrganization } from '@clerk/clerk-react'
import { useProvisionOrg } from '../hooks/useProvisionOrg'

interface Props {
  children: ReactNode
}

/**
 * Wraps authenticated app routes. Provisions the org in the local DB
 * on first load, then renders children. Shows a spinner while provisioning.
 */
export function OrgProvider({ children }: Props) {
  const { organization, isLoaded } = useOrganization()
  const { provisioned, error } = useProvisionOrg()

  if (!isLoaded || (!provisioned && !error)) {
    return (
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        height: '100vh',
        color: '#64748b',
        fontSize: 14,
      }}>
        {error ? 'Failed to initialize workspace. Please refresh.' : 'Setting up workspace…'}
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

  return <>{children}</>
}
