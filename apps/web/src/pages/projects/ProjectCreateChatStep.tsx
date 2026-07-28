// The project-creation chat: a leaner version of onboarding-v2's IdeaChatStep,
// wired to the session-scoped /api/projects/sessions/{id}/chat endpoints
// instead of the org-wide /api/onboarding/v2 ones — see useProjectCreationChat.

import { useEffect, useRef, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Input } from '../../components/ui/Input'
import { Alert } from '../../components/ui/Alert'
import { Spinner } from '../../components/ui/Spinner'
import { useProjectCreationChat } from '../../features/projects/hooks/useProjectCreationChat'

export function ProjectCreateChatStep({
  sessionId,
  onGenerate,
}: {
  sessionId: string
  onGenerate: () => void
}) {
  const chat = useProjectCreationChat(sessionId)
  const [draft, setDraft] = useState('')
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [chat.messages.length, chat.streamingReply])

  const submit = () => {
    const content = draft.trim()
    if (!content) return
    setDraft('')
    void chat.send(content)
  }

  if (chat.isLoading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '2rem 0' }}>
        <Spinner /> Starting the interview…
      </div>
    )
  }

  const canGenerate = chat.briefComplete || chat.messages.length > 3

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div>
        <h2 style={{ fontSize: 'var(--text-lg)', fontWeight: 700, margin: 0 }}>Tell us about your idea</h2>
        <p style={{ color: 'var(--color-text-secondary)', fontSize: 'var(--text-sm)' }}>
          Chat through what you're building — we'll turn it into a day-by-day roadmap.
        </p>
      </div>

      <div
        style={{
          border: '1px solid var(--color-border)',
          borderRadius: 'var(--radius-lg)',
          background: 'var(--color-bg-elevated)',
          overflow: 'hidden',
        }}
      >
        <div
          ref={scrollRef}
          style={{ display: 'flex', flexDirection: 'column', gap: 12, padding: 16, maxHeight: 340, minHeight: 160, overflowY: 'auto' }}
        >
          {chat.messages.map(m => (
            <div key={m.id} style={{ display: 'flex', flexDirection: 'column', alignItems: m.role === 'user' ? 'flex-end' : 'flex-start' }}>
              <div
                style={{
                  maxWidth: '86%',
                  padding: '9px 13px',
                  borderRadius: 12,
                  fontSize: 'var(--text-sm)',
                  whiteSpace: 'pre-wrap',
                  color: m.role === 'user' ? '#fff' : 'var(--color-text-primary)',
                  background: m.role === 'user' ? 'var(--color-accent)' : 'var(--color-bg-tertiary)',
                }}
              >
                {m.content}
              </div>
            </div>
          ))}
          {chat.isStreaming && (
            <div style={{ maxWidth: '86%', fontSize: 'var(--text-sm)', color: 'var(--color-text-secondary)' }}>
              {chat.streamingReply}
              <span>▍</span>
            </div>
          )}
        </div>

        {chat.error && (
          <div style={{ padding: '0 16px 12px' }}>
            <Alert variant="danger">{chat.error}</Alert>
          </div>
        )}

        <form
          onSubmit={e => { e.preventDefault(); submit() }}
          style={{ display: 'flex', gap: 8, padding: 12, borderTop: '1px solid var(--color-border-subtle)' }}
        >
          <Input
            aria-label="Your message"
            value={draft}
            onChange={e => setDraft(e.target.value)}
            disabled={chat.isStreaming}
            placeholder="Type your reply…"
            style={{ flex: 1 }}
          />
          <Button type="submit" disabled={chat.isStreaming || !draft.trim()}>
            {chat.isStreaming ? <Spinner size={13} /> : 'Send'}
          </Button>
        </form>
      </div>

      <div>
        <Button variant="primary" disabled={!canGenerate} onClick={onGenerate}>
          That's enough — build my roadmap
        </Button>
      </div>
    </div>
  )
}
