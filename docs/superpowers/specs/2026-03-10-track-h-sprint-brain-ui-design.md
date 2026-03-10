# Track H — Sprint Brain UI Design

Date: 2026-03-10
Status: Approved

## Visual Direction

Dark/Indigo palette. `#0f1117` page background, `#1e2030` card surfaces, `#6366f1` primary accent, semantic colours for status: `#4ade80` green (healthy), `#fbbf24` amber (warning), `#ef4444` red (over-capacity). Inline styles throughout (no CSS framework — consistent with existing codebase).

## Route Structure

```
/onboarding          OnboardingLayout (full-screen, no sidebar)
  /onboarding        → OnboardingPage (step router)

/sprint              DashboardLayout (with sidebar)
  /sprint            → SprintPlannerPage
```

## New Files

```
apps/web/src/
  layouts/
    OnboardingLayout.tsx
  pages/onboarding/
    OnboardingPage.tsx
    ConnectJiraStep.tsx
    SelectBoardStep.tsx
    SaveAnthropicKeyStep.tsx
  pages/
    SprintPlannerPage.tsx          (replaces stub)
  components/sprint/
    VelocityCard.tsx
    TicketList.tsx
    ConfidenceGauge.tsx
    PlanReasoningPanel.tsx
```

## Onboarding Flow

Full-screen centred card layout. Step state held in `useState`, persisted to `localStorage` so refresh doesn't reset progress.

- **Step 1 — ConnectJiraStep**: Button → redirect to Atlassian OAuth URL. On return, detect `?code=` param and advance.
- **Step 2 — SelectBoardStep**: `GET /api/jira/boards` via `useApi()`. Dropdown to pick board + project. POST selection to `/api/jira/board-selection`.
- **Step 3 — SaveAnthropicKeyStep**: Text input for key. `POST /api/settings/anthropic-key`. On success, display masked key (`sk-ant-...xxxx`). Advance to `/sprint`.

Step indicator: numbered dots (1/2/3), completed steps filled indigo, current step outlined, future steps grey. Back button available on steps 2 and 3.

## SprintPlannerPage Layout (Option C)

```
┌─────────────────────────────────────────────────────────┐
│  [VelocityCard Alice] [VelocityCard Bob] [VelocityCard Carol] [ConfidenceGauge + Generate button]  │
├──────────────────────────┬──────────────────────────────┤
│  TicketList              │  PlanReasoningPanel          │
│  (In Sprint / Removed)   │  (accordion assignments)     │
└──────────────────────────┴──────────────────────────────┘
```

Top row scrolls horizontally if team is large. Bottom panels share equal width.

## Component Specs

### VelocityCard
- Props: `developer: string`, `meanVelocity: number`, `committed: number`, `capacity: number`, `sprintCount: number`
- Committed/capacity bar: green if `committed/capacity < 0.8`, amber if `0.8–0.99`, red if `≥ 1.0`
- Insufficient data state: shown when `sprintCount < 3`. Displays "Need X more sprint(s)" instead of bar.

### ConfidenceGauge
- Props: `score: number` (0–1), `sampleSize: number`, `sprintCount: number`
- SVG radial gauge. Animates via CSS transition on `stroke-dashoffset` from 0 to target on mount.
- Colour: green if `score > 0.75`, amber if `0.5–0.75`, red if `< 0.5`
- Tooltip (native `<title>`) showing data basis.

### TicketList
- Library: `@dnd-kit/core` + `@dnd-kit/sortable`
- Two droppable containers: "In Sprint" and "What-If: Removed"
- Dragging ticket to Removed calls `POST /api/sprint-brain/what-if` with `dropped_ticket_ids`
- Response updates ConfidenceGauge score live (lifted state in SprintPlannerPage)
- Each ticket row: `[ticket_id] [title] [assignee chip] [points badge] [confidence dot]`

### PlanReasoningPanel
- Props: `assignments: Assignment[]` where `Assignment = { ticket_id, developer_id, reasoning, confidence, story_points }`
- Accordion: one item open at a time. Chevron rotates on open.
- Collapsed: shows ticket ID, assignee, points, confidence dot
- Expanded: adds `reasoning` paragraph below

### OnboardingLayout
- Centred card, max-width 480px, vertically centred on page
- Dark background `#0f1117`, card surface `#1e2030`, indigo border accent

## State Management

- All planner state (plan result, removed tickets, confidence) in `SprintPlannerPage` via `useState` + React Query
- `useApi()` hook for all authenticated requests (already in codebase)
- No global state store needed

## API Endpoints Used

| Endpoint | Method | Used by |
|---|---|---|
| `/api/jira/boards` | GET | SelectBoardStep |
| `/api/jira/board-selection` | POST | SelectBoardStep |
| `/api/settings/anthropic-key` | POST | SaveAnthropicKeyStep |
| `/api/sprint-brain/plan` | POST | SprintPlannerPage |
| `/api/sprint-brain/what-if` | POST | TicketList (on drag) |

## New Dependency

`@dnd-kit/core` + `@dnd-kit/sortable` — drag-and-drop for TicketList what-if modelling.
