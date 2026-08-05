import { test, expect } from '@playwright/test'

/**
 * E2e walk of the onboarding v2 flow (profile → purpose → idea chat →
 * GitHub+repo → done) against the reference UI at /onboarding/v2.
 *
 * Requires VITE_TEST_MODE=true: App.tsx skips <SignedIn> and the headless
 * client uses a dummy bearer token, so every API route here is intercepted
 * with canned responses — including the SSE chat stream.
 */

type StepStatus = 'complete' | 'current' | 'pending'

function makeState(current: 'profile' | 'purpose' | 'idea_chat' | 'github_repo' | 'done') {
  const order = ['profile', 'purpose', 'idea_chat', 'github_repo'] as const
  const currentIdx = current === 'done' ? order.length : order.indexOf(current)
  const status = (i: number): StepStatus =>
    i < currentIdx ? 'complete' : i === currentIdx ? 'current' : 'pending'
  return {
    currentStep: current,
    steps: order.map((id, i) => ({ id, status: status(i), skippable: id === 'github_repo' })),
    // GitHub is only skipped once the walk reaches (and skips) github_repo,
    // the last tracked step here — i.e. only once we're at 'done'.
    github: {
      connected: false, login: null, skipped: currentIdx > 3,
      needsReconnect: false, needsSetup: currentIdx > 3,
    },
    profile:
      currentIdx > 0
        ? { name: 'Ada Lovelace', phone: '+1 555 123 4567', complete: true }
        : { name: null, phone: null, complete: false },
    purpose:
      currentIdx > 1
        ? { value: 'startup', complete: true }
        : { value: null, complete: false },
    ideaChat: {
      sessionId: currentIdx > 2 ? 'sess-1' : null,
      status: currentIdx > 2 ? 'completed' : 'not_started',
      messageCount: 0,
      brief: null,
      briefComplete: false,
    },
    onboardingPath: currentIdx > 1 ? 'chat' : null,
    // GithubRepoStep/RepoSelectStep read these unconditionally once
    // currentStep is 'github_repo', so every state needs them even though
    // this walk never leaves phase A (GitHub not connected).
    repo: { selected: null, skipped: false, available: false, canCreate: false, ownerLogin: null },
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
  test('walks profile → purpose → idea chat → "I don\'t have GitHub yet" → done', async ({ page }) => {
    // GET /state serves whatever step the flow has reached; mutations advance it.
    let state = makeState('profile')

    await page.route('**/api/onboarding/v2/state', route =>
      route.fulfill({ status: 200, body: JSON.stringify(state) }),
    )
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
      state = makeState('github_repo')
      return route.fulfill({ status: 200, body: JSON.stringify(state) })
    })
    await page.route('**/api/onboarding/v2/github/needs-setup', route => {
      state = makeState('done')
      return route.fulfill({ status: 200, body: JSON.stringify(state) })
    })
    await page.route('**/api/onboarding/v2/complete', route =>
      route.fulfill({ status: 200, body: JSON.stringify({ completedAt: new Date().toISOString() }) }),
    )

    await page.goto('/onboarding/v2')

    // Step 1: profile.
    await expect(page.getByRole('heading', { name: 'Tell us who you are' })).toBeVisible()
    await page.getByLabel('Name').fill('Ada Lovelace')
    await page.getByLabel('Phone').fill('+1 555 123 4567')
    await page.getByRole('button', { name: 'Continue' }).click()

    // Step 2: purpose — a simple 3-way choice, not free text.
    await expect(page.getByRole('heading', { name: "What's this project for?" })).toBeVisible()
    // The options are a radiogroup, not plain buttons (see PurposeStep).
    await page.getByRole('radio', { name: /A startup/ }).click()

    // Step 3: idea chat — opening message, then a streamed turn.
    await expect(page.getByRole('heading', { name: 'Tell us about your idea' })).toBeVisible()
    await expect(page.getByText('what are you building?')).toBeVisible()
    await page.getByLabel('Your message').fill('A roadmap AI for founders')
    await page.getByRole('button', { name: 'Send' }).click()
    await expect(page.getByText('Sounds great! Who is it for?')).toBeVisible()
    await expect(page.getByText('A roadmap AI for founders')).toBeVisible()

    // User override: finish the interview.
    await page.getByRole('button', { name: "That's enough — finish up" }).click()

    // Step 4: GitHub + repo (merged step, phase A since GitHub isn't
    // connected). The beginner's way out — which also gets a GitHub setup
    // milestone prepended to the plan (see services/github_setup_plan).
    await expect(page.getByRole('heading', { name: 'Connect your GitHub' })).toBeVisible()
    await page.getByRole('button', { name: "I don't have GitHub yet" }).click()

    // No "you're all set" interstitial — the last step finishes onboarding
    // and drops the founder straight into the app.
    await expect(page).toHaveURL(/\/app$/)
  })

  test('tech_stack step: picking known tools advances to build_plan', async ({ page }) => {
    let state: Record<string, unknown> = {
      currentStep: 'tech_stack',
      steps: [
        { id: 'profile', status: 'complete', skippable: false },
        { id: 'purpose', status: 'complete', skippable: false },
        { id: 'tech_stack', status: 'current', skippable: false },
        { id: 'build_plan', status: 'pending', skippable: false },
        { id: 'github_repo', status: 'complete', skippable: true },
      ],
      github: { connected: false, login: null, skipped: true },
      profile: { name: 'Ada Lovelace', phone: '+1 555 123 4567', complete: true },
      purpose: { value: 'startup', complete: true },
      techStack: { stack: [], experience: null, complete: false },
      ideaChat: { sessionId: null, status: 'not_started', messageCount: 0, brief: null, briefComplete: false },
      onboardingPath: null,
      importArtifact: null,
      repo: { selected: null, skipped: false, available: false },
      onboardingCompleted: false,
    }

    await page.route('**/api/onboarding/v2/state', route =>
      route.fulfill({ status: 200, body: JSON.stringify(state) }),
    )

    let putBody: unknown = null
    await page.route('**/api/onboarding/v2/tech-stack', route => {
      putBody = route.request().postDataJSON()
      state = {
        ...state,
        currentStep: 'build_plan',
        techStack: { stack: putBody.stack, experience: putBody.experience, complete: true },
      }
      return route.fulfill({ status: 200, body: JSON.stringify(state) })
    })

    await page.goto('/onboarding/v2')

    await expect(page.getByRole('heading', { name: 'What do you already know?' })).toBeVisible()
    await page.getByRole('button', { name: 'React', exact: true }).click()
    await page.getByRole('button', { name: 'Node.js', exact: true }).click()
    await page.getByRole('button', { name: /Continue/ }).click()

    await expect.poll(() => putBody).toEqual({ stack: ['React', 'Node.js'], experience: 'experienced' })
  })

  test('tech_stack step: "I\'m new" is mutually exclusive with picked tools', async ({ page }) => {
    const state = {
      currentStep: 'tech_stack',
      steps: [{ id: 'tech_stack', status: 'current', skippable: false }],
      github: { connected: false, login: null, skipped: true },
      profile: { name: 'Ada Lovelace', phone: '+1 555 123 4567', complete: true },
      purpose: { value: 'learning', complete: true },
      techStack: { stack: [], experience: null, complete: false },
      ideaChat: { sessionId: null, status: 'not_started', messageCount: 0, brief: null, briefComplete: false },
      onboardingPath: null,
      importArtifact: null,
      repo: { selected: null, skipped: false, available: false },
      onboardingCompleted: false,
    }
    await page.route('**/api/onboarding/v2/state', route =>
      route.fulfill({ status: 200, body: JSON.stringify(state) }),
    )
    let putBody: unknown = null
    await page.route('**/api/onboarding/v2/tech-stack', route => {
      putBody = route.request().postDataJSON()
      return route.fulfill({ status: 200, body: JSON.stringify(state) })
    })

    await page.goto('/onboarding/v2')
    await expect(page.getByRole('heading', { name: 'What do you already know?' })).toBeVisible()

    // Pick a chip, then flip to "I'm new" — the chip selection must clear.
    await page.getByRole('button', { name: 'React', exact: true }).click()
    await page.getByRole('radio', { name: /None of these/ }).click()
    await page.getByRole('button', { name: /Continue/ }).click()
    await expect.poll(() => putBody).toEqual({ stack: [], experience: 'new' })

    // Picking a chip afterwards should clear "I'm new" back off.
    await expect(page.getByRole('radio', { name: /None of these/ })).toHaveAttribute('aria-checked', 'true')
    await page.getByRole('button', { name: 'Vue', exact: true }).click()
    await expect(page.getByRole('radio', { name: /None of these/ })).toHaveAttribute('aria-checked', 'false')
  })

  test('surfaces a GitHub OAuth error redirect', async ({ page }) => {
    await page.route('**/api/onboarding/v2/state', route =>
      route.fulfill({ status: 200, body: JSON.stringify(makeState('github_repo')) }),
    )
    await page.goto('/onboarding/v2?github=error&reason=token_exchange_failed')
    await expect(page.getByRole('alert')).toContainText('token_exchange_failed')
  })

  test('a legacy connection needing reconnect keeps the plain skip', async ({ page }) => {
    // Someone with an old connection demonstrably has GitHub — offering them
    // a beginner setup milestone would be wrong, so they get "Skip for now".
    const state = {
      ...makeState('github_repo'),
      github: { connected: true, login: 'octocat', skipped: false, needsReconnect: true, needsSetup: false },
    }
    await page.route('**/api/onboarding/v2/state', route =>
      route.fulfill({ status: 200, body: JSON.stringify(state) }),
    )
    await page.goto('/onboarding/v2')

    await expect(page.getByRole('heading', { name: 'Reconnect your GitHub' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Skip for now' })).toBeVisible()
    await expect(page.getByRole('button', { name: "I don't have GitHub yet" })).toHaveCount(0)
  })
})
