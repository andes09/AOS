import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApi, ApiError } from '../lib/api'
import { Card, CardBody } from '../components/ui/Card'
import { Badge } from '../components/ui/Badge'
import { Alert } from '../components/ui/Alert'
import type { BadgeVariant } from '../components/ui/Badge'
import type { TeamDashboardItem } from '../types/multiTeam'

const RAG_ORDER: Record<string, number> = { red: 0, amber: 1, green: 2 }

const RAG_SCORE_COLOR: Record<string, string> = {
  red:   'var(--color-danger)',
  amber: 'var(--color-warning)',
  green: 'var(--color-success)',
}

const RAG_BADGE_VARIANT: Record<string, BadgeVariant> = {
  red:   'danger',
  amber: 'warning',
  green: 'success',
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
    return (
      <div style={{ color: 'var(--color-text-muted)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)', padding: '2rem' }}>
        Loading teams...
      </div>
    )
  }

  if (error) {
    return (
      <Alert variant="danger" style={{ margin: '2rem 0' }}>{error}</Alert>
    )
  }

  if (teams.length === 0) {
    return (
      <div style={{ color: 'var(--color-text-muted)', fontFamily: 'var(--font-sans)', textAlign: 'center', padding: '3rem', fontSize: 'var(--text-base)' }}>
        No additional teams found
      </div>
    )
  }

  return (
    <div style={{ fontFamily: 'var(--font-sans)', minHeight: '100%' }}>
      <h1 style={{ color: 'var(--color-text-primary)', fontSize: 'var(--text-xl)', fontWeight: 700, marginBottom: 20, margin: '0 0 20px' }}>
        Multi-Team Dashboard
      </h1>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 12 }}>
        {teams.map(team => {
          const scoreColor = RAG_SCORE_COLOR[team.ragStatus] || RAG_SCORE_COLOR.green
          const badgeVariant = RAG_BADGE_VARIANT[team.ragStatus] || 'success'
          const completionPct = Math.round(team.completionRate * 100)

          return (
            <Card
              key={team.teamId}
              onClick={() => navigate(`/app/velocity-mirror?teamId=${team.teamId}`)}
              style={{ cursor: 'pointer', transition: 'box-shadow 0.15s' }}
              onMouseEnter={e => (e.currentTarget.style.boxShadow = 'var(--shadow-md)')}
              onMouseLeave={e => (e.currentTarget.style.boxShadow = 'var(--shadow-sm)')}
            >
              <CardBody style={{ padding: 16 }}>
                {/* Header */}
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 }}>
                  <span style={{ color: 'var(--color-text-primary)', fontSize: 'var(--text-base)', fontWeight: 700 }}>
                    {team.teamName}
                  </span>
                  <Badge variant={badgeVariant}>{team.ragStatus.toUpperCase()}</Badge>
                </div>

                {/* Stats */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span style={{ color: 'var(--color-text-secondary)', fontSize: 'var(--text-sm)' }}>Health score</span>
                    <span style={{ color: scoreColor, fontSize: 'var(--text-sm)', fontWeight: 700 }}>{team.healthScore}/100</span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span style={{ color: 'var(--color-text-secondary)', fontSize: 'var(--text-sm)' }}>Active sprint</span>
                    <span style={{ color: 'var(--color-text-primary)', fontSize: 'var(--text-sm)' }}>{team.activeSprintName || '—'}</span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ color: 'var(--color-text-secondary)', fontSize: 'var(--text-sm)' }}>Completion</span>
                    <span style={{ color: 'var(--color-text-primary)', fontSize: 'var(--text-sm)' }}>{completionPct}%</span>
                  </div>
                  {/* Completion bar */}
                  <div style={{ background: 'var(--color-border)', borderRadius: 3, height: 5, overflow: 'hidden' }}>
                    <div style={{ width: `${completionPct}%`, height: '100%', background: scoreColor, borderRadius: 3, transition: 'width 0.3s' }} />
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span style={{ color: 'var(--color-text-secondary)', fontSize: 'var(--text-sm)' }}>Active deps</span>
                    <span style={{ color: team.activeDepsCount > 0 ? 'var(--color-warning)' : 'var(--color-text-secondary)', fontSize: 'var(--text-sm)', fontWeight: team.activeDepsCount > 0 ? 700 : 400 }}>
                      {team.activeDepsCount}
                    </span>
                  </div>
                  {team.lastRetroDate && (
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: 'var(--color-text-secondary)', fontSize: 'var(--text-sm)' }}>Last retro</span>
                      <span style={{ color: 'var(--color-text-secondary)', fontSize: 'var(--text-sm)' }}>{team.lastRetroDate}</span>
                    </div>
                  )}
                </div>
              </CardBody>
            </Card>
          )
        })}
      </div>
    </div>
  )
}
