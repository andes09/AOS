import { useQuery } from '@tanstack/react-query'
import { useAuth } from '@clerk/clerk-react'
import { useApi, ApiError } from '../lib/api'
import { SectorHealthBanner } from '../components/exec/SectorHealthBanner'
import { TeamHealthCard } from '../components/exec/TeamHealthCard'
import { SectorOverviewResponse } from '../types/exec'

function LoadingSkeleton() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {/* Banner skeleton */}
      <div style={{
        background: '#1e2130',
        borderRadius: 12,
        height: 110,
        marginBottom: 8,
        opacity: 0.5,
      }} />
      {/* Card grid skeleton */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 12 }}>
        {[1, 2, 3].map(i => (
          <div key={i} style={{
            background: '#1e2130',
            borderRadius: 10,
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
    <div style={{
      background: '#0f1117',
      minHeight: '100%',
      padding: '1.5rem',
      fontFamily: 'system-ui, sans-serif',
    }}>
      <div style={{ marginBottom: 20 }}>
        <h1 style={{ color: '#e2e8f0', fontSize: 22, fontWeight: 800, margin: 0, letterSpacing: '-0.01em' }}>
          Exec Dashboard
        </h1>
        <div style={{ color: '#64748b', fontSize: 13, marginTop: 4 }}>
          Organization-wide health overview
        </div>
      </div>

      {isLoading && <LoadingSkeleton />}

      {is403 && (
        <div style={{
          background: '#1e2130',
          border: '1px solid #ef444433',
          borderRadius: 10,
          padding: '2rem',
          textAlign: 'center',
          color: '#ef4444',
          fontSize: 15,
        }}>
          Access denied. Exec role required.
        </div>
      )}

      {isError && !is403 && (
        <div style={{ color: '#ef4444', fontSize: 14 }}>
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
            <div style={{ color: '#64748b', fontSize: 14, textAlign: 'center', marginTop: 32 }}>
              No teams found in this organization.
            </div>
          )}
        </>
      )}
    </div>
  )
}
