import { createContext, useContext, useEffect, useState } from 'react'
import { useApi } from '../lib/api'
import type { TeamListItem } from '../types/multiTeam'

interface TeamContextValue {
  activeTeamId: string
  activeTeamName: string
  teams: TeamListItem[]
  setActiveTeam: (teamId: string) => void
}

const TeamContext = createContext<TeamContextValue>({
  activeTeamId: 'default',
  activeTeamName: '',
  teams: [],
  setActiveTeam: () => {},
})

export function useTeam() {
  return useContext(TeamContext)
}

const STORAGE_KEY = 'aos_active_team_id'

export function TeamProvider({ children }: { children: React.ReactNode }) {
  const { get } = useApi()
  const [teams, setTeams] = useState<TeamListItem[]>([])
  const [activeTeamId, setActiveTeamId] = useState<string>(() => {
    return localStorage.getItem(STORAGE_KEY) || 'default'
  })

  useEffect(() => {
    get<{ teams: TeamListItem[] }>('/api/teams')
      .then(data => setTeams(data.teams))
      .catch(() => {})
  }, [])

  function setActiveTeam(teamId: string) {
    localStorage.setItem(STORAGE_KEY, teamId)
    setActiveTeamId(teamId)
    window.location.reload()
  }

  const activeTeam = teams.find(t => t.teamId === activeTeamId)
  const activeTeamName = activeTeam?.teamName ?? ''

  return (
    <TeamContext.Provider value={{ activeTeamId, activeTeamName, teams, setActiveTeam }}>
      {children}
    </TeamContext.Provider>
  )
}
