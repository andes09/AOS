import { useQueryClient } from '@tanstack/react-query'
import { useApi } from '../lib/api'
import { useAppRole } from '../hooks/useAppRole'

const ROLES = ['developer', 'lead', 'exec', 'admin'] as const

export function RoleSwitcher() {
  const { patch } = useApi()
  const { appRole } = useAppRole()
  const queryClient = useQueryClient()

  async function handleChange(e: React.ChangeEvent<HTMLSelectElement>) {
    const newRole = e.target.value
    await patch('/api/users/me/role', { app_role: newRole })
    await queryClient.invalidateQueries({ queryKey: ['app-role'] })
    window.location.reload()
  }

  return (
    <div style={{
      position: 'fixed',
      bottom: 16,
      right: 16,
      zIndex: 9999,
      display: 'flex',
      alignItems: 'center',
      gap: 6,
      background: '#1e2030',
      border: '1px solid #f59e0b',
      borderRadius: 8,
      padding: '6px 10px',
      fontSize: 12,
      boxShadow: '0 2px 8px rgba(0,0,0,0.4)',
    }}>
      <span style={{ color: '#f59e0b', fontWeight: 700, letterSpacing: '0.05em' }}>
        DEV
      </span>
      <select
        value={appRole}
        onChange={handleChange}
        style={{
          background: '#0f1117',
          color: '#e2e8f0',
          border: '1px solid #374151',
          borderRadius: 4,
          padding: '2px 6px',
          fontSize: 12,
          cursor: 'pointer',
          outline: 'none',
        }}
      >
        {ROLES.map(r => (
          <option key={r} value={r}>{r}</option>
        ))}
      </select>
    </div>
  )
}
