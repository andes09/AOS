import { useState } from 'react'
import { Outlet, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { RoleSwitcher } from '../components/RoleSwitcher'
import { TeamProvider } from '../contexts/TeamContext'
import { Modal } from '../components/ui/Modal'
import { TopBar } from '../components/layout/TopBar'
import { SettingsPage } from '../pages/SettingsPage'
import { useApi } from '../lib/api'
import type { ProjectSummary } from '../features/projects/types'
import type { PlannerOutletContext, PlannerView } from '../components/planner/plannerViews'

/**
 * The app shell: a single top bar over an immersive content area. There is no
 * left sidebar — the planner is the whole surface.
 *
 * The planner's `view` lives here rather than inside the page so the top bar's
 * switcher and the planner share one value; it's handed down through the router
 * Outlet context (see PlannerPage's useOutletContext).
 */
/** Persisted collapse state for the planner's people panel. '1' = shown. */
const LANES_KEY = 'aos_planner_lanes'

export function DashboardLayout() {
  const [settingsOpen, setSettingsOpen] = useState(false)
  // Default to the detailed single-day agenda; Week stays available in the switcher.
  const [view, setView] = useState<PlannerView>('day')
  // Collapsed by default so the day view opens focused on "Up next"; remembers
  // when the user opens it. Lives here (not the planner) so the top-bar toggle
  // and the planner sidebar stay in sync.
  const [lanesHidden, setLanesHidden] = useState(() => localStorage.getItem(LANES_KEY) !== '1')
  const toggleLanes = () =>
    setLanesHidden(prev => {
      const next = !prev
      localStorage.setItem(LANES_KEY, next ? '0' : '1')
      return next
    })

  // An org can have multiple projects now (see docs/plans/2026-07-20-project-hub.md).
  // Only /app/projects/:projectId routes get the planner's view switcher/lanes
  // toggle in the top bar — the Project Hub itself has neither.
  const { projectId } = useParams<{ projectId: string }>()
  const { get } = useApi()
  const { data: project } = useQuery({
    queryKey: ['projects', projectId, 'summary'],
    queryFn: () => get<ProjectSummary>(`/api/projects/${projectId}`),
    enabled: Boolean(projectId),
  })

  const outletContext: PlannerOutletContext = { view, setView, lanesHidden, onToggleLanes: toggleLanes }

  return (
    <TeamProvider>
      <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: 'var(--color-bg-primary)' }}>
        <TopBar
          onOpenSettings={() => setSettingsOpen(true)}
          planner={
            projectId
              ? { view, onViewChange: setView, lanesHidden, onToggleLanes: toggleLanes, projectName: project?.name ?? null }
              : null
          }
        />
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
