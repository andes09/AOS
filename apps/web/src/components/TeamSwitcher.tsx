import { useTeam } from '../contexts/TeamContext'

export function TeamSwitcher() {
  const { teams, activeTeamId, setActiveTeam } = useTeam()

  if (teams.length <= 1) return null

  return (
    <div style={{ marginBottom: '1rem' }}>
      <select
        value={activeTeamId}
        onChange={e => setActiveTeam(e.target.value)}
        style={{
          width: '100%',
          background: '#1e2030',
          border: '1px solid #2d2f45',
          borderRadius: 6,
          color: '#e2e8f0',
          fontSize: 13,
          padding: '0.375rem 0.625rem',
          cursor: 'pointer',
          outline: 'none',
        }}
      >
        {teams.map(t => (
          <option key={t.teamId} value={t.teamId}>
            {t.teamName}{t.isPrimary ? ' (primary)' : ''}
          </option>
        ))}
      </select>
    </div>
  )
}
