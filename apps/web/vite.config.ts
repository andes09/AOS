import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  server: {
    port: 5173,
    strictPort: true,  // fail instead of bumping to next port
  },
  plugins: [react()],
  test: {
    // Scoped to src/ on purpose: the Playwright suite in tests/e2e also uses
    // *.spec.ts, and Vitest's default glob would otherwise try to run it.
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
    environment: 'node',
  },
})
