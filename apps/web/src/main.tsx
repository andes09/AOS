// Theme must be applied before React renders to prevent flash of wrong theme.
// This runs synchronously, before the React tree mounts.
;(function () {
  try {
    const stored = localStorage.getItem('aos_theme')
    const theme = stored === 'dark' || stored === 'light' ? stored : 'light'
    document.documentElement.setAttribute('data-theme', theme)
  } catch {
    document.documentElement.setAttribute('data-theme', 'light')
  }
})()

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { ClerkProvider } from '@clerk/clerk-react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import './index.css'
import { ApiError } from './lib/api'
import * as Sentry from '@sentry/react'

const sentryDsn = import.meta.env.VITE_SENTRY_DSN
if (sentryDsn) {
  Sentry.init({ dsn: sentryDsn, integrations: [Sentry.browserTracingIntegration()] })
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (_, error) => !(error instanceof ApiError && error.status >= 400 && error.status < 500),
    },
  },
})
const PUBLISHABLE_KEY = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ClerkProvider publishableKey={PUBLISHABLE_KEY}>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </QueryClientProvider>
    </ClerkProvider>
  </StrictMode>
)
