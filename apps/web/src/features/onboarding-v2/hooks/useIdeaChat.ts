import { useCallback, useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import type { ChatMessage, ChatStatus, ProjectBrief } from '../types'
import { ONBOARDING_STATE_KEY } from './useOnboardingState'
import { useOnboardingApi } from './useOnboardingApi'

/**
 * The idea-interview chat. Loads (or starts) the session on mount, exposes the
 * transcript plus the in-flight streamed reply, and keeps the flow state cache
 * in sync when the interview completes.
 *
 * UI contract: render `messages`, then `streamingReply` as a partial assistant
 * bubble while `isStreaming`.
 */
export function useIdeaChat() {
  const api = useOnboardingApi()
  const queryClient = useQueryClient()

  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [status, setStatus] = useState<ChatStatus>('not_started')
  const [brief, setBrief] = useState<ProjectBrief | null>(null)
  const [briefComplete, setBriefComplete] = useState(false)
  const [awaitingConfirmation, setAwaitingConfirmation] = useState(false)
  const [streamingReply, setStreamingReply] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const startedRef = useRef(false)

  useEffect(() => {
    if (startedRef.current) return
    startedRef.current = true
    api
      .startChat()
      .then(payload => {
        setMessages(payload.messages)
        setStatus(payload.status)
        setBrief(payload.brief)
        setBriefComplete(payload.briefComplete)
        setAwaitingConfirmation(payload.awaitingConfirmation)
      })
      .catch(err => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setIsLoading(false))
    return () => abortRef.current?.abort()
  }, [api])

  const invalidateFlowState = useCallback(
    () => queryClient.invalidateQueries({ queryKey: ONBOARDING_STATE_KEY }),
    [queryClient],
  )

  const send = useCallback(
    async (content: string) => {
      if (isStreaming || status === 'completed') return
      setError(null)
      setIsStreaming(true)
      setStreamingReply('')

      // Optimistic local echo of the user message.
      const userMessage: ChatMessage = {
        id: `local-${Date.now()}`,
        role: 'user',
        content,
        createdAt: new Date().toISOString(),
      }
      setMessages(prev => [...prev, userMessage])

      abortRef.current?.abort()
      const controller = new AbortController()
      abortRef.current = controller

      try {
        const result = await api.streamChatMessage(
          content,
          {
            onToken: text => setStreamingReply(prev => prev + text),
            onBrief: d => {
              setBrief(d.brief)
              setBriefComplete(d.briefComplete)
              setAwaitingConfirmation(d.awaitingConfirmation)
            },
          },
          controller.signal,
        )
        setMessages(prev => [
          ...prev,
          {
            id: `assistant-${Date.now()}`,
            role: 'assistant',
            content: result.reply,
            createdAt: new Date().toISOString(),
          },
        ])
        setStatus(result.status)
        if (result.status === 'completed') invalidateFlowState()
      } catch (err) {
        // Roll back the optimistic user message so the user can retry.
        setMessages(prev => prev.filter(m => m.id !== userMessage.id))
        setError(err instanceof Error ? err.message : String(err))
      } finally {
        setStreamingReply('')
        setIsStreaming(false)
      }
    },
    [api, invalidateFlowState, isStreaming, status],
  )

  const complete = useCallback(async () => {
    await api.completeChat()
    setStatus('completed')
    invalidateFlowState()
  }, [api, invalidateFlowState])

  return {
    messages,
    status,
    brief,
    briefComplete,
    awaitingConfirmation,
    streamingReply,
    isStreaming,
    isLoading,
    error,
    send,
    /** User override: end the interview without waiting for the AI to judge it done. */
    complete,
  }
}
