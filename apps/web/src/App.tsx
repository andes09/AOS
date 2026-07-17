import { Routes, Route, Navigate } from 'react-router-dom'
import { SignedIn, SignedOut, RedirectToSignIn, SignIn } from '@clerk/clerk-react'
import { DashboardLayout } from './layouts/DashboardLayout'
import { OrgProvider } from './components/OrgProvider'
import { RequireFeature } from './components/RequireFeature'
import { PlannerCalendarPage } from './pages/planner/PlannerCalendarPage'
import { VelocityMirrorPage } from './pages/VelocityMirrorPage'
import { ExecDashboardPage } from './pages/ExecDashboardPage'
import { DependencyRadarPage } from './pages/DependencyRadarPage'
import { RetrospectivePage } from './pages/RetrospectivePage'
import { OnboardingV2Page } from './pages/OnboardingV2Page'
import { SettingsPage } from './pages/SettingsPage'
import { TeamGlossaryPage } from './pages/settings/TeamGlossaryPage'
import { CalibrationSuggestionsPage } from './pages/settings/CalibrationSuggestionsPage'
import { MultiTeamDashboardPage } from './pages/MultiTeamDashboardPage'
import { InviteAcceptPage } from './pages/InviteAcceptPage'

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
        <Route path="sprint-planner" element={<PlannerCalendarPage />} />
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
        <Route path="settings/calibration" element={<CalibrationSuggestionsPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/app" replace />} />
    </Routes>
  )
}
