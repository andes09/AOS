// Theme must be applied before React renders to prevent flash of wrong theme.
// This runs synchronously, before the React tree mounts.
;(function () {
  try {
    // Dark-first: default to dark unless the user has explicitly toggled.
    const stored = localStorage.getItem('aos_theme_v2')
    const theme = stored === 'dark' || stored === 'light' ? stored : 'dark'
    document.documentElement.setAttribute('data-theme', theme)
  } catch {
    document.documentElement.setAttribute('data-theme', 'dark')
  }
})()

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { ClerkProvider } from '@clerk/clerk-react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter } from 'react-router-dom'
import { QueryCache, MutationCache } from '@tanstack/react-query'
import App from './App'
import './index.css'
import { ApiError } from './lib/api'
import { ErrorBoundary } from './components/ErrorBoundary'
import { installGlobalErrorHandlers, logger } from './lib/logger'
import * as Sentry from '@sentry/react'

const sentryDsn = import.meta.env.VITE_SENTRY_DSN
if (sentryDsn) {
  Sentry.init({ dsn: sentryDsn, integrations: [Sentry.browserTracingIntegration()] })
} else if (import.meta.env.PROD) {
  console.warn('[warn] VITE_SENTRY_DSN is not set — front-end errors are not being reported')
}

installGlobalErrorHandlers()

const queryClient = new QueryClient({
  // React Query swallows failures into per-hook `error` state. Plenty of call
  // sites never render that, so a failed query showed as a permanently empty
  // panel. These caches give every failure exactly one central report.
  queryCache: new QueryCache({
    onError: (error, query) => {
      logger.error('Query failed', error, { queryKey: JSON.stringify(query.queryKey) })
    },
  }),
  mutationCache: new MutationCache({
    onError: (error, _vars, _ctx, mutation) => {
      logger.error('Mutation failed', error, { mutationKey: JSON.stringify(mutation.options.mutationKey) })
    },
  }),
  defaultOptions: {
    queries: {
      retry: (_, error) => !(error instanceof ApiError && error.status >= 400 && error.status < 500),
    },
  },
})
const PUBLISHABLE_KEY = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY
if (!PUBLISHABLE_KEY) {
  logger.error('VITE_CLERK_PUBLISHABLE_KEY is missing — authentication will not work')
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {/* Outermost boundary: without one, any render error unmounts the whole
        app and leaves a white screen with nothing reported. */}
    <ErrorBoundary boundaryName="root">
      <ClerkProvider publishableKey={PUBLISHABLE_KEY}>
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>
            <ErrorBoundary boundaryName="app">
              <App />
            </ErrorBoundary>
          </BrowserRouter>
        </QueryClientProvider>
      </ClerkProvider>
    </ErrorBoundary>
  </StrictMode>
)
