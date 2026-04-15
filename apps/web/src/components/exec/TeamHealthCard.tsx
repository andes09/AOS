import { useNavigate } from 'react-router-dom'
import { Card, CardBody } from '../ui/Card'
import { Badge } from '../ui/Badge'
import type { BadgeVariant } from '../ui/Badge'
import { TeamSummary, RAGStatus, VelocityTrend } from '../../types/exec'

interface Props {
  team: TeamSummary
}

const RAG_BADGE_VARIANT: Record<RAGStatus, BadgeVariant> = {
  green: 'success',
  amber: 'warning',
  red:   'danger',
}

const RAG_SCORE_COLOR: Record<RAGStatus, string> = {
  green: 'var(--color-success)',
  amber: 'var(--color-warning)',
  red:   'var(--color-danger)',
}

const TREND_ARROW: Record<VelocityTrend, string> = {
  accelerating: '↑',
  stable:       '→',
  declining:    '↓',
}

const TREND_COLOR: Record<VelocityTrend, string> = {
  accelerating: 'var(--color-success)',
  stable:       'var(--color-text-secondary)',
  declining:    'var(--color-danger)',
}

export function TeamHealthCard({ team }: Props) {
  const navigate = useNavigate()
  const ragColor = RAG_SCORE_COLOR[team.status]
  const trendArrow = TREND_ARROW[team.velocityTrend]
  const trendColor = TREND_COLOR[team.velocityTrend]
  const completionPct = Math.round(team.sprintCompletionRate * 100)

  return (
    <Card
      onClick={() => navigate(`/app/velocity-mirror?teamId=${team.teamId}`)}
      style={{ cursor: 'pointer', transition: 'box-shadow 0.15s' }}
      onMouseEnter={e => (e.currentTarget.style.boxShadow = 'var(--shadow-md)')}
      onMouseLeave={e => (e.currentTarget.style.boxShadow = 'var(--shadow-sm)')}
    >
      <CardBody style={{ padding: '16px' }}>
        {/* Header: RAG badge + team name */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginBottom: 12 }}>
          <div style={{
            color: 'var(--color-text-primary)',
            fontFamily: 'var(--font-sans)',
            fontWeight: 700,
            fontSize: 'var(--text-base)',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}>
            {team.name}
          </div>
          <Badge variant={RAG_BADGE_VARIANT[team.status]}>{team.status.toUpperCase()}</Badge>
        </div>

        {/* Health score + trend arrow */}
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 12 }}>
          <div style={{ fontSize: 'var(--text-2xl)', fontWeight: 800, color: ragColor, lineHeight: 1, fontFamily: 'var(--font-sans)' }}>
            {team.healthScore}
          </div>
          <div style={{ fontSize: 22, color: trendColor, fontWeight: 700 }}>
            {trendArrow}
          </div>
        </div>

        {/* Completion rate progress bar */}
        <div>
          <div style={{ color: 'var(--color-text-secondary)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-xs)', marginBottom: 4 }}>
            Sprint completion · {completionPct}%
          </div>
          <div style={{ background: 'var(--color-bg-secondary)', borderRadius: 4, height: 6, overflow: 'hidden' }}>
            <div style={{
              width: `${completionPct}%`,
              height: '100%',
              background: ragColor,
              borderRadius: 4,
              transition: 'width 0.3s',
            }} />
          </div>
        </div>

        {team.lastSprintName && (
          <div style={{ color: 'var(--color-text-muted)', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-xs)', marginTop: 10 }}>
            Last: {team.lastSprintName}
          </div>
        )}
      </CardBody>
    </Card>
  )
}
