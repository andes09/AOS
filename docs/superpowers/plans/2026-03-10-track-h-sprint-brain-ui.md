# Track H — Sprint Brain UI Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Sprint Brain onboarding wizard and sprint planner page — dark/indigo, wired to the existing FastAPI backend.

**Architecture:** Full-screen 3-step onboarding wizard with localStorage step persistence. Sprint planner page uses Layout C (velocity row + split bottom). All API calls via existing `useApi()` hook from `src/lib/api.ts`. Inline styles throughout (no CSS framework). `@dnd-kit` for what-if drag-and-drop in TicketList.

**Tech Stack:** React 18, TypeScript strict, React Router v6, Clerk auth, @tanstack/react-query, @dnd-kit/core + @dnd-kit/sortable + @dnd-kit/utilities, SVG for gauge animation.

**Colour palette (dark/indigo):**
- `#0f1117` page background
- `#1e2030` card surface
- `#2d2f45` track/border
- `#6366f1` indigo primary
- `#a5b4fc` indigo light (labels)
- `#e2e8f0` text primary · `#94a3b8` secondary · `#64748b` tertiary
- `#4ade80` green · `#fbbf24` amber · `#ef4444` red

---

## Chunk 1: Foundation

### Task 1: Install @dnd-kit packages

**Files:**
- Modify: `apps/web/package.json`

- [ ] **Step 1: Install dependencies**

```bash
cd apps/web
npm install @dnd-kit/core @dnd-kit/sortable @dnd-kit/utilities
```

Expected: packages added to `node_modules`, `package.json` updated with three new `@dnd-kit/*` entries.

- [ ] **Step 2: Verify TypeScript can resolve them**

```bash
cd apps/web
npx tsc --noEmit 2>&1 | head -20
```

Expected: zero errors (or only pre-existing errors unrelated to dnd-kit).

- [ ] **Step 3: Commit**

```bash
git add apps/web/package.json apps/web/package-lock.json
git commit -m "chore: install @dnd-kit packages for sprint planner"
```

---

### Task 2: Create shared sprint types

**Files:**
- Create: `apps/web/src/types/sprint.ts`

- [ ] **Step 1: Create types file**

```typescript
// apps/web/src/types/sprint.ts

export interface Assignment {
  ticket_id: string
  developer_id: string
  reasoning: string
  confidence: number
  story_points: number
}

export interface SprintPlanResponse {
  team_id: string
  sprint_start: string
  assignments: Assignment[]
  confidence_score: number
  summary: string
  warnings: string[]
  what_if_dropped: Record<string, number>
}

export interface WhatIfResponse {
  confidence_score: number
  what_if_dropped: Record<string, number>
}

export interface Ticket {
  ticket_id: string
  title: string
  developer_id: string
  story_points: number
  confidence: number
}

export interface JiraBoard {
  id: string
  name: string
  project_key: string
}
```

- [ ] **Step 2: Verify with TypeScript**

```bash
cd apps/web && npx tsc --noEmit 2>&1 | head -20
```

Expected: no new errors.

- [ ] **Step 3: Commit**

```bash
git add apps/web/src/types/sprint.ts
git commit -m "feat: add shared sprint TypeScript types"
```

---

### Task 3: Create OnboardingLayout

**Files:**
- Create: `apps/web/src/layouts/OnboardingLayout.tsx`

- [ ] **Step 1: Create the layout component**

```tsx
// apps/web/src/layouts/OnboardingLayout.tsx

interface OnboardingLayoutProps {
  children: React.ReactNode
}

export function OnboardingLayout({ children }: OnboardingLayoutProps) {
  return (
    <div style={{
      minHeight: '100vh',
      background: '#0f1117',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      padding: '1.5rem',
      fontFamily: 'system-ui, sans-serif',
    }}>
      <div style={{
        width: '100%',
        maxWidth: 480,
        background: '#1e2030',
        borderRadius: 12,
        padding: '2rem',
        border: '1px solid #2d2f45',
      }}>
        {children}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Verify TypeScript**

```bash
cd apps/web && npx tsc --noEmit 2>&1 | head -20
```

- [ ] **Step 3: Commit**

```bash
git add apps/web/src/layouts/OnboardingLayout.tsx
git commit -m "feat: add OnboardingLayout full-screen centred card"
```

---

### Task 4: Create sprint components directory

**Files:**
- Create directory: `apps/web/src/components/sprint/`

- [ ] **Step 1: Create placeholder index so directory exists**

```bash
mkdir -p apps/web/src/components/sprint
```

No commit yet — components will be added in Chunk 3.

---

## Chunk 2: Onboarding Flow

### Task 5: ConnectJiraStep

**Files:**
- Create: `apps/web/src/pages/onboarding/ConnectJiraStep.tsx`

- [ ] **Step 1: Create the step component**

```tsx
// apps/web/src/pages/onboarding/ConnectJiraStep.tsx

import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useApi } from '../../lib/api'

interface ConnectJiraStepProps {
  onNext: () => void
}

export function ConnectJiraStep({ onNext }: ConnectJiraStepProps) {
  const [searchParams] = useSearchParams()
  const [status, setStatus] = useState<'idle' | 'loading' | 'connected' | 'error'>('idle')
  const [error, setError] = useState<string | null>(null)
  const { get, post } = useApi()

  // Atlassian redirects back to this page with ?code= after the user grants access.
  // We exchange the code with our backend, then show success.
  useEffect(() => {
    const code = searchParams.get('code')
    if (code && status === 'idle') {
      setStatus('loading')
      post<void>('/api/jira/oauth/callback', { code })
        .then(() => setStatus('connected'))
        .catch(err => {
          setStatus('error')
          setError(err instanceof Error ? err.message : 'Failed to connect Jira')
        })
    }
  }, [searchParams])

  async function handleConnect() {
    setStatus('loading')
    setError(null)
    try {
      const data = await get<{ url: string }>('/api/jira/oauth/initiate')
      window.location.href = data.url
    } catch (err) {
      setStatus('error')
      setError(err instanceof Error ? err.message : 'Failed to initiate Jira connection')
    }
  }

  return (
    <div>
      <h2 style={{ color: '#e2e8f0', fontSize: '1.25rem', fontWeight: 700, margin: '0 0 8px' }}>
        Connect Jira
      </h2>
      <p style={{ color: '#94a3b8', fontSize: 14, marginBottom: '1.5rem', lineHeight: 1.6 }}>
        Connect your Atlassian account so Sprint Brain can read your team's tickets and sprint history.
      </p>

      {status === 'connected' ? (
        <div>
          <div style={{ color: '#4ade80', fontSize: 14, marginBottom: '1rem' }}>
            ✓ Jira connected successfully
          </div>
          <button onClick={onNext} style={primaryButtonStyle('#6366f1')}>
            Continue →
          </button>
        </div>
      ) : (
        <div>
          {error && (
            <div style={{ color: '#ef4444', fontSize: 13, marginBottom: 12 }}>{error}</div>
          )}
          <button
            onClick={handleConnect}
            disabled={status === 'loading'}
            style={primaryButtonStyle(status === 'loading' ? '#374151' : '#6366f1')}
          >
            {status === 'loading' ? 'Redirecting...' : 'Connect Atlassian Account →'}
          </button>
        </div>
      )}
    </div>
  )
}

function primaryButtonStyle(bg: string): React.CSSProperties {
  return {
    background: bg,
    color: '#fff',
    border: 'none',
    borderRadius: 6,
    padding: '0.625rem 1.25rem',
    fontSize: 14,
    fontWeight: 600,
    cursor: 'pointer',
    width: '100%',
  }
}
```

- [ ] **Step 2: Verify TypeScript**

```bash
cd apps/web && npx tsc --noEmit 2>&1 | head -20
```

Expected: no new errors.

- [ ] **Step 3: Commit**

```bash
git add apps/web/src/pages/onboarding/ConnectJiraStep.tsx
git commit -m "feat: add ConnectJiraStep — Atlassian OAuth initiation and code exchange"
```

---

### Task 6: SelectBoardStep

**Files:**
- Create: `apps/web/src/pages/onboarding/SelectBoardStep.tsx`

- [ ] **Step 1: Create the step component**

```tsx
// apps/web/src/pages/onboarding/SelectBoardStep.tsx

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useApi } from '../../lib/api'
import type { JiraBoard } from '../../types/sprint'

interface SelectBoardStepProps {
  onNext: () => void
  onBack: () => void
}

export function SelectBoardStep({ onNext, onBack }: SelectBoardStepProps) {
  const [selectedBoardId, setSelectedBoardId] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const { get, post } = useApi()

  const { data: boards, isLoading, error: fetchError } = useQuery({
    queryKey: ['jira-boards'],
    queryFn: () => get<JiraBoard[]>('/api/jira/boards'),
  })

  async function handleSave() {
    if (!selectedBoardId || !boards) return
    const board = boards.find(b => b.id === selectedBoardId)
    if (!board) return
    setSaving(true)
    setSaveError(null)
    try {
      await post('/api/jira/board-selection', { board_id: board.id, project_key: board.project_key })
      onNext()
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Failed to save board selection')
      setSaving(false)
    }
  }

  return (
    <div>
      <h2 style={{ color: '#e2e8f0', fontSize: '1.25rem', fontWeight: 700, margin: '0 0 8px' }}>
        Select Board
      </h2>
      <p style={{ color: '#94a3b8', fontSize: 14, marginBottom: '1.5rem', lineHeight: 1.6 }}>
        Choose the Jira board Sprint Brain will use for sprint planning.
      </p>

      {isLoading && (
        <div style={{ color: '#64748b', fontSize: 14, marginBottom: '1.5rem' }}>Loading boards...</div>
      )}
      {fetchError && (
        <div style={{ color: '#ef4444', fontSize: 13, marginBottom: 12 }}>
          Failed to load boards. Check your Jira connection.
        </div>
      )}
      {saveError && (
        <div style={{ color: '#ef4444', fontSize: 13, marginBottom: 12 }}>{saveError}</div>
      )}

      {boards && (
        <div style={{ marginBottom: '1.5rem' }}>
          {boards.length === 0 ? (
            <div style={{ color: '#64748b', fontSize: 14 }}>
              No boards found. Make sure your Jira account has access to at least one project.
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {boards.map(board => (
                <div
                  key={board.id}
                  onClick={() => setSelectedBoardId(board.id)}
                  style={{
                    padding: '0.75rem 1rem',
                    borderRadius: 6,
                    border: `2px solid ${selectedBoardId === board.id ? '#6366f1' : '#2d2f45'}`,
                    background: selectedBoardId === board.id ? '#2d2f45' : 'transparent',
                    cursor: 'pointer',
                    transition: 'border-color 0.15s, background 0.15s',
                  }}
                >
                  <div style={{ color: '#e2e8f0', fontSize: 14, fontWeight: 600 }}>{board.name}</div>
                  <div style={{ color: '#64748b', fontSize: 12, marginTop: 2 }}>{board.project_key}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      <div style={{ display: 'flex', gap: 8 }}>
        <button onClick={onBack} style={ghostButtonStyle}>← Back</button>
        <button
          onClick={handleSave}
          disabled={!selectedBoardId || saving}
          style={primaryButtonStyle(!selectedBoardId || saving ? '#374151' : '#6366f1')}
        >
          {saving ? 'Saving...' : 'Continue →'}
        </button>
      </div>
    </div>
  )
}

const ghostButtonStyle: React.CSSProperties = {
  background: 'transparent',
  color: '#94a3b8',
  border: '1px solid #2d2f45',
  borderRadius: 6,
  padding: '0.625rem 1rem',
  fontSize: 14,
  cursor: 'pointer',
}

function primaryButtonStyle(bg: string): React.CSSProperties {
  return {
    flex: 1,
    background: bg,
    color: '#fff',
    border: 'none',
    borderRadius: 6,
    padding: '0.625rem 1.25rem',
    fontSize: 14,
    fontWeight: 600,
    cursor: 'pointer',
  }
}
```

- [ ] **Step 2: Verify TypeScript**

```bash
cd apps/web && npx tsc --noEmit 2>&1 | head -20
```

- [ ] **Step 3: Commit**

```bash
git add apps/web/src/pages/onboarding/SelectBoardStep.tsx
git commit -m "feat: add SelectBoardStep — Jira board picker with React Query"
```

---

### Task 7: SaveAnthropicKeyStep

**Files:**
- Create: `apps/web/src/pages/onboarding/SaveAnthropicKeyStep.tsx`

- [ ] **Step 1: Create the step component**

```tsx
// apps/web/src/pages/onboarding/SaveAnthropicKeyStep.tsx

import { useState } from 'react'
import { useApi } from '../../lib/api'

interface SaveAnthropicKeyStepProps {
  onNext: () => void
  onBack: () => void
}

function maskKey(key: string): string {
  if (key.length < 12) return key
  return `${key.slice(0, 7)}...${key.slice(-4)}`
}

export function SaveAnthropicKeyStep({ onNext, onBack }: SaveAnthropicKeyStepProps) {
  const [key, setKey] = useState('')
  const [savedMasked, setSavedMasked] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { post } = useApi()

  async function handleSave() {
    if (!key.trim()) return
    setSaving(true)
    setError(null)
    try {
      await post('/api/settings/anthropic-key', { key: key.trim() })
      setSavedMasked(maskKey(key.trim()))
      setKey('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save key')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div>
      <h2 style={{ color: '#e2e8f0', fontSize: '1.25rem', fontWeight: 700, margin: '0 0 8px' }}>
        Anthropic API Key
      </h2>
      <p style={{ color: '#94a3b8', fontSize: 14, marginBottom: '1.5rem', lineHeight: 1.6 }}>
        Sprint Brain uses Claude to generate sprint plans. Paste your Anthropic API key — it is stored encrypted.
      </p>

      {savedMasked ? (
        <div style={{ marginBottom: '1.5rem' }}>
          <div style={{ color: '#4ade80', fontSize: 13, marginBottom: 8 }}>✓ Key saved</div>
          <div style={{
            padding: '0.5rem 0.75rem',
            background: '#0f1117',
            borderRadius: 4,
            fontFamily: 'monospace',
            fontSize: 13,
            color: '#a5b4fc',
            border: '1px solid #2d2f45',
          }}>
            {savedMasked}
          </div>
        </div>
      ) : (
        <div style={{ marginBottom: '1.5rem' }}>
          {error && (
            <div style={{ color: '#ef4444', fontSize: 13, marginBottom: 8 }}>{error}</div>
          )}
          <input
            type="password"
            value={key}
            onChange={e => setKey(e.target.value)}
            placeholder="sk-ant-..."
            style={{
              width: '100%',
              background: '#0f1117',
              border: '1px solid #2d2f45',
              borderRadius: 6,
              padding: '0.625rem 0.75rem',
              color: '#e2e8f0',
              fontSize: 14,
              fontFamily: 'monospace',
              boxSizing: 'border-box',
              marginBottom: 8,
              outline: 'none',
            }}
          />
          <button
            onClick={handleSave}
            disabled={!key.trim() || saving}
            style={{
              width: '100%',
              background: !key.trim() || saving ? '#374151' : '#6366f1',
              color: '#fff',
              border: 'none',
              borderRadius: 6,
              padding: '0.625rem 1.25rem',
              fontSize: 14,
              fontWeight: 600,
              cursor: !key.trim() || saving ? 'default' : 'pointer',
            }}
          >
            {saving ? 'Saving...' : 'Save Key'}
          </button>
        </div>
      )}

      <div style={{ display: 'flex', gap: 8 }}>
        <button onClick={onBack} style={ghostButtonStyle}>← Back</button>
        <button
          onClick={onNext}
          disabled={!savedMasked}
          style={{
            flex: 1,
            background: savedMasked ? '#6366f1' : '#374151',
            color: '#fff',
            border: 'none',
            borderRadius: 6,
            padding: '0.625rem 1.25rem',
            fontSize: 14,
            fontWeight: 600,
            cursor: savedMasked ? 'pointer' : 'default',
          }}
        >
          Finish Setup →
        </button>
      </div>
    </div>
  )
}

const ghostButtonStyle: React.CSSProperties = {
  background: 'transparent',
  color: '#94a3b8',
  border: '1px solid #2d2f45',
  borderRadius: 6,
  padding: '0.625rem 1rem',
  fontSize: 14,
  cursor: 'pointer',
}
```

- [ ] **Step 2: Verify TypeScript**

```bash
cd apps/web && npx tsc --noEmit 2>&1 | head -20
```

- [ ] **Step 3: Commit**

```bash
git add apps/web/src/pages/onboarding/SaveAnthropicKeyStep.tsx
git commit -m "feat: add SaveAnthropicKeyStep — encrypted key input with masked display"
```

---

### Task 8: OnboardingPage wizard shell

**Files:**
- Modify: `apps/web/src/pages/OnboardingPage.tsx` (replace stub content)

The existing App.tsx already imports `OnboardingPage` from `./pages/OnboardingPage` and renders it under `/onboarding/*`. No App.tsx change needed — `OnboardingPage` will render `OnboardingLayout` internally.

- [ ] **Step 1: Replace stub with wizard shell**

```tsx
// apps/web/src/pages/OnboardingPage.tsx

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { OnboardingLayout } from '../layouts/OnboardingLayout'
import { ConnectJiraStep } from './onboarding/ConnectJiraStep'
import { SelectBoardStep } from './onboarding/SelectBoardStep'
import { SaveAnthropicKeyStep } from './onboarding/SaveAnthropicKeyStep'

const STEPS = ['Connect Jira', 'Select Board', 'Anthropic Key'] as const
const STORAGE_KEY = 'aos_onboarding_step'

export function OnboardingPage() {
  const navigate = useNavigate()
  const [step, setStep] = useState<number>(() => {
    const saved = localStorage.getItem(STORAGE_KEY)
    return saved ? parseInt(saved, 10) : 0
  })

  function goTo(next: number) {
    localStorage.setItem(STORAGE_KEY, String(next))
    setStep(next)
  }

  function advance() {
    if (step === STEPS.length - 1) {
      localStorage.removeItem(STORAGE_KEY)
      navigate('/app/sprint-planner')
    } else {
      goTo(step + 1)
    }
  }

  function back() {
    goTo(step - 1)
  }

  return (
    <OnboardingLayout>
      {/* Step indicator */}
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: '2rem' }}>
        {STEPS.map((label, i) => (
          <div key={i} style={{ display: 'flex', alignItems: 'center' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <div style={{
                width: 28,
                height: 28,
                borderRadius: '50%',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                background: i < step ? '#6366f1' : 'transparent',
                border: i === step ? '2px solid #6366f1' : i < step ? 'none' : '2px solid #2d2f45',
                color: i < step ? '#fff' : i === step ? '#6366f1' : '#64748b',
                fontSize: 11,
                fontWeight: 700,
                flexShrink: 0,
              }}>
                {i < step ? '✓' : i + 1}
              </div>
              <span style={{ fontSize: 12, color: i === step ? '#e2e8f0' : '#64748b', whiteSpace: 'nowrap' }}>
                {label}
              </span>
            </div>
            {i < STEPS.length - 1 && (
              <div style={{ width: 24, height: 1, background: '#2d2f45', margin: '0 8px', flexShrink: 0 }} />
            )}
          </div>
        ))}
      </div>

      {step === 0 && <ConnectJiraStep onNext={advance} />}
      {step === 1 && <SelectBoardStep onNext={advance} onBack={back} />}
      {step === 2 && <SaveAnthropicKeyStep onNext={advance} onBack={back} />}
    </OnboardingLayout>
  )
}
```

- [ ] **Step 2: Verify TypeScript**

```bash
cd apps/web && npx tsc --noEmit 2>&1 | head -30
```

Expected: no errors from the new files.

- [ ] **Step 3: Commit**

```bash
git add apps/web/src/pages/OnboardingPage.tsx
git commit -m "feat: add OnboardingPage wizard shell — 3-step indicator, localStorage persistence"
```

---

## Chunk 3: Sprint Planner Components

### Task 9: VelocityCard

**Files:**
- Create: `apps/web/src/components/sprint/VelocityCard.tsx`

- [ ] **Step 1: Create VelocityCard**

```tsx
// apps/web/src/components/sprint/VelocityCard.tsx

export interface VelocityCardProps {
  developer: string
  meanVelocity: number
  committed: number
  capacity: number
  sprintCount: number
}

function utilColour(ratio: number): string {
  if (ratio < 0.8) return '#4ade80'
  if (ratio < 1.0) return '#fbbf24'
  return '#ef4444'
}

export function VelocityCard({ developer, meanVelocity, committed, capacity, sprintCount }: VelocityCardProps) {
  const isInsufficient = sprintCount < 3
  const ratio = capacity > 0 ? committed / capacity : 0
  const barColour = utilColour(ratio)

  return (
    <div style={{
      background: '#1e2030',
      borderRadius: 8,
      padding: '0.875rem 1rem',
      minWidth: 150,
      flex: 1,
    }}>
      <div style={{
        color: '#a5b4fc',
        fontSize: 11,
        fontWeight: 700,
        textTransform: 'uppercase',
        letterSpacing: '0.06em',
        marginBottom: 6,
      }}>
        {developer}
      </div>

      {isInsufficient ? (
        <div>
          <div style={{ color: '#64748b', fontSize: 13, marginBottom: 4 }}>Insufficient data</div>
          <div style={{ color: '#94a3b8', fontSize: 11 }}>
            {3 - sprintCount} more sprint{3 - sprintCount !== 1 ? 's' : ''} needed
          </div>
        </div>
      ) : (
        <>
          <div style={{ color: '#e2e8f0', fontSize: 22, fontWeight: 700, marginBottom: 4 }}>
            {meanVelocity} pts
          </div>
          <div style={{ color: '#94a3b8', fontSize: 11, marginBottom: 6 }}>
            {committed}/{capacity} pts committed
          </div>
          <div style={{ background: '#2d2f45', height: 6, borderRadius: 3 }}>
            <div style={{
              width: `${Math.min(ratio * 100, 100)}%`,
              height: 6,
              borderRadius: 3,
              background: barColour,
              transition: 'width 0.4s ease',
            }} />
          </div>
        </>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Verify TypeScript**

```bash
cd apps/web && npx tsc --noEmit 2>&1 | head -20
```

- [ ] **Step 3: Commit**

```bash
git add apps/web/src/components/sprint/VelocityCard.tsx
git commit -m "feat: add VelocityCard — dev velocity with utilisation bar and insufficient-data state"
```

---

### Task 10: ConfidenceGauge

**Files:**
- Create: `apps/web/src/components/sprint/ConfidenceGauge.tsx`

- [ ] **Step 1: Create ConfidenceGauge**

The gauge uses a standard SVG technique: `stroke-dasharray = circumference`, `stroke-dashoffset` animates from `circumference` (empty) to `circumference * (1 - score)` (filled).

```tsx
// apps/web/src/components/sprint/ConfidenceGauge.tsx

import { useEffect, useState } from 'react'

export interface ConfidenceGaugeProps {
  score: number        // 0–1
  sampleSize?: number
  sprintCount?: number
}

const R = 22
const CIRC = 2 * Math.PI * R  // ≈ 138.23

function gaugeColour(score: number): string {
  if (score > 0.75) return '#4ade80'
  if (score >= 0.5) return '#fbbf24'
  return '#ef4444'
}

export function ConfidenceGauge({ score, sampleSize, sprintCount }: ConfidenceGaugeProps) {
  const [animated, setAnimated] = useState(false)

  useEffect(() => {
    const t = setTimeout(() => setAnimated(true), 50)
    return () => clearTimeout(t)
  }, [])

  const pct = Math.round(score * 100)
  const colour = gaugeColour(score)
  const dashOffset = animated ? CIRC * (1 - score) : CIRC
  const label = score > 0.75 ? 'High' : score >= 0.5 ? 'Medium' : 'Low'

  const tooltipLines = [
    `Confidence: ${pct}%`,
    sampleSize != null ? `Based on ${sampleSize} tickets` : null,
    sprintCount != null ? `Across ${sprintCount} sprints` : null,
  ].filter((l): l is string => l !== null)

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
      <svg
        width={60}
        height={60}
        viewBox="0 0 60 60"
        role="img"
        aria-label={tooltipLines.join(', ')}
      >
        <title>{tooltipLines.join('\n')}</title>
        {/* Track */}
        <circle
          cx={30} cy={30} r={R}
          fill="none"
          stroke="#2d2f45"
          strokeWidth={6}
        />
        {/* Fill — rotated so 0% starts at top */}
        <circle
          cx={30} cy={30} r={R}
          fill="none"
          stroke={colour}
          strokeWidth={6}
          strokeDasharray={CIRC}
          strokeDashoffset={dashOffset}
          transform="rotate(-90 30 30)"
          style={{ transition: 'stroke-dashoffset 0.8s ease-out' }}
        />
        <text
          x={30} y={34}
          textAnchor="middle"
          fill="#e2e8f0"
          fontSize={11}
          fontWeight={700}
        >
          {pct}%
        </text>
      </svg>
      <div>
        <div style={{
          color: '#a5b4fc',
          fontSize: 11,
          fontWeight: 700,
          textTransform: 'uppercase',
          letterSpacing: '0.06em',
        }}>
          Confidence
        </div>
        <div style={{ color: colour, fontSize: 14, fontWeight: 700, marginTop: 2 }}>
          {label}
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Verify TypeScript**

```bash
cd apps/web && npx tsc --noEmit 2>&1 | head -20
```

- [ ] **Step 3: Commit**

```bash
git add apps/web/src/components/sprint/ConfidenceGauge.tsx
git commit -m "feat: add ConfidenceGauge — animated SVG radial gauge with colour thresholds"
```

---

### Task 11: PlanReasoningPanel

**Files:**
- Create: `apps/web/src/components/sprint/PlanReasoningPanel.tsx`

- [ ] **Step 1: Create PlanReasoningPanel**

```tsx
// apps/web/src/components/sprint/PlanReasoningPanel.tsx

import { useState } from 'react'
import type { Assignment } from '../../types/sprint'

interface PlanReasoningPanelProps {
  assignments: Assignment[]
}

function dotColour(c: number): string {
  if (c > 0.75) return '#4ade80'
  if (c >= 0.5) return '#fbbf24'
  return '#ef4444'
}

export function PlanReasoningPanel({ assignments }: PlanReasoningPanelProps) {
  const [openId, setOpenId] = useState<string | null>(null)

  if (assignments.length === 0) {
    return (
      <div style={{ color: '#64748b', fontSize: 13, padding: '1rem 0' }}>
        Generate a plan to see assignment reasoning.
      </div>
    )
  }

  return (
    <div>
      <div style={{
        color: '#a5b4fc',
        fontSize: 11,
        fontWeight: 700,
        textTransform: 'uppercase',
        letterSpacing: '0.06em',
        marginBottom: 10,
      }}>
        Why this assignment?
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        {assignments.map(a => {
          const isOpen = openId === a.ticket_id
          return (
            <div key={a.ticket_id} style={{ background: '#0f1117', borderRadius: 6, overflow: 'hidden' }}>
              <button
                onClick={() => setOpenId(isOpen ? null : a.ticket_id)}
                style={{
                  width: '100%',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  padding: '0.625rem 0.75rem',
                  background: 'transparent',
                  border: 'none',
                  cursor: 'pointer',
                  textAlign: 'left',
                }}
              >
                <span style={{ color: '#6366f1', fontSize: 12, fontWeight: 700, whiteSpace: 'nowrap' }}>
                  {a.ticket_id}
                </span>
                <span style={{
                  color: '#94a3b8',
                  fontSize: 12,
                  flex: 1,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}>
                  → {a.developer_id}
                </span>
                <span style={{ color: '#64748b', fontSize: 11, whiteSpace: 'nowrap' }}>
                  {a.story_points}pts
                </span>
                <span style={{
                  width: 8,
                  height: 8,
                  borderRadius: '50%',
                  background: dotColour(a.confidence),
                  flexShrink: 0,
                }} />
                <span style={{ color: '#64748b', fontSize: 10 }}>{isOpen ? '▲' : '▼'}</span>
              </button>

              {isOpen && (
                <div style={{
                  padding: '0.5rem 0.75rem 0.75rem',
                  color: '#94a3b8',
                  fontSize: 13,
                  lineHeight: 1.6,
                  borderTop: '1px solid #2d2f45',
                }}>
                  {a.reasoning}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Verify TypeScript**

```bash
cd apps/web && npx tsc --noEmit 2>&1 | head -20
```

- [ ] **Step 3: Commit**

```bash
git add apps/web/src/components/sprint/PlanReasoningPanel.tsx
git commit -m "feat: add PlanReasoningPanel — accordion showing assignment reasoning per ticket"
```

---

### Task 12: TicketList with drag-and-drop

**Files:**
- Create: `apps/web/src/components/sprint/TicketList.tsx`

- [ ] **Step 1: Create TicketList**

```tsx
// apps/web/src/components/sprint/TicketList.tsx

import { useState } from 'react'
import {
  DndContext,
  DragEndEvent,
  DragOverlay,
  DragStartEvent,
  PointerSensor,
  useSensor,
  useSensors,
  useDroppable,
} from '@dnd-kit/core'
import {
  SortableContext,
  verticalListSortingStrategy,
  useSortable,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import type { Ticket } from '../../types/sprint'

interface TicketListProps {
  tickets: Ticket[]
  droppedIds: Set<string>
  onDropTicket: (ticketId: string) => void
  onRestoreTicket: (ticketId: string) => void
}

function TicketRow({ ticket }: { ticket: Ticket }) {
  const dotColour = ticket.confidence > 0.75 ? '#4ade80' : ticket.confidence >= 0.5 ? '#fbbf24' : '#ef4444'
  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      gap: 8,
      padding: '0.5rem 0.625rem',
      background: '#1e2030',
      borderRadius: 4,
      marginBottom: 4,
      cursor: 'grab',
      borderLeft: '2px solid #6366f1',
      userSelect: 'none',
    }}>
      <span style={{ color: '#6366f1', fontSize: 11, fontWeight: 700, whiteSpace: 'nowrap' }}>
        {ticket.ticket_id}
      </span>
      <span style={{
        color: '#e2e8f0',
        fontSize: 12,
        flex: 1,
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        whiteSpace: 'nowrap',
      }}>
        {ticket.title}
      </span>
      <span style={{ color: '#94a3b8', fontSize: 11, whiteSpace: 'nowrap' }}>
        {ticket.developer_id}
      </span>
      <span style={{ color: '#64748b', fontSize: 11, whiteSpace: 'nowrap' }}>
        {ticket.story_points}pts
      </span>
      <span style={{ width: 8, height: 8, borderRadius: '50%', background: dotColour, flexShrink: 0 }} />
    </div>
  )
}

function SortableTicketRow({ ticket }: { ticket: Ticket }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: ticket.ticket_id,
  })
  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition, opacity: isDragging ? 0.4 : 1 }}
      {...attributes}
      {...listeners}
    >
      <TicketRow ticket={ticket} />
    </div>
  )
}

function DroppableZone({
  id,
  label,
  children,
  isEmpty,
  emptyText,
}: {
  id: string
  label: string
  children: React.ReactNode
  isEmpty: boolean
  emptyText: string
}) {
  const { setNodeRef, isOver } = useDroppable({ id })
  return (
    <div
      ref={setNodeRef}
      style={{
        flex: 1,
        background: isOver ? '#2d2f45' : '#0f1117',
        borderRadius: 6,
        padding: '0.75rem',
        border: `2px dashed ${isOver ? '#6366f1' : '#2d2f45'}`,
        minHeight: 80,
        transition: 'background 0.15s, border-color 0.15s',
      }}
    >
      <div style={{
        color: '#a5b4fc',
        fontSize: 11,
        fontWeight: 700,
        textTransform: 'uppercase',
        letterSpacing: '0.06em',
        marginBottom: 8,
      }}>
        {label}
      </div>
      {children}
      {isEmpty && (
        <div style={{ color: '#374151', fontSize: 12 }}>{emptyText}</div>
      )}
    </div>
  )
}

export function TicketList({ tickets, droppedIds, onDropTicket, onRestoreTicket }: TicketListProps) {
  const [activeId, setActiveId] = useState<string | null>(null)
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 8 } }))

  const inSprint = tickets.filter(t => !droppedIds.has(t.ticket_id))
  const removed = tickets.filter(t => droppedIds.has(t.ticket_id))
  const activeTicket = tickets.find(t => t.ticket_id === activeId)

  function handleDragStart(e: DragStartEvent) {
    setActiveId(String(e.active.id))
  }

  function handleDragEnd(e: DragEndEvent) {
    const { active, over } = e
    setActiveId(null)
    if (!over) return
    const ticketId = String(active.id)
    if (over.id === 'removed-zone' && !droppedIds.has(ticketId)) {
      onDropTicket(ticketId)
    } else if (over.id === 'sprint-zone' && droppedIds.has(ticketId)) {
      onRestoreTicket(ticketId)
    }
  }

  return (
    <DndContext sensors={sensors} onDragStart={handleDragStart} onDragEnd={handleDragEnd}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, height: '100%' }}>
        <DroppableZone
          id="sprint-zone"
          label="In Sprint"
          isEmpty={inSprint.length === 0}
          emptyText="No tickets in sprint"
        >
          <SortableContext items={inSprint.map(t => t.ticket_id)} strategy={verticalListSortingStrategy}>
            {inSprint.map(t => <SortableTicketRow key={t.ticket_id} ticket={t} />)}
          </SortableContext>
        </DroppableZone>

        <DroppableZone
          id="removed-zone"
          label="What-If: Removed"
          isEmpty={removed.length === 0}
          emptyText="Drag tickets here to model impact"
        >
          <SortableContext items={removed.map(t => t.ticket_id)} strategy={verticalListSortingStrategy}>
            {removed.map(t => <SortableTicketRow key={t.ticket_id} ticket={t} />)}
          </SortableContext>
        </DroppableZone>
      </div>

      <DragOverlay>
        {activeTicket && <TicketRow ticket={activeTicket} />}
      </DragOverlay>
    </DndContext>
  )
}
```

- [ ] **Step 2: Verify TypeScript**

```bash
cd apps/web && npx tsc --noEmit 2>&1 | head -30
```

Expected: no errors. The `@dnd-kit/*` packages ship their own types.

- [ ] **Step 3: Commit**

```bash
git add apps/web/src/components/sprint/TicketList.tsx
git commit -m "feat: add TicketList — dnd-kit drag-and-drop with In Sprint / What-If zones"
```

---

## Chunk 4: SprintPlannerPage

### Task 13: SprintPlannerPage — wire all components

**Files:**
- Modify: `apps/web/src/pages/SprintPlannerPage.tsx` (replace stub)

The page:
1. Renders a "Generate Plan" button
2. On click: `POST /api/sprint-brain/plan` via React Query mutation
3. Derives velocity display from assignments (committed pts per developer)
4. Passes data down to VelocityCard, ConfidenceGauge, TicketList, PlanReasoningPanel
5. On ticket drag to Removed: `POST /api/sprint-brain/what-if` → updates confidence live

- [ ] **Step 1: Replace stub with full implementation**

```tsx
// apps/web/src/pages/SprintPlannerPage.tsx

import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { useApi } from '../lib/api'
import { VelocityCard } from '../components/sprint/VelocityCard'
import { ConfidenceGauge } from '../components/sprint/ConfidenceGauge'
import { TicketList } from '../components/sprint/TicketList'
import { PlanReasoningPanel } from '../components/sprint/PlanReasoningPanel'
import type { SprintPlanResponse, WhatIfResponse, Ticket } from '../types/sprint'

// Derive committed points per developer from assignments
function deriveCommitted(assignments: SprintPlanResponse['assignments']): Map<string, number> {
  const map = new Map<string, number>()
  for (const a of assignments) {
    map.set(a.developer_id, (map.get(a.developer_id) ?? 0) + a.story_points)
  }
  return map
}

const DEFAULT_CAPACITY = 40  // pts per developer per sprint; replace when velocity API exists

export function SprintPlannerPage() {
  const { post } = useApi()
  const [plan, setPlan] = useState<SprintPlanResponse | null>(null)
  const [confidence, setConfidence] = useState(0)
  const [droppedIds, setDroppedIds] = useState<Set<string>>(new Set())
  const [warnings, setWarnings] = useState<string[]>([])

  const generatePlan = useMutation({
    mutationFn: () =>
      post<SprintPlanResponse>('/api/sprint-brain/plan', {
        team_id: 'default',
        sprint_length_days: 14,
        pto_overrides: {},
      }),
    onSuccess: data => {
      setPlan(data)
      setConfidence(data.confidence_score)
      setWarnings(data.warnings)
      setDroppedIds(new Set())
    },
  })

  const whatIf = useMutation({
    mutationFn: (dropped: string[]) =>
      post<WhatIfResponse>('/api/sprint-brain/what-if', {
        team_id: 'default',
        sprint_length_days: 14,
        dropped_ticket_ids: dropped,
      }),
    onSuccess: data => {
      setConfidence(data.confidence_score)
    },
  })

  function handleDropTicket(ticketId: string) {
    const next = new Set(droppedIds)
    next.add(ticketId)
    setDroppedIds(next)
    whatIf.mutate(Array.from(next))
  }

  function handleRestoreTicket(ticketId: string) {
    const next = new Set(droppedIds)
    next.delete(ticketId)
    setDroppedIds(next)
    whatIf.mutate(Array.from(next))
  }

  const committed = plan ? deriveCommitted(plan.assignments) : new Map<string, number>()
  const developers = Array.from(committed.keys())

  const tickets: Ticket[] = (plan?.assignments ?? []).map(a => ({
    ticket_id: a.ticket_id,
    title: a.ticket_id,   // title not yet in API response; use ID as fallback
    developer_id: a.developer_id,
    story_points: a.story_points,
    confidence: a.confidence,
  }))

  return (
    <div style={{ background: '#0f1117', minHeight: '100%', padding: '1.5rem', fontFamily: 'system-ui, sans-serif' }}>

      {/* Top row: velocity cards + gauge + action button */}
      <div style={{ display: 'flex', gap: 12, alignItems: 'stretch', marginBottom: 16, flexWrap: 'wrap' }}>

        {developers.length === 0 && !generatePlan.isPending && (
          <div style={{
            flex: 1,
            background: '#1e2030',
            borderRadius: 8,
            padding: '0.875rem 1rem',
            color: '#64748b',
            fontSize: 13,
            display: 'flex',
            alignItems: 'center',
          }}>
            Velocity cards will appear here after generating a plan.
          </div>
        )}

        {developers.map(dev => (
          <VelocityCard
            key={dev}
            developer={dev}
            meanVelocity={committed.get(dev) ?? 0}
            committed={committed.get(dev) ?? 0}
            capacity={DEFAULT_CAPACITY}
            sprintCount={3}
          />
        ))}

        {plan && (
          <div style={{ background: '#1e2030', borderRadius: 8, padding: '0.875rem 1rem', display: 'flex', alignItems: 'center' }}>
            <ConfidenceGauge score={confidence} sampleSize={plan.assignments.length} />
          </div>
        )}

        <button
          onClick={() => generatePlan.mutate()}
          disabled={generatePlan.isPending}
          style={{
            background: generatePlan.isPending ? '#374151' : '#6366f1',
            color: '#fff',
            border: 'none',
            borderRadius: 8,
            padding: '0.875rem 1.5rem',
            fontSize: 14,
            fontWeight: 700,
            cursor: generatePlan.isPending ? 'default' : 'pointer',
            whiteSpace: 'nowrap',
            alignSelf: 'center',
          }}
        >
          {generatePlan.isPending ? 'Generating...' : '✦ Generate Plan'}
        </button>
      </div>

      {/* Error banner */}
      {generatePlan.isError && (
        <div style={{ color: '#ef4444', fontSize: 13, marginBottom: 12 }}>
          {generatePlan.error instanceof Error
            ? generatePlan.error.message
            : 'Failed to generate plan. Check your Anthropic key and Jira connection.'}
        </div>
      )}

      {/* Warnings */}
      {warnings.length > 0 && (
        <div style={{ background: '#1e2030', borderRadius: 8, padding: '0.75rem 1rem', marginBottom: 16, display: 'flex', flexDirection: 'column', gap: 4 }}>
          {warnings.map((w, i) => (
            <div key={i} style={{ color: '#fbbf24', fontSize: 13, display: 'flex', gap: 8 }}>
              <span>⚠</span><span>{w}</span>
            </div>
          ))}
        </div>
      )}

      {/* Bottom: tickets + reasoning */}
      {plan && (
        <div style={{ display: 'flex', gap: 12, minHeight: 400 }}>
          <div style={{ flex: 1 }}>
            <TicketList
              tickets={tickets}
              droppedIds={droppedIds}
              onDropTicket={handleDropTicket}
              onRestoreTicket={handleRestoreTicket}
            />
          </div>
          <div style={{
            flex: 1,
            background: '#1e2030',
            borderRadius: 8,
            padding: '1rem',
            overflowY: 'auto',
          }}>
            <PlanReasoningPanel assignments={plan.assignments} />
          </div>
        </div>
      )}

      {/* Empty state */}
      {!plan && !generatePlan.isPending && (
        <div style={{ textAlign: 'center', padding: '5rem 0', color: '#374151' }}>
          <div style={{ fontSize: 48, marginBottom: 12 }}>✦</div>
          <div style={{ fontSize: 14, color: '#64748b' }}>Click "Generate Plan" to start sprint planning</div>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Verify TypeScript compiles cleanly**

```bash
cd apps/web && npx tsc --noEmit 2>&1
```

Expected: zero errors. If errors appear, fix before committing.

- [ ] **Step 3: Run dev server and visually check the page**

```bash
cd apps/web && npm run dev
```

Navigate to `http://localhost:5173/app/sprint-planner`. Expected:
- Dark `#0f1117` background fills the main content area
- "Generate Plan" indigo button visible
- Empty state star icon and helper text visible
- No console errors

Also navigate to `http://localhost:5173/onboarding`. Expected:
- Full-screen dark card centred on page
- 3-step indicator at top
- "Connect Atlassian Account →" button visible

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/pages/SprintPlannerPage.tsx
git commit -m "feat: implement SprintPlannerPage — velocity row, confidence gauge, ticket dnd, reasoning panel"
```

---

### Task 14: Final integration commit

- [ ] **Step 1: Run full TypeScript check one last time**

```bash
cd apps/web && npx tsc --noEmit 2>&1
```

Expected: zero errors.

- [ ] **Step 2: Verify build compiles**

```bash
cd apps/web && npm run build 2>&1 | tail -10
```

Expected: build succeeds with no TypeScript errors.

- [ ] **Step 3: Check for any unstaged files from earlier tasks**

```bash
git status
```

If `apps/web/src/types/sprint.ts` or `apps/web/src/layouts/OnboardingLayout.tsx` appear as untracked (they should be committed already from Tasks 2 and 3), stage and commit them:

```bash
# Only run if git status shows these as untracked:
git add apps/web/src/types/sprint.ts apps/web/src/layouts/OnboardingLayout.tsx
git commit -m "feat: add OnboardingLayout and sprint types"
```

- [ ] **Step 4: Verify git log looks clean**

```bash
git log --oneline -10
```

Expected commits on `track-h-sprint-brain-ui`:
```
feat: implement SprintPlannerPage — velocity row, confidence gauge, ticket dnd, reasoning panel
feat: add TicketList — dnd-kit drag-and-drop with In Sprint / What-If zones
feat: add PlanReasoningPanel — accordion showing assignment reasoning per ticket
feat: add ConfidenceGauge — animated SVG radial gauge with colour thresholds
feat: add VelocityCard — dev velocity with utilisation bar and insufficient-data state
feat: add 3-step onboarding wizard — Jira OAuth, board select, Anthropic key
feat: add shared sprint TypeScript types
chore: install @dnd-kit packages for sprint planner
docs: add Track H Sprint Brain UI design spec
```
