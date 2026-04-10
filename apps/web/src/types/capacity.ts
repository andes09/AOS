export interface DeveloperCapacityItem {
  developerId: string
  displayName: string
  baseVelocity: number
  effectiveCapacityPts: number
  meetingOverheadPct: number
  ptoDays: number
  capacityPct: number
  isHighMeetingLoad: boolean
  warningMessage: string | null
}

export interface TeamCapacityResponse {
  teamId: string
  meetingOverheadPct: number
  developers: DeveloperCapacityItem[]
}
