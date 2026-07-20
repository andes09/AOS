// Streaming chat with Groq to add project detail (roadmap refine-chat).
// Loads the transcript on first open, then streams each reply token-by-token
// over SSE from POST /api/roadmap/chat/message. When the brief changes, the
// planner's readiness badge is refreshed via the ['roadmap-status'] query.

import { useCallback, useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useAuth } from '@clerk/clerk-react'
import type { ProjectChatMessage } from '../../types/roadmap'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export function useProjectChat(open: boolean) {
  const { getToken } = useAuth()
  const qc = useQueryClient()
  const [messages, setMessages] = useState<ProjectChatMessage[]>([])
  const [streamingReply, setStreamingReply] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const loadedRef = useRef(false)

  useEffect(() => {
    if (!open || loadedRef.current) return
    loadedRef.current = true
    setIsLoading(true)
    ;(async () => {
      try {
        const token = await getToken()
        const res = await fetch(`${API_URL}/api/roadmap/chat`, {
          headers: { Authorization: `Bearer ${token}` },
        })
        if (!res.ok) throw new Error('Failed to load chat')
        const data = await res.json()
        setMessages(data.messages ?? [])
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
      } finally {
        setIsLoading(false)
      }
    })()
  }, [open, getToken])

  const send = useCallback(
    async (content: string) => {
      if (isStreaming) return
      setError(null)
      setIsStreaming(true)
      setStreamingReply('')

      const userMsg: ProjectChatMessage = {
        id: `local-${Date.now()}`,
        role: 'user',
        content,
        createdAt: new Date().toISOString(),
      }
      setMessages(prev => [...prev, userMsg])

      try {
        const token = await getToken()
        const res = await fetch(`${API_URL}/api/roadmap/chat/message`, {
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
            if (ev === 'token') replyText += (data as { text: string }).text
            else if (ev === 'error') streamError = (data as { message?: string }).message ?? 'Chat failed'
            if (ev === 'token') setStreamingReply(replyText)
          }
        }

        if (streamError) throw new Error(streamError)
        setMessages(prev => [
          ...prev,
          { id: `asst-${Date.now()}`, role: 'assistant', content: replyText, createdAt: new Date().toISOString() },
        ])
        // The brief may have grown → refresh the planner's readiness badge.
        qc.invalidateQueries({ queryKey: ['roadmap-status'] })
      } catch (e) {
        // Roll back the optimistic user message so they can retry.
        setMessages(prev => prev.filter(m => m.id !== userMsg.id))
        setError(e instanceof Error ? e.message : String(e))
      } finally {
        setStreamingReply('')
        setIsStreaming(false)
      }
    },
    [getToken, isStreaming, qc],
  )

  return { messages, streamingReply, isStreaming, isLoading, error, send }
}
