import { Routes, Route, Navigate } from 'react-router-dom'
import { SignedIn, SignedOut, RedirectToSignIn, SignIn } from '@clerk/clerk-react'
import { DashboardLayout } from './layouts/DashboardLayout'
import { OrgProvider } from './components/OrgProvider'
import { RequireFeature } from './components/RequireFeature'
import { SprintPlannerPage } from './pages/SprintPlannerPage'
import { VelocityMirrorPage } from './pages/VelocityMirrorPage'
import { ExecDashboardPage } from './pages/ExecDashboardPage'
import { DependencyRadarPage } from './pages/DependencyRadarPage'
import { RetrospectivePage } from './pages/RetrospectivePage'
import { OnboardingPage } from './pages/OnboardingPage'
import { TeamSetupPage } from './pages/TeamSetupPage'
import { SettingsPage } from './pages/SettingsPage'
import { TeamGlossaryPage } from './pages/settings/TeamGlossaryPage'
import { MultiTeamDashboardPage } from './pages/MultiTeamDashboardPage'
import { InviteAcceptPage } from './pages/InviteAcceptPage'

function SignInPage() {
  return <SignIn routing="path" path="/sign-in" />
}

export default function App() {
  return (
    <Routes>
      <Route path="/sign-in/*" element={<SignInPage />} />
      <Route path="/invite" element={<SignedIn><InviteAcceptPage /></SignedIn>} />
      <Route path="/onboarding/team-setup" element={
        <SignedIn><TeamSetupPage /></SignedIn>
      } />
      <Route path="/onboarding/*" element={
        <SignedIn><OnboardingPage /></SignedIn>
      } />
      <Route path="/app" element={
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
      }>
        <Route index element={<Navigate to="sprint-planner" replace />} />
        <Route path="sprint-planner" element={<SprintPlannerPage />} />
        <Route path="velocity-mirror" element={<VelocityMirrorPage />} />
        <Route path="exec-dashboard" element={
          <RequireFeature flag="exec_dashboard"><ExecDashboardPage /></RequireFeature>
        } />
        <Route path="dependency-radar" element={
          <RequireFeature flag="dependency_radar"><DependencyRadarPage /></RequireFeature>
        } />
        <Route path="retrospective" element={<RetrospectivePage />} />
        <Route path="multi-team" element={
          <RequireFeature flag="multi_team_dashboard"><MultiTeamDashboardPage /></RequireFeature>
        } />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="settings/glossary" element={<TeamGlossaryPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/app" replace />} />
    </Routes>
  )
}
