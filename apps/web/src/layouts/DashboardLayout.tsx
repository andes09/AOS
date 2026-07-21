import { useState } from 'react'
import { Outlet } from 'react-router-dom'
import { RoleSwitcher } from '../components/RoleSwitcher'
import { TeamProvider } from '../contexts/TeamContext'
import { Modal } from '../components/ui/Modal'
import { TopBar } from '../components/layout/TopBar'
import { SettingsPage } from '../pages/SettingsPage'
import type { PlannerOutletContext, PlannerView } from '../components/planner/plannerViews'

/**
 * The app shell: a single top bar over an immersive content area. There is no
 * left sidebar — the planner is the whole surface.
 *
 * The planner's `view` lives here rather than inside the page so the top bar's
 * switcher and the planner share one value; it's handed down through the router
 * Outlet context (see PlannerPage's useOutletContext).
 */
export function DashboardLayout() {
  const [settingsOpen, setSettingsOpen] = useState(false)
  // Default to the detailed single-day agenda; Week stays available in the switcher.
  const [view, setView] = useState<PlannerView>('day')

  const outletContext: PlannerOutletContext = { view, setView }

  return (
    <TeamProvider>
      <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: 'var(--color-bg-primary)' }}>
        <TopBar view={view} onViewChange={setView} onOpenSettings={() => setSettingsOpen(true)} />
        <main style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: 'var(--space-5)' }}>
          <Outlet context={outletContext} />
        </main>
      </div>

      {import.meta.env.DEV && <RoleSwitcher />}

      <Modal open={settingsOpen} onClose={() => setSettingsOpen(false)} title="Settings">
        <SettingsPage onClose={() => setSettingsOpen(false)} />
      </Modal>
    </TeamProvider>
  )
}
