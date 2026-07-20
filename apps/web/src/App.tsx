import { Routes, Route, Navigate } from 'react-router-dom'
import { SignedIn, SignedOut, RedirectToSignIn, SignIn } from '@clerk/clerk-react'
import { DashboardLayout } from './layouts/DashboardLayout'
import { OrgProvider } from './components/OrgProvider'
import { RoadmapPage } from './pages/roadmap/RoadmapPage'
import { PlannerPage } from './pages/planner/PlannerPage'
import { OnboardingV2Page } from './pages/OnboardingV2Page'
import { SettingsPage } from './pages/SettingsPage'
import { CalibrationSuggestionsPage } from './pages/settings/CalibrationSuggestionsPage'
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
        <Route index element={<Navigate to="roadmap" replace />} />
        <Route path="roadmap" element={<RoadmapPage />} />
        <Route path="sprint-planner" element={<PlannerPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="settings/calibration" element={<CalibrationSuggestionsPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/app" replace />} />
    </Routes>
  )
}
