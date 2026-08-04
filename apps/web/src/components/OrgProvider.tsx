import { ReactNode, useEffect, useRef, useState } from 'react'
import { useOrganization, useOrganizationList, useUser } from '@clerk/clerk-react'
import { useNavigate } from 'react-router-dom'
import { useProvisionOrg } from '../hooks/useProvisionOrg'

interface Props {
  children: ReactNode
}

/** Name for the workspace we silently create — founders never see or pick it. */
function personalWorkspaceName(user: ReturnType<typeof useUser>['user']): string {
  const base =
    user?.firstName?.trim() ||
    user?.username?.trim() ||
    user?.primaryEmailAddress?.emailAddress?.split('@')[0] ||
    'My'
  return `${base}'s Workspace`
}

/**
 * Wraps authenticated app routes. Provisions the org in the local DB
 * on first load, then renders children. Redirects new orgs to onboarding.
 *
 * The whole backend is org-scoped off the JWT's `org_id` claim, which Clerk
 * only emits when an organisation is *active*. Rather than make founders sit
 * through Clerk's <CreateOrganization /> screen, we adopt one for them: reuse
 * their first existing membership, or create a personal workspace, then set it
 * active. Purely a signup-friction change — nothing downstream of the claim
 * knows the difference.
 */
export function OrgProvider({ children }: Props) {
  const { organization, isLoaded } = useOrganization()
  const { isLoaded: listLoaded, setActive, createOrganization, userMemberships } =
    useOrganizationList({ userMemberships: true })
  const { user } = useUser()
  const { provisioned, onboardingCompleted, error } = useProvisionOrg()
  const navigate = useNavigate()

  // One attempt per mount: Clerk re-renders several times while the org
  // becomes active, and creating a second workspace would be unrecoverable.
  const claimedRef = useRef(false)
  const [orgError, setOrgError] = useState<string | null>(null)

  useEffect(() => {
    if (organization || claimedRef.current) return
    if (!isLoaded || !listLoaded || !setActive || !createOrganization) return
    if (userMemberships.isLoading) return

    claimedRef.current = true
    const existing = userMemberships.data?.[0]?.organization
    const ensured = existing
      ? Promise.resolve(existing)
      : createOrganization({ name: personalWorkspaceName(user) })

    ensured
      .then(org => setActive({ organization: org.id }))
      .catch(err => {
        setOrgError(err instanceof Error ? err.message : 'Could not set up your workspace.')
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [organization, isLoaded, listLoaded, userMemberships.isLoading])

  useEffect(() => {
    if (provisioned && !onboardingCompleted) {
      navigate('/onboarding', { replace: true })
    }
  }, [provisioned, onboardingCompleted])

  if (orgError) {
    return <Centered>Failed to set up your workspace ({orgError}). Please refresh.</Centered>
  }

  // Covers both "Clerk still loading" and "we're adopting/creating the org".
  if (!isLoaded || !organization) {
    return <Centered>Setting up workspace…</Centered>
  }

  if (!provisioned && !error) {
    return <Centered>Setting up workspace…</Centered>
  }

  if (error) {
    return <Centered>Failed to initialize workspace. Please refresh.</Centered>
  }

  if (provisioned && !onboardingCompleted) {
    return null
  }

  return <>{children}</>
}

function Centered({ children }: { children: ReactNode }) {
  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      height: '100vh',
      color: '#64748b',
      fontSize: 14,
      padding: 24,
      textAlign: 'center',
    }}>
      {children}
    </div>
  )
}
