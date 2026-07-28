import { Routes, Route, Navigate } from 'react-router-dom'
import { SignedIn, SignedOut, RedirectToSignIn, SignIn } from '@clerk/clerk-react'
import { DashboardLayout } from './layouts/DashboardLayout'
import { OrgProvider } from './components/OrgProvider'
import { RequireFeature } from './components/RequireFeature'
import { PlannerPage } from './pages/planner/PlannerPage'
import { ProjectHubPage } from './pages/projects/ProjectHubPage'
import { ProjectCreatePage } from './pages/projects/ProjectCreatePage'
import { OnboardingV2Page } from './pages/OnboardingV2Page'
import { InviteAcceptPage } from './pages/InviteAcceptPage'
import { MasterDashboardPage } from './pages/MasterDashboardPage'
import { McpAuthorizePage } from './pages/McpAuthorizePage'

function SignInPage() {
  return <SignIn routing="path" path="/sign-in" />
}

const testMode = import.meta.env.VITE_TEST_MODE === 'true'

export default function App() {
  return (
    <Routes>
      <Route path="/sign-in/*" element={<SignInPage />} />
      <Route path="/invite" element={<SignedIn><InviteAcceptPage /></SignedIn>} />
      {/* Onboarding is the v2 flow everywhere (GitHub + profile + idea interview). */}
      <Route path="/onboarding/*" element={
        testMode ? <OnboardingV2Page /> : <SignedIn><OnboardingV2Page /></SignedIn>
      } />
      {/* In test mode Playwright has no Clerk session, so skip the auth/org
          gates (mirrors the /onboarding route above). */}
      <Route path="/app" element={
        testMode ? <DashboardLayout /> : (
          <>
            <SignedIn>
              <OrgProvider>
                <DashboardLayout />
              </OrgProvider>
            </SignedIn>
            <SignedOut>
              <RedirectToSignIn />
            </SignedOut>
          </>
        )
      }>
        {/* Project Hub is the new landing page — an org can have multiple
            projects now (see docs/plans/2026-07-20-project-hub.md). The
            planner becomes a project-scoped nested route. Settings is a
            modal opened from the top bar, not a route. */}
        <Route index element={<ProjectHubPage />} />
        <Route path="projects/new" element={<ProjectCreatePage />} />
        <Route path="projects/:projectId" element={<PlannerPage />} />
      </Route>
      {/* Master Dashboard — a cross-org, founder-only view (see
          docs/plans/2026-07-20-master-dashboard.md). Standalone top-level
          route: no OrgProvider (it has no org context) and no sidebar.
          Gated client-side by experimental.master_dashboard so the route
          doesn't even render when the flag is off — the real access
          boundary is the backend's require_platform_admin allowlist. */}
      <Route path="/master" element={
        testMode ? <MasterDashboardPage /> : (
          <>
            <SignedIn>
              <RequireFeature flag="experimental.master_dashboard">
                <MasterDashboardPage />
              </RequireFeature>
            </SignedIn>
            <SignedOut>
              <RedirectToSignIn />
            </SignedOut>
          </>
        )
      } />
      {/* Omada MCP Server consent screen (see docs/plans/2026-07-20-omada-mcp-server.md
          and src/mcp_server/oauth_provider.py's `authorize()`, which redirects
          here). Gated the same way as /master: client-side by
          experimental.mcp_server so the route doesn't render when the flag
          is off, and by Clerk sign-in — the actual OAuth security boundary is
          the backend's /api/mcp/oauth/consent endpoint (also flag-gated). */}
      <Route path="/mcp/authorize" element={
        testMode ? <McpAuthorizePage /> : (
          <>
            <SignedIn>
              <RequireFeature flag="experimental.mcp_server">
                <McpAuthorizePage />
              </RequireFeature>
            </SignedIn>
            <SignedOut>
              <RedirectToSignIn />
            </SignedOut>
          </>
        )
      } />
      <Route path="*" element={<Navigate to="/app" replace />} />
    </Routes>
  )
}
