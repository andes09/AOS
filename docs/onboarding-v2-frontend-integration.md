# Onboarding v2 — frontend integration guide

This is for whoever builds the real onboarding UI. The backend and a small
headless React layer are done; this doc is everything you need to build
against them without reading the API source.

**TL;DR:** import hooks from `apps/web/src/features/onboarding-v2`, don't call
`fetch` yourself, don't hardcode step order — render whatever
`state.currentStep` says.

## What already exists

- **API**: `apps/api/src/routers/onboarding_v2.py` + `apps/api/src/integrations/github/router.py`
- **Headless layer** (your integration surface): `apps/web/src/features/onboarding-v2/`
- **Throwaway reference UI**: `apps/web/src/pages/OnboardingV2Page.tsx` — plain
  unstyled HTML that proves the flow works end to end. Copy the *wiring*
  (which hook goes with which step), not the markup.

You should never need to touch the backend or call `fetch` directly — the
hooks handle auth (Clerk bearer token), error shapes, and the SSE chat
protocol for you.

## The flow

Onboarding is five steps, always in this order:

```
profile → purpose → build_plan → github_repo → done
```

`build_plan` is a fork, not a single step: until the user picks a plan
source, its `id` in `state.steps` is `'build_plan'`; once they pick via
`savePlanSource('chat' | 'import')`, it becomes `'idea_chat'` or
`'import_artifact'` for the rest of the session (no path-switching UI —
the choice is fixed once its sub-flow starts). `github_repo` covers
connecting GitHub *and* picking (or creating) a repo as one skippable step —
it renders as two phases (connect, then pick/create) off the same
`state.currentStep === 'github_repo'`, and auto-completes on its own if
GitHub was never connected in the first place (nothing to pick a repo from).
**Don't hardcode any of this in your UI logic** — read it off
`state.steps` / `state.currentStep` so if we ever reorder or add a step, your
UI adapts without a code change.

The whole flow state comes from one hook:

```tsx
import { useOnboardingState } from '../features/onboarding-v2'

const { state, isLoading, error, skipGithub, saveProfile, savePurpose, savePlanSource, complete } =
  useOnboardingState()
```

`state` looks like this (see `types.ts` for the full shape):

```ts
{
  currentStep: 'profile' | 'purpose' | 'build_plan' | 'idea_chat'
             | 'import_artifact' | 'github_repo' | 'done',
  steps: [
    { id: 'profile',        status: 'complete' | 'current' | 'pending', skippable: false },
    { id: 'purpose',        status: ..., skippable: false },
    { id: 'build_plan' | 'idea_chat' | 'import_artifact', status: ..., skippable: false },
    { id: 'github_repo',    status: ..., skippable: true },
  ],
  github:   { connected: boolean, login: string | null, skipped: boolean, needsReconnect: boolean },
  profile:  { name: string | null, phone: string | null, complete: boolean },
  purpose:  { value: 'hobby' | 'startup' | 'learning' | null, complete: boolean },
  ideaChat: { sessionId, status, messageCount, brief, briefComplete },
  onboardingPath: 'chat' | 'import' | null,
  importArtifact: { analyzed, projectName, summary, milestones, missingFields } | null,
  repo: { selected: string | null, skipped: boolean, available: boolean },
  onboardingCompleted: boolean,
}
```

Render based on `state.currentStep`. Every mutation below returns the **full
new state**, so after calling one, `state` is already up to date — no manual
refetch needed.

### Step 1 — Profile (name + phone)

```tsx
saveProfile.mutate({ name, phone })
```

Validation (name 1–255 chars, phone must look like a phone number) happens
server-side and surfaces as `saveProfile.error.message` — a 422 means one of
the fields is invalid, show that message next to the form.

### Step 2 — Purpose (hobby / startup / learning)

**This is a 3-way choice, not free text.** It determines how the AI interview
in the next step behaves — a hobby project gets asked about fun and spare
time, a startup gets asked about market and MVP scope, a learning project
gets asked about skill goals. Don't build a text input for this; render three
buttons/cards and call:

```tsx
savePurpose.mutate('hobby' | 'startup' | 'learning')
```

### Step 3 — Idea interview (the AI chat)

```tsx
import { useIdeaChat } from '../features/onboarding-v2'

const chat = useIdeaChat()
// chat.messages        — full transcript so far (ChatMessage[])
// chat.streamingReply   — partial assistant text while chat.isStreaming is true
// chat.isStreaming      — true while a reply is being generated
// chat.status           — 'not_started' | 'in_progress' | 'completed'
// chat.brief            — the structured ProjectBrief extracted so far (or null)
// chat.error            — last error message, or null
// chat.send(text)        — send a user message
// chat.complete()        — user override: "that's enough, wrap up"
```

The hook auto-starts the session on mount (calls `chat/start` once). Render
`chat.messages`, and while `chat.isStreaming` is true, show
`chat.streamingReply` as an in-progress assistant bubble (it fills in token by
token). When `chat.send()` resolves, the finished message has already been
appended to `chat.messages` and `streamingReply` clears — you don't need to
merge them yourself.

Show a "that's enough — finish up" button once there's been some back-and-
forth (the reference UI gates it on `chat.messages.length > 2`); it lets the
user end the interview instead of waiting for the AI to decide it has enough.
When `chat.status === 'completed'`, disable the input and move on.

### Step 3 (fork) — build_plan: chat or import

`build_plan` isn't one step, it's a chooser. Render it while
`state.currentStep === 'build_plan'`:

```tsx
savePlanSource.mutate('chat' | 'import')
```

After that call resolves, `state.currentStep` becomes `'idea_chat'` (existing
flow, unchanged — see below) or `'import_artifact'` — pick your next
component off `state.currentStep`, same as everywhere else in this flow.

#### idea_chat (chat path)

Unchanged from before — see "Idea interview" below.

#### import_artifact (import path)

```tsx
import { useImportArtifact } from '../features/onboarding-v2'

const {
  importState,      // { analyzed, projectName, summary, milestones, missingFields, truncated? } | undefined
  milestones,        // importState.milestones, or []
  analyze,           // analyze.mutate({ text?: string, files?: File[] })
  apply,             // apply.mutate(briefOverrides?: Record<string, unknown>)
  isAccepted,        // (index: number) => boolean — defaults to true for every milestone
  toggleMilestone,   // (index: number) => void — local only, not sent to the server per toggle
  acceptedCount,
} = useImportArtifact()
```

Flow: user pastes text and/or attaches files (`.txt`/`.md`/`.pdf`/`.docx`, up
to 5 files, 10MB each) → `analyze.mutate(...)` → once `importState.analyzed`
is true, render one card per milestone with `toggleMilestone` wired to a
checkbox (defaulting to accepted) → for each `importState.missingFields`
entry, collect a value and pass it as a key in `apply`'s `briefOverrides` →
`apply.mutate(overrides)` once `acceptedCount >= 1`. `apply`'s success sets
the same onboarding state everything else does — no manual navigation needed,
`state.currentStep` moves on by itself.

### Step 4 — GitHub + repo (skippable)

One step, two phases, both keyed off `state.currentStep === 'github_repo'`:

**Phase A — GitHub not connected** (`!state.github.connected ||
state.github.needsReconnect`):

```tsx
import { useGithubConnect } from '../features/onboarding-v2'

const { connect, disconnect, redirectResult } = useGithubConnect('/onboarding')

<button onClick={() => connect.mutate()}>Connect GitHub</button>
<button onClick={() => skipGithub.mutate()}>Skip for now</button>
```

`connect.mutate()` redirects the whole page to GitHub's consent screen.
GitHub redirects back to the same URL with `?github=connected` or
`?github=error&reason=...` — `redirectResult` parses that for you on mount, so
check it once to show a success/error message:

```tsx
if (redirectResult?.outcome === 'error') {
  // show redirectResult.reason (e.g. "token_exchange_failed")
}
```

`skipGithub.mutate()` here skips the *whole* step — with no connection,
there's no repo to pick either, so the backend auto-completes both halves at
once.

**Phase B — GitHub connected**: render the repo picker instead. Its skip only
skips the repo half (GitHub stays connected):

```tsx
import { useRepoSelect } from '../features/onboarding-v2'

const { repos, page, setPage, selectRepo, skip, createRepo } = useRepoSelect()
// repos.data — GithubRepo[] for the current page
// selectRepo.mutate(repoFullName)
// skip.mutate()
// createRepo.mutate({ name, isPrivate }) — chat/greenfield path only, gated
//   behind state.repo.canCreate (an Organization install with
//   experimental.repo_create on; personal accounts are connect-only)
```

`state.currentStep` only moves past `github_repo` once *both* phases are
done (connected-or-skipped, and repo-picked-or-skipped-or-unavailable) — see
`GithubRepoStep.tsx` in the reference UI for the phase switch itself.

### Step 5 — Done

```tsx
await complete.mutateAsync()  // sets onboardingCompleted, then navigate to /app
```

`complete` only requires the profile step — it will never get stuck waiting
on GitHub or on the AI's judgment about the interview, so it's always safe to
call once you're on the `done` step.

## Local setup

1. `apps/api/.env` needs (see root `.env.example`): `GITHUB_CLIENT_ID`,
   `GITHUB_CLIENT_SECRET`, `GITHUB_REDIRECT_URI`, and `GROQ_API_KEY` (the idea
   interview and artifact-import analysis both run on Groq's platform key,
   not Anthropic — see the Import Artifacts plan's Implementation Notes for
   why this doc's older `ANTHROPIC_API_KEY` guidance no longer applies here).
2. Import Artifacts is gated by `experimental.import_artifacts` in
   `apps/api/config/features/*.yaml` — **on** in `local.yaml`/`test.yaml`,
   **off** in `production.yaml`. Nothing to flip locally.
3. Build against `/onboarding/v2` directly while any onboarding-wide flag is
   still off in production:
   `http://localhost:5174/onboarding/v2`
4. `VITE_TEST_MODE=true` skips the Clerk `<SignedIn>` wrapper and lets the
   headless client send a dummy bearer token — useful for Playwright, and for
   poking at the UI without a real login if you mock the API routes.

## Rules of the road

- **Only import from `apps/web/src/features/onboarding-v2`.** Never call
  `fetch('/api/onboarding/v2/...')` yourself — the hooks own auth, error
  parsing, and the SSE protocol.
- **Don't guess field names or step order from memory** — `types.ts` in that
  folder is the source of truth, and it's kept in lockstep with the backend
  by tests (`apps/api/tests/test_onboarding_v2.py`).
- **`OnboardingV2Page.tsx` is disposable.** It exists to prove the hooks work;
  replace its markup entirely, keep its wiring logic as a reference.
- If you need a field or endpoint that isn't here, ask rather than adding a
  raw fetch call — there's probably a reason it's shaped the way it is (e.g.
  purpose is a fixed enum, not free text, because it drives the system prompt
  server-side).
