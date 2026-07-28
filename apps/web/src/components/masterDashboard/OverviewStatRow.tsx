// Big-number stat tiles — Total Orgs, Total Users, AI Cost, Commits.

import { Card } from '../ui/Card'
import type { OverviewResponse } from '../../types/masterDashboard'

interface Props {
  data: OverviewResponse | undefined
  isLoading: boolean
}

function formatUsd(n: number): string {
  return `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function Tile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <Card style={{ flex: '1 1 180px', padding: '14px 16px' }}>
      <div
        style={{
          fontSize: 'var(--text-xs)',
          color: 'var(--color-text-secondary)',
          textTransform: 'uppercase',
          letterSpacing: '0.04em',
          fontWeight: 'var(--font-weight-semibold)' as const,
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontSize: 'var(--text-2xl)',
          fontWeight: 'var(--font-weight-semibold)' as const,
          color: 'var(--color-text-primary)',
          marginTop: 4,
          lineHeight: 1.15,
        }}
      >
        {value}
      </div>
      {sub && (
        <div style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-muted)', marginTop: 2 }}>{sub}</div>
      )}
    </Card>
  )
}

export function OverviewStatRow({ data, isLoading }: Props) {
  if (isLoading || !data) {
    return (
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        {Array.from({ length: 4 }).map((_, i) => (
          <Card key={i} style={{ flex: '1 1 180px', height: 72 }}>
            <></>
          </Card>
        ))}
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
      <Tile label="Total Orgs" value={data.totalOrgs.toLocaleString()} />
      <Tile label="Total Users" value={data.totalUsers.toLocaleString()} />
      <Tile
        label="AI Cost"
        value={formatUsd(data.cost.allTimeUsd)}
        sub={`${formatUsd(data.cost.last30dUsd)} last 30d`}
      />
      <Tile
        label="Commits"
        value={data.commits.allTime.toLocaleString()}
        sub={`${data.commits.last30d.toLocaleString()} last 30d`}
      />
    </div>
  )
}
