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

Onboarding is four steps, always in this order:

```
github_connect → profile → purpose → idea_chat → done
```

`github_connect` is skippable; the rest are required. **Don't hardcode this
order in your UI logic** — read it off `state.steps` / `state.currentStep` so
if we ever reorder or add a step, your UI adapts without a code change.

The whole flow state comes from one hook:

```tsx
import { useOnboardingState } from '../features/onboarding-v2'

const { state, isLoading, error, skipGithub, saveProfile, savePurpose, complete } =
  useOnboardingState()
```

`state` looks like this (see `types.ts` for the full shape):

```ts
{
  currentStep: 'github_connect' | 'profile' | 'purpose' | 'idea_chat' | 'done',
  steps: [
    { id: 'github_connect', status: 'complete' | 'current' | 'pending', skippable: true },
    { id: 'profile',        status: ..., skippable: false },
    { id: 'purpose',        status: ..., skippable: false },
    { id: 'idea_chat',      status: ..., skippable: false },
  ],
  github:   { connected: boolean, login: string | null, skipped: boolean },
  profile:  { name: string | null, phone: string | null, complete: boolean },
  purpose:  { value: 'hobby' | 'startup' | 'learning' | null, complete: boolean },
  ideaChat: { sessionId, status, messageCount, brief, briefComplete },
  onboardingCompleted: boolean,
}
```

Render based on `state.currentStep`. Every mutation below returns the **full
new state**, so after calling one, `state` is already up to date — no manual
refetch needed.

### Step 1 — GitHub connect (skippable)

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

### Step 2 — Profile (name + phone)

```tsx
saveProfile.mutate({ name, phone })
```

Validation (name 1–255 chars, phone must look like a phone number) happens
server-side and surfaces as `saveProfile.error.message` — a 422 means one of
the fields is invalid, show that message next to the form.

### Step 3 — Purpose (hobby / startup / learning)

**This is a 3-way choice, not free text.** It determines how the AI interview
in the next step behaves — a hobby project gets asked about fun and spare
time, a startup gets asked about market and MVP scope, a learning project
gets asked about skill goals. Don't build a text input for this; render three
buttons/cards and call:

```tsx
savePurpose.mutate('hobby' | 'startup' | 'learning')
```

### Step 4 — Idea interview (the AI chat)

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

### Step 5 — Done

```tsx
await complete.mutateAsync()  // sets onboardingCompleted, then navigate to /app
```

`complete` only requires the profile step — it will never get stuck waiting
on GitHub or on the AI's judgment about the interview, so it's always safe to
call once you're on the `done` step.

## Local setup

1. `apps/api/.env` needs (see root `.env.example`): `GITHUB_CLIENT_ID`,
   `GITHUB_CLIENT_SECRET`, `GITHUB_REDIRECT_URI`, and `ANTHROPIC_API_KEY`
   (the idea interview needs a working key even before an org saves its own).
2. The `onboarding_v2` feature flag is **on** in
   `apps/api/config/features/local.yaml` — nothing to flip locally.
3. Build against `/onboarding/v2` directly (bypasses the flag check) while
   the flag is still off in production:
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
