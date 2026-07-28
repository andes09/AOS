// The platform admin dashboard — a cross-org, founder-only view of business
// health (total users, AI cost, GitHub commit activity, per-org rollup).
// Standalone route (/master, see App.tsx), not nested under /app: it has no
// org context, so it renders its own minimal header instead of
// DashboardLayout's org-scoped shell.

import { useState } from 'react'

import { Alert } from '../components/ui/Alert'
import { SegmentedControl } from '../components/ui/SegmentedControl'
import { ThemeToggle } from '../components/ui/ThemeToggle'
import { CommitsChart } from '../components/masterDashboard/CommitsChart'
import { CostChart } from '../components/masterDashboard/CostChart'
import { OrgRollupTable } from '../components/masterDashboard/OrgRollupTable'
import { OverviewStatRow } from '../components/masterDashboard/OverviewStatRow'
import { SignupsChart } from '../components/masterDashboard/SignupsChart'
import {
  useCommitsSeries,
  useCostSeries,
  useOrgRollup,
  useOverview,
  useSignupsSeries,
} from '../hooks/useMasterDashboard'
import { ApiError } from '../lib/api'
import type { DashboardRange } from '../types/masterDashboard'

const RANGE_OPTIONS = [
  { value: '7d' as const, label: '7 days', content: '7d' },
  { value: '30d' as const, label: '30 days', content: '30d' },
  { value: '90d' as const, label: '90 days', content: '90d' },
  { value: 'all' as const, label: 'All time', content: 'All' },
]

export function MasterDashboardPage() {
  const [range, setRange] = useState<DashboardRange>('30d')

  const overview = useOverview()
  const signups = useSignupsSeries(range)
  const cost = useCostSeries(range)
  const commits = useCommitsSeries(range)
  const orgs = useOrgRollup()

  // The backend's require_platform_admin is the real access boundary — a
  // non-allowlisted user gets a 403 here. This is just UX around that.
  const firstError = [overview.error, signups.error, cost.error, commits.error, orgs.error].find(Boolean)
  const isForbidden = firstError instanceof ApiError && firstError.status === 403

  return (
    <div style={{ minHeight: '100vh', background: 'var(--color-bg-primary)' }}>
      <header
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '12px 20px',
          borderBottom: '1px solid var(--color-border)',
          position: 'sticky',
          top: 0,
          background: 'var(--color-bg-primary)',
          zIndex: 1,
        }}
      >
        <h1 style={{ fontSize: 'var(--text-lg)', fontWeight: 700, margin: 0, color: 'var(--color-text-primary)' }}>
          Master Dashboard
        </h1>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          {!isForbidden && (
            <SegmentedControl
              ariaLabel="Date range"
              options={RANGE_OPTIONS}
              value={range}
              onChange={setRange}
              size="sm"
            />
          )}
          <ThemeToggle />
        </div>
      </header>

      <div style={{ maxWidth: 1200, margin: '0 auto', padding: '20px', display: 'flex', flexDirection: 'column', gap: 'var(--space-6)' }}>
        {isForbidden ? (
          <Alert variant="danger" title="Access denied">
            You don't have access to the platform admin dashboard.
          </Alert>
        ) : firstError ? (
          <Alert variant="danger">
            {firstError instanceof ApiError ? firstError.message : 'Could not load the dashboard.'}
          </Alert>
        ) : (
          <>
            <OverviewStatRow data={overview.data} isLoading={overview.isLoading} />

            <div style={{ display: 'flex', gap: 'var(--space-4)', flexWrap: 'wrap' }}>
              <SignupsChart series={signups.data?.series} isLoading={signups.isLoading} />
              <CostChart series={cost.data?.series} isLoading={cost.isLoading} />
              <CommitsChart series={commits.data?.series} isLoading={commits.isLoading} />
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
              <h2 style={{ fontSize: 'var(--text-sm)', fontWeight: 'var(--font-weight-semibold)' as const, margin: 0, color: 'var(--color-text-primary)' }}>
                Organizations
              </h2>
              <OrgRollupTable orgs={orgs.data?.orgs} isLoading={orgs.isLoading} />
            </div>
          </>
        )}
      </div>
    </div>
  )
}
