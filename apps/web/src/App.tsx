import { Routes, Route, Navigate } from 'react-router-dom'
import { SignedIn, SignedOut, RedirectToSignIn, SignIn } from '@clerk/clerk-react'
import { DashboardLayout } from './layouts/DashboardLayout'
import { OrgProvider } from './components/OrgProvider'
import { SprintPlannerPage } from './pages/SprintPlannerPage'
import { VelocityMirrorPage } from './pages/VelocityMirrorPage'
import { ExecDashboardPage } from './pages/ExecDashboardPage'
import { DependencyRadarPage } from './pages/DependencyRadarPage'
import { RetrospectivePage } from './pages/RetrospectivePage'
import { OnboardingPage } from './pages/OnboardingPage'
import { SettingsPage } from './pages/SettingsPage'

function SignInPage() {
  return <SignIn routing="path" path="/sign-in" />
}

export default function App() {
  return (
    <Routes>
      <Route path="/sign-in/*" element={<SignInPage />} />
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
        <Route path="exec-dashboard" element={<ExecDashboardPage />} />
        <Route path="dependency-radar" element={<DependencyRadarPage />} />
        <Route path="retrospective" element={<RetrospectivePage />} />
        <Route path="settings" element={<SettingsPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/app" replace />} />
    </Routes>
  )
}
