import { test, expect } from '@playwright/test'

/**
 * Smoke test of the onboarding → roadmap hand-off: finish onboarding v2 at
 * the done step, land on /app/roadmap (the /app index route), generate a
 * roadmap, and toggle a task's status.
 *
 * Requires VITE_TEST_MODE=true: App.tsx skips the Clerk/org gates on both
 * /onboarding and /app, and the headless clients use a dummy bearer token, so
 * every API route here is intercepted with canned responses.
 */

// Onboarding state parked at the final step — the DoneStep renders from this.
const DONE_STATE = {
  currentStep: 'done',
  steps: [
    { id: 'github_connect', status: 'complete', skippable: true },
    { id: 'profile', status: 'complete', skippable: false },
    { id: 'purpose', status: 'complete', skippable: false },
    { id: 'idea_chat', status: 'complete', skippable: false },
  ],
  github: { connected: false, login: null, skipped: true },
  profile: { name: 'Ada Lovelace', phone: '+1 555 123 4567', complete: true },
  purpose: { value: 'startup', complete: true },
  ideaChat: {
    sessionId: 'sess-1',
    status: 'completed',
    messageCount: 4,
    brief: { projectName: 'Roadmapper' },
    briefComplete: true,
  },
  onboardingCompleted: false,
}

const PROJECT = {
  id: 'p-1',
  name: 'Roadmapper',
  summary: 'A roadmap AI for founders',
  purpose: 'startup',
  milestones: [
    {
      id: 'ms-1',
      title: 'Foundation',
      description: 'Ship the walking skeleton',
      sortOrder: 0,
      tasks: [
        {
          id: 't-1',
          title: 'Set up the repo',
          description: null,
          status: 'todo',
          sortOrder: 0,
          scheduledDate: '2026-07-20',
        },
        {
          id: 't-2',
          title: 'Deploy hello world',
          description: null,
          status: 'todo',
          sortOrder: 1,
          scheduledDate: null,
        },
      ],
    },
    {
      id: 'ms-2',
      title: 'MVP',
      description: null,
      sortOrder: 1,
      tasks: [
        {
          id: 't-3',
          title: 'First real feature',
          description: null,
          status: 'todo',
          sortOrder: 0,
          scheduledDate: null,
        },
      ],
    },
  ],
}

test.describe('Roadmap landing', () => {
  test('completes onboarding, lands on the roadmap, generates, toggles a task', async ({
    page,
  }) => {
    // No roadmap exists until POST /generate is called.
    let roadmap: typeof PROJECT | null = null

    await page.route('**/api/onboarding/v2/state', route =>
      route.fulfill({ status: 200, body: JSON.stringify(DONE_STATE) }),
    )
    await page.route('**/api/onboarding/v2/complete', route =>
      route.fulfill({ status: 200, body: JSON.stringify({ completedAt: new Date().toISOString() }) }),
    )
    await page.route('**/api/roadmap', route =>
      route.fulfill({ status: 200, body: JSON.stringify(roadmap) }),
    )
    await page.route('**/api/roadmap/generate', route => {
      roadmap = PROJECT
      return route.fulfill({ status: 200, body: JSON.stringify(roadmap) })
    })
    await page.route('**/api/roadmap/tasks/*', route => {
      const patch = route.request().postDataJSON() as { status?: string }
      const taskId = route.request().url().split('/').pop()
      const task = PROJECT.milestones.flatMap(m => m.tasks).find(t => t.id === taskId)
      return route.fulfill({ status: 200, body: JSON.stringify({ ...task, ...patch }) })
    })

    // Finish onboarding at the done step and follow the hand-off into the app.
    await page.goto('/onboarding/v2')
    await expect(page.getByRole('heading', { name: "You're all set" })).toBeVisible()
    await page.getByRole('button', { name: /Go to your project/ }).click()

    // The /app index route lands on the roadmap, which is empty pre-generate.
    await expect(page).toHaveURL(/\/app\/roadmap$/)
    await expect(page.getByRole('heading', { name: 'No roadmap yet' })).toBeVisible()

    // Generate → the milestone/task tree renders.
    await page.getByRole('button', { name: 'Generate roadmap' }).click()
    await expect(page.getByRole('heading', { name: 'Roadmapper' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Foundation' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'MVP' })).toBeVisible()
    await expect(page.getByText('Set up the repo')).toBeVisible()

    // Toggle a task: todo → in_progress.
    await page.getByRole('button', { name: 'Set up the repo: todo' }).click()
    await expect(page.getByRole('button', { name: 'Set up the repo: in_progress' })).toBeVisible()
  })
})
