export interface OnboardingStatus {
  jiraConnected: boolean
  boardSelected: boolean
  importStatus: 'pending' | 'in_progress' | 'completed' | 'failed'
  importedSprints: number | null
  onboardingCompleted: boolean
}

export interface InvitationItem {
  id: string
  email: string
  role: string
  status: string
  inviteLink: string
  expiresAt: string
  createdAt: string
}
