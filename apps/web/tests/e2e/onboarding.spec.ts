import { test, expect } from '@playwright/test'

/**
 * Smoke test for the onboarding flow.
 *
 * Requires VITE_TEST_MODE=true (set in playwright.config.ts env / CI).
 * In test mode, App.tsx skips the <SignedIn> wrapper so the page renders
 * without a real Clerk session. All API routes are intercepted with canned
 * responses so no backend or Atlassian credentials are needed.
 */

test.describe('Onboarding flow', () => {
  test('loads the onboarding page and shows the welcome step', async ({ page }) => {
    await page.route('**/api/integrations/jira/connect', route =>
      route.fulfill({ status: 200, body: JSON.stringify({ auth_url: '/onboarding?connection_id=test-conn-id' }) })
    )
    await page.route('**/api/integrations/jira/projects*', route =>
      route.fulfill({
        status: 200,
        body: JSON.stringify([
          { id: 'p-1', key: 'E2E', name: 'E2E Project', connection_id: 'test-conn-id' },
        ]),
      })
    )
    await page.route('**/api/integrations/jira/boards*', route =>
      route.fulfill({
        status: 200,
        body: JSON.stringify([
          { id: '1', name: 'Team Board', project_key: 'E2E', type: 'scrum', connection_id: 'test-conn-id' },
        ]),
      })
    )
    await page.route('**/api/integrations/jira/board-selection', route =>
      route.fulfill({ status: 200, body: JSON.stringify({ saved: true, team_id: 'test-team-id' }) })
    )
    await page.route('**/api/integrations/jira/sync-status/test-team-id', route =>
      route.fulfill({ status: 200, body: JSON.stringify({ state: 'complete', tickets_synced: 10, members_synced: 3 }) })
    )
    await page.route('**/api/integrations/jira/team-members*', route =>
      route.fulfill({
        status: 200,
        body: JSON.stringify([
          { id: 'dev-1', name: 'Alice', handle: 'alice', jira_account_id: 'jira-alice', issues: 5 },
          { id: 'dev-2', name: 'Bob', handle: 'bob', jira_account_id: 'jira-bob', issues: 3 },
        ]),
      })
    )
    await page.route('**/api/onboarding/confirm-team', route =>
      route.fulfill({ status: 200, body: JSON.stringify({ upserted: 2, completed_at: new Date().toISOString() }) })
    )

    await page.goto('/onboarding')

    // Welcome step should be visible (VITE_TEST_MODE bypasses <SignedIn> wrapper)
    await expect(page.locator('text=Connect Jira')).toBeVisible({ timeout: 10000 })
  })
})
