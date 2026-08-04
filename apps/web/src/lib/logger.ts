/**
 * Front-end logging.
 *
 * The app had no `console.*` calls and no error boundary at all, so a failed
 * fetch or a render crash produced exactly zero signal — a blank panel or a
 * white screen and nothing to go on. Sentry was initialised in main.tsx but
 * only ever saw genuinely uncaught errors.
 *
 * Everything here goes to the console (for local dev and for a user's DevTools)
 * and, when Sentry is configured, to Sentry as a breadcrumb or an exception.
 */
import * as Sentry from '@sentry/react'

type Context = Record<string, unknown>

const isDev = import.meta.env.DEV

function emit(level: 'debug' | 'info' | 'warn' | 'error', msg: string, context?: Context) {
  // Keep debug chatter out of production consoles; warn/error always show.
  if (level === 'debug' && !isDev) return

  const args: unknown[] = [`[${level}] ${msg}`]
  if (context && Object.keys(context).length > 0) args.push(context)

  if (level === 'error') console.error(...args)
  else if (level === 'warn') console.warn(...args)
  else if (level === 'info') console.info(...args)
  else console.debug(...args)

  Sentry.addBreadcrumb({
    category: 'app',
    message: msg,
    level: level === 'warn' ? 'warning' : level,
    data: context,
  })
}

export const logger = {
  debug: (msg: string, context?: Context) => emit('debug', msg, context),
  info: (msg: string, context?: Context) => emit('info', msg, context),
  warn: (msg: string, context?: Context) => emit('warn', msg, context),

  /**
   * Report a genuine failure. Sends the real Error to Sentry (so it keeps its
   * stack trace) rather than a stringified copy.
   */
  error: (msg: string, error?: unknown, context?: Context) => {
    emit('error', msg, { ...context, error: describeError(error) })
    if (error instanceof Error) {
      Sentry.captureException(error, { extra: { message: msg, ...context } })
    } else {
      Sentry.captureMessage(msg, { level: 'error', extra: { error, ...context } })
    }
  },
}

/** Flatten an unknown thrown value into something loggable. */
export function describeError(error: unknown): string {
  if (error instanceof Error) return `${error.name}: ${error.message}`
  if (typeof error === 'string') return error
  if (error === undefined) return 'undefined'
  try {
    return JSON.stringify(error)
  } catch {
    return String(error)
  }
}

/**
 * Catch failures that never reach a React boundary: rejected promises with no
 * `.catch`, and errors thrown outside the render cycle (event handlers,
 * timers). Without this they surface only as a browser console line nobody is
 * watching.
 */
export function installGlobalErrorHandlers() {
  window.addEventListener('unhandledrejection', event => {
    logger.error('Unhandled promise rejection', event.reason, {
      url: window.location.pathname,
    })
  })

  window.addEventListener('error', event => {
    logger.error('Uncaught error', event.error ?? event.message, {
      url: window.location.pathname,
      source: event.filename,
      line: event.lineno,
    })
  })
}
