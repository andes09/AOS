export interface MemberDraft {
  name: string
  email: string
  role: string           // role id or 'custom'
  customRole: string
  strengths: string[]
  seniority: string
  capacity: number
  meetings: string
}

export interface TeamDraft {
  name: string
  size: string
  cadence: string
  methodology: string
  techStack: string[]
}

export const BLANK_MEMBER: MemberDraft = {
  name: '', email: '', role: '', customRole: '',
  strengths: [], seniority: 'Mid', capacity: 32, meetings: '3to6',
}
