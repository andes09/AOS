export interface TeamListItem {
  teamId: string
  teamName: string
  isPrimary: boolean
}

export interface TeamDashboardItem {
  teamId: string
  teamName: string
  healthScore: number
  activeSprintName: string | null
  completionRate: number
  activeDepsCount: number
  lastRetroDate: string | null
  ragStatus: 'green' | 'amber' | 'red'
}
