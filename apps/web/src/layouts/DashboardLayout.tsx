import { Outlet, NavLink } from 'react-router-dom'
import { UserButton } from '@clerk/clerk-react'
import { useAppRole } from '../hooks/useAppRole'
import { RoleSwitcher } from '../components/RoleSwitcher'
import { TeamProvider } from '../contexts/TeamContext'
import { TeamSwitcher } from '../components/TeamSwitcher'
import { ThemeToggle } from '../components/ui/ThemeToggle'

export function DashboardLayout() {
  const { appRole } = useAppRole()
  const canSeeLead = appRole === 'lead' || appRole === 'exec' || appRole === 'admin'
  const canSeeExec = appRole === 'exec' || appRole === 'admin'

  return (
    <TeamProvider>
      <div style={{ display: 'flex', height: '100vh' }}>
        <nav style={{ width: 220, padding: '1rem', borderRight: '1px solid var(--color-border)', display: 'flex', flexDirection: 'column', background: 'var(--color-bg-secondary)' }}>
          <div style={{ fontWeight: 700, fontSize: '1.125rem', marginBottom: '0.75rem' }}>AgileOS</div>
          <TeamSwitcher />
          <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: '0.25rem', flex: 1 }}>
            <li><NavLink to="/app/sprint-planner">Sprint Planner</NavLink></li>
            <li><NavLink to="/app/velocity-mirror">Velocity Mirror</NavLink></li>
            {canSeeLead && (
              <>
                <li style={{ marginTop: '1rem', fontSize: '0.7rem', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', color: '#6b7280' }}>Intelligence</li>
                <li><NavLink to="/app/dependency-radar">Dependency Radar</NavLink></li>
                <li><NavLink to="/app/retrospective">Retrospective</NavLink></li>
                <li><NavLink to="/app/multi-team">Multi-Team</NavLink></li>
              </>
            )}
            {canSeeExec && (
              <>
                <li style={{ marginTop: '1rem', fontSize: '0.7rem', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', color: '#6b7280' }}>Executive</li>
                <li><NavLink to="/app/exec-dashboard">Exec Dashboard</NavLink></li>
              </>
            )}
            <li><NavLink to="/app/settings">Settings</NavLink></li>
          </ul>
          <UserButton />
        </nav>
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
          <header style={{
            height: 48,
            borderBottom: '1px solid var(--color-border)',
            background: 'var(--color-bg-elevated)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'flex-end',
            padding: '0 16px',
            gap: 8,
            flexShrink: 0,
          }}>
            <ThemeToggle />
          </header>
          <main style={{ flex: 1, padding: '1.5rem', overflowY: 'auto' }}>
            <Outlet />
          </main>
        </div>
        <RoleSwitcher />
      </div>
    </TeamProvider>
  )
}
