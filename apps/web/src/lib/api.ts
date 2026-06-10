import { useAuth } from '@clerk/clerk-react'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

export function useApi() {
  const { getToken } = useAuth()

  async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const token = await getToken()
    if (!token) throw new Error('Not authenticated')
    const response = await fetch(`${API_URL}${path}`, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
        ...options.headers,
      },
    })
    if (!response.ok) {
      const error = await response.json().catch(() => ({}))
      const detail = (error as { detail?: unknown }).detail
      const message = Array.isArray(detail)
        ? detail.map((e: { msg?: string }) => e.msg ?? JSON.stringify(e)).join(', ')
        : (typeof detail === 'string' ? detail : null) ?? `API error ${response.status}`
      throw new ApiError(message, response.status)
    }
    return response.json() as Promise<T>
  }

  return {
    get: <T>(path: string) => request<T>(path),
    post: <T>(path: string, body: unknown) => request<T>(path, { method: 'POST', body: JSON.stringify(body) }),
    patch: <T>(path: string, body?: unknown) => request<T>(path, { method: 'PATCH', body: body ? JSON.stringify(body) : undefined }),
    put: <T>(path: string, body?: unknown) => request<T>(path, { method: 'PUT', body: body ? JSON.stringify(body) : undefined }),
    del: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
  }
}
