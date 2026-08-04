import { useAuth } from '@clerk/clerk-react'
import { logger } from './logger'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export class ApiError extends Error {
  status: number
  /** The server's X-Request-ID, when present — ties this to the backend logs. */
  requestId?: string
  constructor(message: string, status: number, requestId?: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.requestId = requestId
  }
}

export function useApi() {
  const { getToken } = useAuth()

  async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const method = options.method ?? 'GET'
    const token = await getToken()
    if (!token) {
      logger.warn('API call attempted with no auth token', { path, method })
      throw new Error('Not authenticated')
    }

    let response: Response
    try {
      response = await fetch(`${API_URL}${path}`, {
        ...options,
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
          ...options.headers,
        },
      })
    } catch (err) {
      // Network-level failure (offline, DNS, server down, CORS preflight).
      // Previously this propagated as a bare TypeError with no context.
      logger.error('Network request failed', err, { path, method, apiUrl: API_URL })
      throw new ApiError('Could not reach the server. Check your connection.', 0)
    }

    const requestId = response.headers.get('X-Request-ID') ?? undefined

    if (!response.ok) {
      const error = await response.json().catch(() => ({}))
      const detail = (error as { detail?: unknown }).detail
      const message = Array.isArray(detail)
        ? detail.map((e: { msg?: string }) => e.msg ?? JSON.stringify(e)).join(', ')
        : (typeof detail === 'string' ? detail : null) ?? `API error ${response.status}`

      const apiError = new ApiError(message, response.status, requestId)
      // 5xx is a real defect; 4xx is usually expected control flow (401 before
      // sign-in, 404 for a missing record) and would be noise at error level.
      if (response.status >= 500) {
        logger.error('API request failed', apiError, { path, method, status: response.status, requestId })
      } else {
        logger.warn('API request rejected', { path, method, status: response.status, message, requestId })
      }
      throw apiError
    }

    try {
      return (await response.json()) as T
    } catch (err) {
      // A 2xx whose body isn't valid JSON means the contract is broken.
      logger.error('API returned unparseable JSON', err, { path, method, status: response.status, requestId })
      throw new ApiError('The server returned an unexpected response.', response.status, requestId)
    }
  }

  return {
    get: <T>(path: string) => request<T>(path),
    post: <T>(path: string, body: unknown) => request<T>(path, { method: 'POST', body: JSON.stringify(body) }),
    patch: <T>(path: string, body?: unknown) => request<T>(path, { method: 'PATCH', body: body ? JSON.stringify(body) : undefined }),
    put: <T>(path: string, body?: unknown) => request<T>(path, { method: 'PUT', body: body ? JSON.stringify(body) : undefined }),
    del: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
  }
}
