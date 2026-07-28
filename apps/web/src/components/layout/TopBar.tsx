import { CSSProperties } from 'react'
import { Link } from 'react-router-dom'
import { UserButton } from '@clerk/clerk-react'
import { ArrowLeft, PanelLeft, Settings } from 'lucide-react'
import { SegmentedControl } from '../ui/SegmentedControl'
import { IconButton } from '../ui/IconButton'
import { ThemeToggle } from '../ui/ThemeToggle'
import { TeamSwitcher } from '../TeamSwitcher'
import { VIEW_OPTIONS, type PlannerView } from '../planner/plannerViews'

interface PlannerTopBarControls {
  view: PlannerView
  onViewChange: (view: PlannerView) => void
  lanesHidden: boolean
  onToggleLanes: () => void
  /** Current project's name, for the "back to hub" breadcrumb. */
  projectName: string | null
}

interface TopBarProps {
  onOpenSettings: () => void
  /** Present only inside a project route (/app/projects/:projectId) — the
   * planner-specific view switcher and lanes toggle don't make sense on the
   * Project Hub itself. */
  planner?: PlannerTopBarControls | null
}

/**
 * The app's only chrome now that the left sidebar is gone: wordmark, an
 * (optional, project-scoped) view switcher, and the utility cluster.
 */
export function TopBar({ onOpenSettings, planner }: TopBarProps) {
  return (
    <header style={barStyle}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', minWidth: 0 }}>
        {planner ? (
          <>
            <IconButton
              label={planner.lanesHidden ? 'Show people panel' : 'Hide people panel'}
              aria-pressed={!planner.lanesHidden}
              onClick={planner.onToggleLanes}
            >
              <PanelLeft size={17} />
            </IconButton>
            <Link
              to="/app"
              style={{ display: 'flex', alignItems: 'center', gap: 6, color: 'var(--color-text-secondary)', fontSize: 'var(--text-sm)', textDecoration: 'none' }}
            >
              <ArrowLeft size={14} /> Projects
            </Link>
            {planner.projectName && (
              <span style={{ ...wordmarkStyle, fontSize: 15 }}>{planner.projectName}</span>
            )}
          </>
        ) : (
          <span style={wordmarkStyle}>Omada</span>
        )}
        <TeamSwitcher />
      </div>

      {planner && (
        <SegmentedControl
          ariaLabel="Calendar view"
          options={VIEW_OPTIONS}
          value={planner.view}
          onChange={planner.onViewChange}
        />
      )}

      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', justifyContent: 'flex-end', gridColumn: planner ? undefined : '3' }}>
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
