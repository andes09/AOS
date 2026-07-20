import { CSSProperties, useState } from 'react'
import { Outlet, NavLink } from 'react-router-dom'
import { UserButton } from '@clerk/clerk-react'
import { Settings } from 'lucide-react'
import { RoleSwitcher } from '../components/RoleSwitcher'
import { TeamProvider } from '../contexts/TeamContext'
import { TeamSwitcher } from '../components/TeamSwitcher'
import { ThemeToggle } from '../components/ui/ThemeToggle'
import { Modal } from '../components/ui/Modal'
import { SettingsPage } from '../pages/SettingsPage'

function navItemStyle(isActive: boolean): CSSProperties {
  return {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    height: 32,
    padding: '0 10px',
    borderRadius: 'var(--radius-md)',
    fontSize: 'var(--text-sm)',
    fontFamily: 'var(--font-sans)',
    fontWeight: 'var(--font-weight-medium)' as CSSProperties['fontWeight'],
    color: isActive ? 'var(--color-accent)' : 'var(--color-text-secondary)',
    background: isActive ? 'var(--color-accent-subtle)' : 'transparent',
    textDecoration: 'none',
    transition: 'background 0.1s, color 0.1s',
    cursor: 'pointer',
    whiteSpace: 'nowrap',
  }
}

export function DashboardLayout() {
  const [settingsOpen, setSettingsOpen] = useState(false)

  return (
    <TeamProvider>
      <div style={{ display: 'flex', height: '100vh', background: 'var(--color-bg-primary)' }}>

        {/* Sidebar */}
        <nav style={{
          width: 220,
          flexShrink: 0,
          padding: '0 8px 16px',
          borderRight: '1px solid var(--color-border)',
          display: 'flex',
          flexDirection: 'column',
          background: 'var(--color-bg-secondary)',
          overflowY: 'auto',
        }}>
          {/* Logo row */}
          <div style={{
            height: 48,
            display: 'flex',
            alignItems: 'center',
            padding: '0 10px',
            fontFamily: '"DM Sans", var(--font-sans)',
            fontWeight: 600,
            fontSize: 18,
            letterSpacing: '-0.02em',
            color: 'var(--color-text-primary)',
            borderBottom: '1px solid var(--color-border)',
            marginBottom: 8,
            flexShrink: 0,
          }}>
            Omada
          </div>

          <div style={{ marginBottom: 8 }}>
            <TeamSwitcher />
          </div>

          <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: 2, flex: 1 }}>
            <li>
              <NavLink to="/app/roadmap" style={({ isActive }) => navItemStyle(isActive)}>
                Roadmap
              </NavLink>
            </li>
            <li>
              <NavLink to="/app/sprint-planner" style={({ isActive }) => navItemStyle(isActive)}>
                Planner
              </NavLink>
            </li>
          </ul>

          {/* Profile + settings gear, bottom-left */}
          <div style={{ padding: '8px 10px 0', display: 'flex', alignItems: 'center', gap: 8 }}>
            <UserButton />
            <button
              onClick={() => setSettingsOpen(true)}
              aria-label="Settings"
              title="Settings"
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                width: 30,
                height: 30,
                borderRadius: 'var(--radius-md)',
                background: 'transparent',
                border: '1px solid var(--color-border)',
                color: 'var(--color-text-secondary)',
                cursor: 'pointer',
              }}
            >
              <Settings size={16} />
            </button>
          </div>
        </nav>

        {/* Content area */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
          <header style={{
            height: 48,
            flexShrink: 0,
            borderBottom: '1px solid var(--color-border)',
            background: 'var(--color-bg-primary)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'flex-end',
            padding: '0 16px',
            gap: 12,
          }}>
            <ThemeToggle />
          </header>
          <main style={{ flex: 1, padding: 24, overflowY: 'auto', background: 'var(--color-bg-primary)' }}>
            <Outlet />
          </main>
        </div>

        {import.meta.env.DEV && <RoleSwitcher />}

        <Modal open={settingsOpen} onClose={() => setSettingsOpen(false)} title="Settings">
          <SettingsPage onClose={() => setSettingsOpen(false)} />
        </Modal>
      </div>
    </TeamProvider>
  )
}
