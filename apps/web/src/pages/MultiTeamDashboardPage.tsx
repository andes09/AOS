import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApi, ApiError } from '../lib/api'
import type { TeamDashboardItem } from '../types/multiTeam'

const RAG_ORDER: Record<string, number> = { red: 0, amber: 1, green: 2 }

const RAG_COLORS: Record<string, { bg: string; border: string; badge: string; text: string }> = {
  red:   { bg: '#1c0a09', border: '#ef4444', badge: '#dc2626', text: '#fca5a5' },
  amber: { bg: '#1c1100', border: '#d97706', badge: '#b45309', text: '#fde68a' },
  green: { bg: '#052e16', border: '#16a34a', badge: '#15803d', text: '#86efac' },
}

export function MultiTeamDashboardPage() {
  const { get } = useApi()
  const navigate = useNavigate()
  const [teams, setTeams] = useState<TeamDashboardItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    get<{ teams: TeamDashboardItem[] }>('/api/teams/multi-dashboard')
      .then(data =>
        setTeams([...data.teams].sort((a, b) => (RAG_ORDER[a.ragStatus] ?? 3) - (RAG_ORDER[b.ragStatus] ?? 3)))
      )
      .catch(err => {
        if (err instanceof ApiError && err.status === 403) {
          setError('Multi-team view requires lead role or higher')
        } else {
          setError('Failed to load team dashboard')
        }
      })
      .finally(() => setLoading(false))
  }, [])

  if (loading) {
    return <div style={{ color: '#64748b', padding: '2rem' }}>Loading teams...</div>
  }

  if (error) {
    return (
      <div style={{ color: '#ef4444', background: '#1c0a09', border: '1px solid #ef4444', borderRadius: 8, padding: '1rem 1.5rem', margin: '2rem 0' }}>
        {error}
      </div>
    )
  }

  if (teams.length === 0) {
    return (
      <div style={{ color: '#64748b', textAlign: 'center', padding: '3rem' }}>
        No additional teams found
      </div>
    )
  }

  return (
    <div style={{ padding: '1.5rem', fontFamily: 'system-ui, sans-serif' }}>
      <h1 style={{ color: '#e2e8f0', fontSize: '1.5rem', fontWeight: 700, marginBottom: '1.5rem' }}>
        Multi-Team Dashboard
      </h1>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 16 }}>
        {teams.map(team => {
          const colors = RAG_COLORS[team.ragStatus] || RAG_COLORS.green
          return (
            <div
              key={team.teamId}
              onClick={() => navigate(`/app/velocity-mirror?teamId=${team.teamId}`)}
              style={{
                background: colors.bg,
                border: `1px solid ${colors.border}`,
                borderRadius: 10,
                padding: '1.25rem',
                cursor: 'pointer',
                transition: 'transform 0.1s',
              }}
              onMouseEnter={e => (e.currentTarget.style.transform = 'translateY(-2px)')}
              onMouseLeave={e => (e.currentTarget.style.transform = 'translateY(0)')}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 }}>
                <span style={{ color: '#e2e8f0', fontSize: '1rem', fontWeight: 700 }}>{team.teamName}</span>
                <span style={{
                  background: colors.badge,
                  color: '#fff',
                  fontSize: 11,
                  fontWeight: 700,
                  padding: '2px 10px',
                  borderRadius: 999,
                  textTransform: 'uppercase',
                }}>
                  {team.ragStatus}
                </span>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: '#64748b', fontSize: 13 }}>Health score</span>
                  <span style={{ color: colors.text, fontSize: 13, fontWeight: 700 }}>{team.healthScore}/100</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: '#64748b', fontSize: 13 }}>Active sprint</span>
                  <span style={{ color: '#94a3b8', fontSize: 13 }}>{team.activeSprintName || '—'}</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: '#64748b', fontSize: 13 }}>Completion</span>
                  <span style={{ color: '#94a3b8', fontSize: 13 }}>{Math.round(team.completionRate * 100)}%</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: '#64748b', fontSize: 13 }}>Active deps</span>
                  <span style={{ color: team.activeDepsCount > 0 ? '#fbbf24' : '#94a3b8', fontSize: 13 }}>{team.activeDepsCount}</span>
                </div>
                {team.lastRetroDate && (
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span style={{ color: '#64748b', fontSize: 13 }}>Last retro</span>
                    <span style={{ color: '#94a3b8', fontSize: 13 }}>{team.lastRetroDate}</span>
                  </div>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
