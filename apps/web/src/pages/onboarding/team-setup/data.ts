export const ROLES = [
  { id: 'frontend',    label: 'Frontend Dev',   group: 'Engineering' },
  { id: 'backend',     label: 'Backend Dev',    group: 'Engineering' },
  { id: 'fullstack',   label: 'Fullstack Dev',  group: 'Engineering' },
  { id: 'mobile',      label: 'Mobile Dev',     group: 'Engineering' },
  { id: 'devops',      label: 'DevOps / Infra', group: 'Engineering' },
  { id: 'qa',          label: 'QA Engineer',    group: 'Engineering' },
  { id: 'data',        label: 'Data Engineer',  group: 'Engineering' },
  { id: 'scrummaster', label: 'Scrum Master',   group: 'Agile' },
  { id: 'po',          label: 'Product Owner',  group: 'Agile' },
  { id: 'techlead',    label: 'Tech Lead',      group: 'Agile' },
  { id: 'stakeholder', label: 'Stakeholder',    group: 'Agile' },
]

export const QUICK_ROLES = ['frontend','backend','fullstack','mobile','devops','qa','data','techlead','po','scrummaster']

export const ROLE_HUES: Record<string, number> = {
  frontend: 235, backend: 275, fullstack: 200, mobile: 330, devops: 35,
  qa: 150, data: 95, scrummaster: 50, po: 18, techlead: 260, stakeholder: 310,
}

export function roleHue(role: string, customRole: string, name: string): number {
  if (!role || role === 'custom') {
    const s = customRole || name || 'x'
    return s.split('').reduce((a, c) => a + c.charCodeAt(0), 0) % 360
  }
  return ROLE_HUES[role] ?? 240
}

export function roleLabelOf(role: string, customRole: string): string {
  if (role === 'custom') return customRole || 'Custom role'
  return ROLES.find(r => r.id === role)?.label || ''
}

export const STRENGTHS = [
  'API Design','System Architecture','Frontend','Backend','Mobile','Cloud Infra','DevOps',
  'Data Modeling','Machine Learning','UI / UX','Accessibility','Performance','Security',
  'Testing / QA','Mentorship','Code Review','Documentation','Incident Response',
  'Database Tuning','Distributed Systems','Observability','Refactoring','Estimation',
]

export const SENIORITY  = ['Intern','Junior','Mid','Senior','Staff']
export const METHODS    = ['Scrum','Kanban','SAFe','Custom']
export const CADENCES   = ['1-week','2-week','3-week','4-week']
export const MEETING_HOURS = [
  { id: 'lt1',   label: '< 1 h',    desc: 'Heads-down' },
  { id: '1to3',  label: '1 – 3 h',  desc: 'Light' },
  { id: '3to6',  label: '3 – 6 h',  desc: 'Standard' },
  { id: '6to10', label: '6 – 10 h', desc: 'Heavy' },
  { id: 'gt10',  label: '10 h +',   desc: 'Manager-level' },
]

export const TECH = [
  'React','Vue','Angular','Svelte','Next.js','Remix','Node.js','TypeScript','JavaScript',
  'Python','Django','FastAPI','Java','Spring','Kotlin','Go','Ruby','Rails','.NET','C#',
  'PHP','Laravel','Rust','Elixir','Swift','iOS','Android','React Native','Flutter',
  'PostgreSQL','MySQL','MongoDB','Redis','Elasticsearch','GraphQL','REST','gRPC',
  'AWS','GCP','Azure','Vercel','Cloudflare','Docker','Kubernetes','Terraform','Pulumi',
]

export const STEP_LABELS = ['Connect Jira', 'Confirm team', 'Review']

export const WHY = [
  'Omada reads the board your team already works in, so you never re-enter what Jira already knows — your roster, cadence and board setup.',
  'Velocity profiles are per-person. Confirming who is actually on the sprint team keeps capacity and assignment intelligence accurate.',
  'A last check before we sync. Profiles map to Jira assignees, so imported sprint history lines up with the right people.',
]

// ── Mock Jira data ──────────────────────────────────────────────────────────────

export interface JiraBoard {
  id: string
  key: string
  name: string
  type: 'Scrum' | 'Kanban'
  cadence: string
  methodology: string
  active: string
  recommended?: boolean
}

export const JIRA_BOARDS: JiraBoard[] = [
  { id: 'plat', key: 'PLAT', name: 'Platform Sprint Board', type: 'Scrum',  cadence: '2-week',     methodology: 'Scrum',  active: 'Active today',      recommended: true },
  { id: 'mob',  key: 'MOB',  name: 'Mobile Apps Board',     type: 'Scrum',  cadence: '2-week',     methodology: 'Scrum',  active: 'Active today' },
  { id: 'grow', key: 'GROW', name: 'Growth Board',          type: 'Kanban', cadence: 'Continuous', methodology: 'Kanban', active: 'Active yesterday' },
  { id: 'data', key: 'DATA', name: 'Data Platform Board',   type: 'Scrum',  cadence: '3-week',     methodology: 'Scrum',  active: 'Active 2 days ago' },
]

// [name, jira handle, recent issues] per board
export const JIRA_PEOPLE: Record<string, [string, string, number][]> = {
  plat: [
    ['Maya Rodriguez', 'maya.r', 46], ['James Chen', 'jchen', 39], ['Priya Nair', 'priya.nair', 35],
    ['Daniel Okoro', 'dokoro', 31], ['Sofia Almeida', 'salmeida', 33], ['Tom Becker', 'tbecker', 24],
    ['Aisha Khan', 'akhan', 28], ['Liam Walsh', 'lwalsh', 30],
  ],
  mob: [
    ['Noah Kim', 'noah.kim', 41], ['Emma Dubois', 'edubois', 37], ['Raj Patel', 'rpatel', 33],
    ['Chloe Martin', 'cmartin', 29], ['Yuki Tanaka', 'ytanaka', 26], ['Omar Hassan', 'ohassan', 31],
  ],
  grow: [
    ['Hannah Lee', 'hlee', 22], ['Marco Rossi', 'mrossi', 19], ['Zara Ahmed', 'zahmed', 24],
    ['Ben Carter', 'bcarter', 18], ['Ines Costa', 'icosta', 20],
  ],
  data: [
    ['Victor Nguyen', 'vnguyen', 44], ['Grace Park', 'gpark', 36], ['Felix Wagner', 'fwagner', 30],
    ['Lena Schmidt', 'lschmidt', 28], ['Arjun Mehta', 'amehta', 33], ['Nora Fox', 'nfox', 25], ['Paul Adams', 'padams', 22],
  ],
}

const JIRA_BOT: [string, string, number] = ['Release Bot', 'ci-release-bot', 214]

export function boardById(id: string): JiraBoard {
  return JIRA_BOARDS.find(b => b.id === id) || JIRA_BOARDS[0]
}

import type { MemberDraft } from './types'

export function importRoster(boardId: string): MemberDraft[] {
  const people = JIRA_PEOPLE[boardId] || JIRA_PEOPLE.plat
  const list: MemberDraft[] = people.map(([name, handle, issues]) => ({
    name, email: '', role: '', customRole: '', strengths: [],
    seniority: 'Mid', capacity: 40, meetings: '3to6',
    handle, issues, included: true, source: 'jira' as const,
  }))
  list.push({
    name: JIRA_BOT[0], email: '', role: '', customRole: '', strengths: [],
    seniority: 'Mid', capacity: 0, meetings: '3to6',
    handle: JIRA_BOT[1], issues: JIRA_BOT[2], included: false, bot: true, source: 'jira' as const,
  })
  return list
}

export function deriveTeamName(board: JiraBoard): string {
  return board.name.replace(/\s*(Sprint\s*)?Board$/i, '').trim() || board.name
}

// kept for imports that haven't been updated
export const SIZE_OPTIONS = ['2–5', '6–10', '11–20', '21–50', '50+']
