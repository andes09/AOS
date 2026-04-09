import { useNavigate } from 'react-router-dom'
import { TeamSummary, RAGStatus, VelocityTrend } from '../../types/exec'

interface Props {
  team: TeamSummary
}

const RAG_COLOR: Record<RAGStatus, string> = {
  green: '#22c55e',
  amber: '#f59e0b',
  red: '#ef4444',
}

const TREND_ARROW: Record<VelocityTrend, string> = {
  accelerating: '↑',
  stable: '→',
  declining: '↓',
}

const TREND_COLOR: Record<VelocityTrend, string> = {
  accelerating: '#22c55e',
  stable: '#94a3b8',
  declining: '#ef4444',
}

export function TeamHealthCard({ team }: Props) {
  const navigate = useNavigate()
  const ragColor = RAG_COLOR[team.status]
  const trendArrow = TREND_ARROW[team.velocityTrend]
  const trendColor = TREND_COLOR[team.velocityTrend]
  const completionPct = Math.round(team.sprintCompletionRate * 100)

  return (
    <div
      onClick={() => navigate(`/app/velocity-mirror?teamId=${team.teamId}`)}
      style={{
        background: '#1e2130',
        border: '1px solid #334155',
        borderRadius: 10,
        padding: '1.25rem',
        cursor: 'pointer',
        transition: 'border-color 0.15s',
      }}
      onMouseEnter={e => (e.currentTarget.style.borderColor = '#475569')}
      onMouseLeave={e => (e.currentTarget.style.borderColor = '#334155')}
    >
      {/* Header: RAG dot + team name */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
        <div style={{
          width: 10,
          height: 10,
          borderRadius: '50%',
          background: ragColor,
          flexShrink: 0,
        }} />
        <div style={{ color: '#e2e8f0', fontWeight: 700, fontSize: 15, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {team.name}
        </div>
      </div>

      {/* Health score + trend arrow */}
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 12 }}>
        <div style={{ fontSize: 32, fontWeight: 800, color: ragColor, lineHeight: 1 }}>
          {team.healthScore}
        </div>
        <div style={{ fontSize: 22, color: trendColor, fontWeight: 700 }}>
          {trendArrow}
        </div>
      </div>

      {/* Completion rate progress bar */}
      <div>
        <div style={{ color: '#94a3b8', fontSize: 11, marginBottom: 4 }}>
          Sprint completion · {completionPct}%
        </div>
        <div style={{ background: '#0f1117', borderRadius: 4, height: 6, overflow: 'hidden' }}>
          <div style={{
            width: `${completionPct}%`,
            height: '100%',
            background: ragColor,
            borderRadius: 4,
            transition: 'width 0.3s',
          }} />
        </div>
      </div>

      {/* Last sprint name */}
      {team.lastSprintName && (
        <div style={{ color: '#64748b', fontSize: 11, marginTop: 10 }}>
          Last: {team.lastSprintName}
        </div>
      )}
    </div>
  )
}
