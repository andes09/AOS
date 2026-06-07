export interface MemberDraft {
  name: string
  email: string
  role: string           // role id or 'custom'
  customRole: string
  strengths: string[]
  seniority: string
  capacity: number
  meetings: string
  // Jira-import fields
  handle?: string
  issues?: number
  included?: boolean
  bot?: boolean
  source?: 'jira' | 'manual'
}

export interface TeamDraft {
  name: string
  boardId: string
  boardName: string
  cadence: string
  methodology: string
  // kept for backward compat with API
  size: string
  techStack: string[]
}

export const BLANK_MEMBER: MemberDraft = {
  name: '', email: '', role: '', customRole: '',
  strengths: [], seniority: 'Mid', capacity: 40, meetings: '3to6',
}
