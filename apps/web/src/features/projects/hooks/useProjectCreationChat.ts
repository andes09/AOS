// Streaming chat for the project-creation flow (POST
// /api/projects/sessions/{id}/chat/message). Mirrors
// pages/planner/useProjectChat.ts's SSE-consuming logic, but session-scoped
// rather than the single org-wide roadmap refine-chat.

import { useCallback, useEffect, useRef, useState } from 'react'
import { useAuth } from '@clerk/clerk-react'
import type { ProjectCreationChatMessage } from '../types'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export function useProjectCreationChat(sessionId: string) {
  const { getToken } = useAuth()
  const [messages, setMessages] = useState<ProjectCreationChatMessage[]>([])
  const [brief, setBrief] = useState<Record<string, unknown> | null>(null)
  const [briefComplete, setBriefComplete] = useState(false)
  const [streamingReply, setStreamingReply] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const loadedRef = useRef<string | null>(null)

  const base = `${API_URL}/api/projects/sessions/${sessionId}`

  useEffect(() => {
    if (loadedRef.current === sessionId) return
    loadedRef.current = sessionId
    setIsLoading(true)
    ;(async () => {
      try {
        const token = await getToken()
        const res = await fetch(`${base}/chat`, {
          headers: { Authorization: `Bearer ${token}` },
        })
        if (!res.ok) throw new Error('Failed to load chat')
        const data = await res.json()
        setMessages(data.messages ?? [])
        setBrief(data.brief ?? null)
        setBriefComplete(Boolean(data.briefComplete))
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
      } finally {
        setIsLoading(false)
      }
    })()
  }, [sessionId, base, getToken])

  const send = useCallback(
    async (content: string) => {
      if (isStreaming) return
      setError(null)
      setIsStreaming(true)
      setStreamingReply('')

      const userMsg: ProjectCreationChatMessage = {
        id: `local-${Date.now()}`,
        role: 'user',
        content,
        createdAt: new Date().toISOString(),
      }
      setMessages(prev => [...prev, userMsg])

      try {
        const token = await getToken()
        const res = await fetch(`${base}/chat/message`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Accept: 'text/event-stream',
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({ content }),
        })
        if (!res.ok || !res.body) {
          const b = await res.json().catch(() => ({}))
          throw new Error((b as { detail?: string }).detail || 'Chat failed')
        }

        const reader = res.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        let replyText = ''
        let streamError: string | null = null

        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          const events = buffer.split('\n\n')
          buffer = events.pop() ?? ''
          for (const evt of events) {
            const lines = evt.split('\n')
            const ev = lines.find(l => l.startsWith('event:'))?.slice(6).trim()
            const dl = lines.find(l => l.startsWith('data:'))?.slice(5).trim()
            if (!ev || !dl) continue
            let data: unknown
            try {
              data = JSON.parse(dl)
            } catch {
              continue
            }
            if (ev === 'token') {
              replyText += (data as { text: string }).text
              setStreamingReply(replyText)
            } else if (ev === 'brief') {
              const b = data as { brief: Record<string, unknown>; briefComplete: boolean }
              setBrief(b.brief)
              setBriefComplete(b.briefComplete)
            } else if (ev === 'error') {
              streamError = (data as { message?: string }).message ?? 'Chat failed'
            }
          }
        }

        if (streamError) throw new Error(streamError)
        setMessages(prev => [
          ...prev,
          { id: `asst-${Date.now()}`, role: 'assistant', content: replyText, createdAt: new Date().toISOString() },
        ])
      } catch (e) {
        // Roll back the optimistic user message so they can retry.
        setMessages(prev => prev.filter(m => m.id !== userMsg.id))
        setError(e instanceof Error ? e.message : String(e))
      } finally {
        setStreamingReply('')
        setIsStreaming(false)
      }
    },
    [base, getToken, isStreaming],
  )

  return { messages, brief, briefComplete, streamingReply, isStreaming, isLoading, error, send }
}
