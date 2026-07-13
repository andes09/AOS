import { defineConfig } from '@playwright/test'

// Overridable so local runs can dodge whatever else is on 5174
// (e.g. the LandingPage dev server). CI keeps the default.
const port = Number(process.env.E2E_PORT || 5174)

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 30000,
  use: {
    baseURL: `http://localhost:${port}`,
    headless: true,
  },
  projects: [
    { name: 'chromium', use: { browserName: 'chromium' } },
  ],
  webServer: {
    command: `VITE_TEST_MODE=true pnpm dev --port ${port} --strictPort`,
    url: `http://localhost:${port}`,
    reuseExistingServer: !process.env.CI,
    timeout: 60000,
    env: {
      VITE_TEST_MODE: 'true',
    },
  },
})
