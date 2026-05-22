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

export const STRENGTHS = [
  'API Design','System Architecture','Frontend','Backend','Mobile','Cloud Infra','DevOps',
  'Data Modeling','Machine Learning','UI / UX','Accessibility','Performance','Security',
  'Testing / QA','Mentorship','Code Review','Documentation','Incident Response',
  'Database Tuning','Distributed Systems','Observability','Refactoring','Estimation',
]

export const SENIORITY = ['Intern','Junior','Mid','Senior','Staff']
export const METHODS   = ['Scrum','Kanban','SAFe','Custom']
export const CADENCES  = ['1-week','2-week','3-week','4-week']
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
export const STEP_LABELS = ['Team Basics', 'Add Members', 'Review']
export const WHY = [
  'Sprint capacity is team-scoped. Your team name and structure help Omada isolate velocity data from other teams in your org.',
  "Per-developer profiles power Sprint Brain's assignment intelligence. Roles and strengths directly influence planning recommendations.",
  'Confirming your roster before connecting Jira ensures profile names match ticket assignees — essential for accurate velocity tracking.',
]
export const SIZE_OPTIONS = ['2–5', '6–10', '11–20', '21–50', '50+']
