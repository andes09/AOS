import { Outlet, NavLink } from 'react-router-dom'
import { UserButton } from '@clerk/clerk-react'
import { useAppRole } from '../hooks/useAppRole'

export function DashboardLayout() {
  const { appRole } = useAppRole()
  const canSeeLead = appRole === 'lead' || appRole === 'exec' || appRole === 'admin'
  const canSeeExec = appRole === 'exec' || appRole === 'admin'

  return (
    <div style={{ display: 'flex', height: '100vh' }}>
      <nav style={{ width: 220, padding: '1rem', borderRight: '1px solid #e5e7eb', display: 'flex', flexDirection: 'column' }}>
        <div style={{ fontWeight: 700, fontSize: '1.125rem', marginBottom: '1.5rem' }}>AgileOS</div>
        <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: '0.25rem', flex: 1 }}>
          <li><NavLink to="/app/sprint-planner">Sprint Planner</NavLink></li>
          <li><NavLink to="/app/velocity-mirror">Velocity Mirror</NavLink></li>
          {canSeeLead && <li><NavLink to="/app/dependency-radar">Dependency Radar</NavLink></li>}
          {canSeeLead && <li><NavLink to="/app/retrospective">Retrospective</NavLink></li>}
          {canSeeExec && <li><NavLink to="/app/exec-dashboard">Exec Dashboard</NavLink></li>}
          <li><NavLink to="/app/settings">Settings</NavLink></li>
        </ul>
        <UserButton />
      </nav>
      <main style={{ flex: 1, padding: '1.5rem', overflowY: 'auto' }}>
        <Outlet />
      </main>
    </div>
  )
}
