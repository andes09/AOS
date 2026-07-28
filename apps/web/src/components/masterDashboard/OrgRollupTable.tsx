// Per-org rollup table, reusing the shared <Table> component.

import { Table, type TableColumn } from '../ui/Table'
import { Badge } from '../ui/Badge'
import type { OrgRollupRow } from '../../types/masterDashboard'

interface Props {
  orgs: OrgRollupRow[] | undefined
  isLoading: boolean
}

function formatUsd(n: number): string {
  return `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}

const columns: TableColumn<OrgRollupRow>[] = [
  { key: 'name', header: 'Org', render: row => row.name, sortable: true },
  { key: 'createdAt', header: 'Created', render: row => formatDate(row.createdAt), sortable: true },
  { key: 'userCount', header: 'Users', render: row => row.userCount, sortable: true, align: 'right' },
  {
    key: 'costAllTimeUsd',
    header: 'Cost (all time)',
    render: row => formatUsd(row.costAllTimeUsd),
    sortable: true,
    align: 'right',
  },
  {
    key: 'cost30dUsd',
    header: 'Cost (30d)',
    render: row => formatUsd(row.cost30dUsd),
    sortable: true,
    align: 'right',
  },
  {
    key: 'commitsAllTime',
    header: 'Commits (all time)',
    render: row => row.commitsAllTime,
    sortable: true,
    align: 'right',
  },
  {
    key: 'commits30d',
    header: 'Commits (30d)',
    render: row => row.commits30d,
    sortable: true,
    align: 'right',
  },
  {
    key: 'onboardingCompleted',
    header: 'Onboarding',
    render: row => (
      <Badge variant={row.onboardingCompleted ? 'success' : 'default'}>
        {row.onboardingCompleted ? 'Complete' : 'In progress'}
      </Badge>
    ),
  },
]

export function OrgRollupTable({ orgs, isLoading }: Props) {
  return (
    <Table
      columns={columns}
      data={orgs ?? []}
      rowKey={row => row.id}
      emptyState={isLoading ? 'Loading…' : 'No organizations yet.'}
    />
  )
}
