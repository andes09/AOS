/**
 * Catches render-phase crashes.
 *
 * Without a boundary anywhere in the tree, React 18 unmounts the whole app on
 * a render error — the user gets a white screen and we get no report at all.
 * This logs the error with its component stack and shows something recoverable.
 */
import { Component, type ErrorInfo, type ReactNode } from 'react'
import { logger } from '../lib/logger'

interface Props {
  children: ReactNode
  /** Shown instead of the default panel. Receives a reset callback. */
  fallback?: (error: Error, reset: () => void) => ReactNode
  /** Label for the logs, so we can tell which boundary tripped. */
  boundaryName?: string
}

interface State {
  error: Error | null
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    logger.error('React render error', error, {
      boundary: this.props.boundaryName ?? 'root',
      componentStack: info.componentStack,
      url: window.location.pathname,
    })
  }

  reset = () => this.setState({ error: null })

  render() {
    const { error } = this.state
    if (!error) return this.props.children
    if (this.props.fallback) return this.props.fallback(error, this.reset)

    return (
      <div role="alert" style={{ padding: '2rem', maxWidth: 640, margin: '0 auto' }}>
        <h2 style={{ marginBottom: '0.5rem' }}>Something went wrong</h2>
        <p style={{ opacity: 0.8, marginBottom: '1rem' }}>
          This has been reported. Try again, or reload the page if it keeps happening.
        </p>
        {import.meta.env.DEV && (
          <pre
            style={{
              whiteSpace: 'pre-wrap',
              fontSize: 12,
              opacity: 0.7,
              overflowX: 'auto',
              marginBottom: '1rem',
            }}
          >
            {error.name}: {error.message}
          </pre>
        )}
        <button onClick={this.reset}>Try again</button>
      </div>
    )
  }
}
