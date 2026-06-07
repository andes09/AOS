import { ReactNode, useEffect } from 'react'
import { useOrganization } from '@clerk/clerk-react'
import { CreateOrganization } from '@clerk/clerk-react'
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
  const { provisioned, onboardingCompleted, error } = useProvisionOrg()
  const navigate = useNavigate()

  useEffect(() => {
    if (provisioned && !onboardingCompleted) {
      localStorage.removeItem('aos_team_setup_step')
      localStorage.removeItem('aos_onboarding_step')
      navigate('/onboarding/team-setup', { replace: true })
    }
  }, [provisioned, onboardingCompleted])

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
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        height: '100vh',
        gap: 16,
        background: '#f7f8fa',
      }}>
        <div style={{ color: '#1a1d23', fontFamily: 'system-ui, sans-serif', fontSize: 18, fontWeight: 700 }}>
          Create your workspace
        </div>
        <div style={{ color: '#64748b', fontFamily: 'system-ui, sans-serif', fontSize: 14, marginBottom: 8 }}>
          You need an organisation to use Omada.
        </div>
        <CreateOrganization afterCreateOrganizationUrl="/app" />
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

  if (provisioned && !onboardingCompleted) {
    return null
  }

  return <>{children}</>
}
