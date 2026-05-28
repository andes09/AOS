import { useQuery } from '@tanstack/react-query'
import { useAuth } from '@clerk/clerk-react'
import { useApi, ApiError } from '../lib/api'
import { SectorHealthBanner } from '../components/exec/SectorHealthBanner'
import { TeamHealthCard } from '../components/exec/TeamHealthCard'
import { PlanQualityChart } from '../components/exec/PlanQualityChart'
import { RevisionAcceptanceChart } from '../components/exec/RevisionAcceptanceChart'
import { Alert } from '../components/ui/Alert'
import { SectorOverviewResponse } from '../types/exec'

function LoadingSkeleton() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{
        background: 'var(--color-bg-elevated)',
        border: '1px solid var(--color-border)',
        borderRadius: 'var(--radius-lg)',
        height: 80,
        marginBottom: 8,
        opacity: 0.5,
      }} />
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 12 }}>
        {[1, 2, 3].map(i => (
          <div key={i} style={{
            background: 'var(--color-bg-elevated)',
            border: '1px solid var(--color-border)',
            borderRadius: 'var(--radius-lg)',
            height: 140,
            opacity: 0.4,
          }} />
        ))}
      </div>
    </div>
  )
}

export function ExecDashboardPage() {
  const { isLoaded, isSignedIn } = useAuth()
  const { get } = useApi()

  const { data, isLoading, isError, error } = useQuery<SectorOverviewResponse, ApiError>({
    queryKey: ['exec-sector-overview'],
    queryFn: () => get<SectorOverviewResponse>('/api/exec/sector-overview'),
    enabled: isLoaded && isSignedIn,
  })

  const is403 = isError && error instanceof ApiError && error.status === 403

  return (
    <div style={{ fontFamily: 'var(--font-sans)', minHeight: '100%' }}>
      <div style={{ marginBottom: 20 }}>
        <h1 style={{ color: 'var(--color-text-primary)', fontSize: 'var(--text-xl)', fontWeight: 700, margin: 0 }}>
          Exec Dashboard
        </h1>
        <div style={{ color: 'var(--color-text-muted)', fontSize: 'var(--text-sm)', marginTop: 4 }}>
          Organization-wide health overview
        </div>
      </div>

      {isLoading && <LoadingSkeleton />}

      {is403 && (
        <Alert variant="danger">Access denied. Exec role required.</Alert>
      )}

      {isError && !is403 && (
        <div style={{ color: 'var(--color-danger)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-base)' }}>
          Failed to load sector overview.
        </div>
      )}

      {data && (
        <>
          <SectorHealthBanner
            sectorHealthScore={data.sectorHealthScore}
            teamCount={data.teamCount}
          />
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
            gap: 12,
          }}>
            {data.teams.map(team => (
              <TeamHealthCard key={team.teamId} team={team} />
            ))}
          </div>
          {data.teams.length === 0 && (
            <div style={{ color: 'var(--color-text-muted)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-base)', textAlign: 'center', marginTop: 32 }}>
              No teams found in this organization.
            </div>
          )}
          {data.teams.length > 0 && (
            <PlanQualityChart teams={data.teams} />
          )}
          {data.teams.length > 0 && (
            <RevisionAcceptanceChart teams={data.teams} />
          )}
        </>
      )}
    </div>
  )
}
