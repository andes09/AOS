import { CSSProperties } from 'react'
import { UserButton } from '@clerk/clerk-react'
import { PanelLeft, Settings } from 'lucide-react'
import { SegmentedControl } from '../ui/SegmentedControl'
import { IconButton } from '../ui/IconButton'
import { ThemeToggle } from '../ui/ThemeToggle'
import { TeamSwitcher } from '../TeamSwitcher'
import { VIEW_OPTIONS, type PlannerView } from '../planner/plannerViews'

interface TopBarProps {
  view: PlannerView
  onViewChange: (view: PlannerView) => void
  onOpenSettings: () => void
  lanesHidden: boolean
  onToggleLanes: () => void
}

/**
 * The app's only chrome now that the left sidebar is gone: wordmark, the
 * planner's view switcher promoted to primary navigation, and the utility
 * cluster. Everything below it is the planner.
 */
export function TopBar({ view, onViewChange, onOpenSettings, lanesHidden, onToggleLanes }: TopBarProps) {
  return (
    <header style={barStyle}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', minWidth: 0 }}>
        <IconButton
          label={lanesHidden ? 'Show people panel' : 'Hide people panel'}
          aria-pressed={!lanesHidden}
          onClick={onToggleLanes}
        >
          <PanelLeft size={17} />
        </IconButton>
        <span style={wordmarkStyle}>Omada</span>
        <TeamSwitcher />
      </div>

      <SegmentedControl
        ariaLabel="Calendar view"
        options={VIEW_OPTIONS}
        value={view}
        onChange={onViewChange}
      />

      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', justifyContent: 'flex-end' }}>
        <ThemeToggle />
        <IconButton label="Settings" onClick={onOpenSettings}>
          <Settings size={16} />
        </IconButton>
        <UserButton />
      </div>
    </header>
  )
}

const barStyle: CSSProperties = {
  height: 52,
  flexShrink: 0,
  display: 'grid',
  gridTemplateColumns: '1fr auto 1fr',
  alignItems: 'center',
  gap: 'var(--space-4)',
  padding: '0 var(--space-4)',
  borderBottom: '1px solid var(--color-border)',
  background: 'var(--color-bg-secondary)',
}

const wordmarkStyle: CSSProperties = {
  fontFamily: '"DM Sans", var(--font-sans)',
  fontWeight: 600,
  fontSize: 18,
  letterSpacing: '-0.02em',
  color: 'var(--color-text-primary)',
  whiteSpace: 'nowrap',
}
