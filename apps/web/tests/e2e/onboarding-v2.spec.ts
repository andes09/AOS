import { test, expect } from '@playwright/test'

/**
 * E2e walk of the onboarding v2 flow (GitHub → profile → idea chat → done)
 * against the reference UI at /onboarding/v2.
 *
 * Requires VITE_TEST_MODE=true: App.tsx skips <SignedIn> and the headless
 * client uses a dummy bearer token, so every API route here is intercepted
 * with canned responses — including the SSE chat stream.
 */

type StepStatus = 'complete' | 'current' | 'pending'

function makeState(current: 'github_connect' | 'profile' | 'purpose' | 'idea_chat' | 'done') {
  const order = ['github_connect', 'profile', 'purpose', 'idea_chat'] as const
  const currentIdx = current === 'done' ? order.length : order.indexOf(current)
  const status = (i: number): StepStatus =>
    i < currentIdx ? 'complete' : i === currentIdx ? 'current' : 'pending'
  return {
    currentStep: current,
    steps: order.map((id, i) => ({ id, status: status(i), skippable: id === 'github_connect' })),
    github: { connected: false, login: null, skipped: currentIdx > 0 },
    profile:
      currentIdx > 1
        ? { name: 'Ada Lovelace', phone: '+1 555 123 4567', complete: true }
        : { name: null, phone: null, complete: false },
    purpose:
      currentIdx > 2
        ? { value: 'startup', complete: true }
        : { value: null, complete: false },
    ideaChat: {
      sessionId: currentIdx > 3 ? 'sess-1' : null,
      status: current === 'done' ? 'completed' : 'not_started',
      messageCount: 0,
      brief: null,
      briefComplete: false,
    },
    onboardingCompleted: false,
  }
}

const SSE_TURN = [
  'event: token\ndata: {"text":"Sounds "}\n',
  'event: token\ndata: {"text":"great! Who is it for?"}\n',
  'event: brief\ndata: {"brief":{"projectName":"Roadmapper"},"missingFields":["targetAudience"],"briefComplete":false}\n',
  'event: done\ndata: {"messageId":"m-2","status":"in_progress"}\n',
].join('\n')

test.describe('Onboarding v2 flow', () => {
  test('walks GitHub skip → profile → idea chat → done', async ({ page }) => {
    // GET /state serves whatever step the flow has reached; mutations advance it.
    let state = makeState('github_connect')

    await page.route('**/api/onboarding/v2/state', route =>
      route.fulfill({ status: 200, body: JSON.stringify(state) }),
    )
    await page.route('**/api/onboarding/v2/github/skip', route => {
      state = makeState('profile')
      return route.fulfill({ status: 200, body: JSON.stringify(state) })
    })
    await page.route('**/api/onboarding/v2/profile', route => {
      state = makeState('purpose')
      return route.fulfill({ status: 200, body: JSON.stringify(state) })
    })
    await page.route('**/api/onboarding/v2/purpose', route => {
      state = makeState('idea_chat')
      return route.fulfill({ status: 200, body: JSON.stringify(state) })
    })
    await page.route('**/api/onboarding/v2/chat/start', route =>
      route.fulfill({
        status: 200,
        body: JSON.stringify({
          sessionId: 'sess-1',
          status: 'in_progress',
          messages: [
            {
              id: 'm-0',
              role: 'assistant',
              content: "Hi! Tell me about your idea — what are you building?",
              createdAt: new Date().toISOString(),
            },
          ],
          brief: null,
          briefComplete: false,
        }),
      }),
    )
    await page.route('**/api/onboarding/v2/chat/message', route =>
      route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: SSE_TURN,
      }),
    )
    await page.route('**/api/onboarding/v2/chat/complete', route => {
      state = makeState('done')
      return route.fulfill({ status: 200, body: JSON.stringify(state) })
    })
    await page.route('**/api/onboarding/v2/complete', route =>
      route.fulfill({ status: 200, body: JSON.stringify({ completedAt: new Date().toISOString() }) }),
    )

    await page.goto('/onboarding/v2')

    // Step 1: GitHub connect, skipped.
    await expect(page.getByRole('heading', { name: 'Connect your GitHub' })).toBeVisible()
    await page.getByRole('button', { name: 'Skip for now' }).click()

    // Step 2: profile.
    await expect(page.getByRole('heading', { name: 'Tell us who you are' })).toBeVisible()
    await page.getByLabel('Name').fill('Ada Lovelace')
    await page.getByLabel('Phone').fill('+1 555 123 4567')
    await page.getByRole('button', { name: 'Continue' }).click()

    // Step 3: purpose — a simple 3-way choice, not free text.
    await expect(page.getByRole('heading', { name: "What's this project for?" })).toBeVisible()
    await page.getByRole('button', { name: /A startup/ }).click()

    // Step 4: idea chat — opening message, then a streamed turn.
    await expect(page.getByRole('heading', { name: 'Tell us about your idea' })).toBeVisible()
    await expect(page.getByText('what are you building?')).toBeVisible()
    await page.getByLabel('Your message').fill('A roadmap AI for founders')
    await page.getByRole('button', { name: 'Send' }).click()
    await expect(page.getByText('Sounds great! Who is it for?')).toBeVisible()
    await expect(page.getByText('A roadmap AI for founders')).toBeVisible()

    // User override: finish the interview.
    await page.getByRole('button', { name: "That's enough — finish up" }).click()

    // Step 4: done.
    await expect(page.getByRole('heading', { name: "You're all set" })).toBeVisible()
  })

  test('surfaces a GitHub OAuth error redirect', async ({ page }) => {
    await page.route('**/api/onboarding/v2/state', route =>
      route.fulfill({ status: 200, body: JSON.stringify(makeState('github_connect')) }),
    )
    await page.goto('/onboarding/v2?github=error&reason=token_exchange_failed')
    await expect(page.getByRole('alert')).toContainText('token_exchange_failed')
  })
})
