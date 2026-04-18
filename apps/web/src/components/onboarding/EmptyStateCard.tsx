interface EmptyStateCardProps {
  icon: string
  title: string
  description: string
  sprintsNeeded?: number
  action?: { label: string; onClick: () => void }
}

export function EmptyStateCard({ icon, title, description, sprintsNeeded, action }: EmptyStateCardProps) {
  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      textAlign: 'center',
      padding: '3rem 2rem',
      background: '#1e2030',
      borderRadius: 12,
      border: '1px solid #2d2f45',
      gap: 12,
    }}>
      <div style={{ fontSize: 40, lineHeight: 1 }}>{icon}</div>
      <div style={{ color: '#e2e8f0', fontSize: '1.125rem', fontWeight: 700 }}>{title}</div>
      <div style={{ color: '#64748b', fontSize: 14, maxWidth: 360, lineHeight: 1.6 }}>{description}</div>
      {sprintsNeeded != null && (
        <div style={{
          fontSize: 12,
          color: '#6366f1',
          background: '#1e1b4b',
          border: '1px solid #3730a3',
          borderRadius: 6,
          padding: '4px 12px',
          fontWeight: 600,
        }}>
          Unlocks after {sprintsNeeded} more sprint{sprintsNeeded !== 1 ? 's' : ''}
        </div>
      )}
      {action && (
        <button
          onClick={action.onClick}
          style={{
            marginTop: 4,
            background: '#6366f1',
            color: '#fff',
            border: 'none',
            borderRadius: 8,
            padding: '0.625rem 1.5rem',
            fontSize: 14,
            fontWeight: 600,
            cursor: 'pointer',
          }}
        >
          {action.label}
        </button>
      )}
    </div>
  )
}
