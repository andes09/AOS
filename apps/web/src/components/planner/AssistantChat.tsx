import { CSSProperties, useEffect, useRef, useState } from 'react'
import { MessageCircleQuestion, Send, Sparkles, X } from 'lucide-react'
import { IconButton } from '../ui/IconButton'
import { useProjectChat } from '../../pages/planner/useProjectChat'

interface AssistantChatProps {
  /** Rebuild the plan from the refined brief. Destructive — see the footer note. */
  onRegenerate: () => void
  isRegenerating: boolean
  regenerateError: string | null
}

/**
 * A "clear" floating question-mark button (TikTok-Tako style) that opens a
 * conversation with the Groq-backed planning assistant. Users describe more
 * about their project; the assistant folds it into the brief, and a "Rebuild
 * plan" action regenerates the roadmap from the enriched brief.
 *
 * The chat plumbing is the existing `useProjectChat` hook (SSE streaming from
 * POST /api/roadmap/chat/message); this component is purely the surface.
 */
export function AssistantChat({ onRegenerate, isRegenerating, regenerateError }: AssistantChatProps) {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState('')
  const { messages, streamingReply, isStreaming, isLoading, error, send } = useProjectChat(open)

  const scrollRef = useRef<HTMLDivElement>(null)
  // Pin to the newest message as the conversation grows and the reply streams.
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight })
  }, [messages, streamingReply, isLoading])

  const submit = () => {
    const text = draft.trim()
    if (!text || isStreaming) return
    send(text)
    setDraft('')
  }

  return (
    <>
      {/* The clear FAB. Translucent so the planner shows through, matching the
          "clear button" brief. color-mix keeps it theme-aware automatically. */}
      <button
        className="pl-fab"
        aria-label={open ? 'Close plan assistant' : 'Ask the plan assistant'}
        aria-expanded={open}
        onClick={() => setOpen(o => !o)}
        style={fabStyle}
      >
        {open ? <X size={22} /> : <MessageCircleQuestion size={24} />}
      </button>

      {open && (
        <section className="pl-assistant-panel" role="dialog" aria-label="Plan assistant" style={panelStyle}>
          <header style={headerStyle}>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 'var(--text-sm)', fontWeight: 700, color: 'var(--color-text-primary)' }}>
                Refine your plan
              </div>
              <div style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-muted)' }}>
                Tell the AI more, then rebuild
              </div>
            </div>
            <IconButton label="Close" onClick={() => setOpen(false)}>
              <X size={16} />
            </IconButton>
          </header>

          <div ref={scrollRef} style={bodyStyle}>
            {isLoading && <Muted>Loading your conversation…</Muted>}
            {!isLoading && messages.length === 0 && (
              <Muted>
                Add anything the plan is missing — goals, tech stack, constraints, deadlines. The more
                detail, the sharper the rebuilt plan.
              </Muted>
            )}
            {messages.map(m => (
              <Bubble key={m.id} role={m.role}>
                {m.content}
              </Bubble>
            ))}
            {isStreaming && (
              <Bubble role="assistant">
                {streamingReply || <span style={{ color: 'var(--color-text-muted)' }}>Thinking…</span>}
              </Bubble>
            )}
            {error && (
              <div style={{ fontSize: 'var(--text-xs)', color: 'var(--color-danger)', padding: '4px 2px' }}>
                {error}
              </div>
            )}
          </div>

          <div style={footerStyle}>
            <div style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'flex-end' }}>
              <textarea
                value={draft}
                onChange={e => setDraft(e.target.value)}
                onKeyDown={e => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    submit()
                  }
                }}
                placeholder="Add more detail…"
                rows={2}
                disabled={isStreaming}
                style={textareaStyle}
              />
              <IconButton
                label="Send"
                onClick={submit}
                disabled={!draft.trim() || isStreaming}
                style={{ background: 'var(--color-accent)', color: '#fff', width: 32, height: 32 }}
              >
                <Send size={15} />
              </IconButton>
            </div>

            <button
              onClick={onRegenerate}
              disabled={isRegenerating}
              style={rebuildBtnStyle}
              title="Replans milestones and tasks from the updated brief"
            >
              <Sparkles size={14} />
              {isRegenerating ? 'Rebuilding your plan…' : 'Rebuild plan with this info'}
            </button>
            {regenerateError ? (
              <div style={{ fontSize: 10, color: 'var(--color-danger)', textAlign: 'center' }}>{regenerateError}</div>
            ) : (
              <div style={{ fontSize: 10, color: 'var(--color-text-muted)', textAlign: 'center' }}>
                Rebuilding replaces the current tasks and their assignments.
              </div>
            )}
          </div>
        </section>
      )}
    </>
  )
}

function Bubble({ role, children }: { role: 'user' | 'assistant'; children: React.ReactNode }) {
  const isUser = role === 'user'
  return (
    <div style={{ display: 'flex', justifyContent: isUser ? 'flex-end' : 'flex-start' }}>
      <div
        style={{
          maxWidth: '85%',
          padding: '7px 10px',
          borderRadius: 'var(--radius-lg)',
          fontSize: 'var(--text-sm)',
          lineHeight: 1.45,
          whiteSpace: 'pre-wrap',
          overflowWrap: 'anywhere',
          background: isUser ? 'var(--color-accent)' : 'var(--color-bg-secondary)',
          color: isUser ? '#fff' : 'var(--color-text-primary)',
          border: isUser ? 'none' : '1px solid var(--color-border-subtle)',
        }}
      >
        {children}
      </div>
    </div>
  )
}

function Muted({ children }: { children: React.ReactNode }) {
  return (
    <p style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-muted)', lineHeight: 1.5, margin: 0, padding: '4px 2px' }}>
      {children}
    </p>
  )
}

const fabStyle: CSSProperties = {
  position: 'fixed',
  right: 24,
  bottom: 24,
  zIndex: 'var(--z-dropdown)' as never,
  width: 52,
  height: 52,
  borderRadius: '50%',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  cursor: 'pointer',
  color: 'var(--color-accent)',
  background: 'color-mix(in srgb, var(--color-bg-elevated) 62%, transparent)',
  border: '1px solid color-mix(in srgb, var(--color-border-strong) 70%, transparent)',
  backdropFilter: 'blur(10px)',
  WebkitBackdropFilter: 'blur(10px)',
  boxShadow: 'var(--shadow-sm)',
}

const panelStyle: CSSProperties = {
  position: 'fixed',
  right: 24,
  bottom: 88,
  zIndex: 'var(--z-dropdown)' as never,
  width: 'min(380px, calc(100vw - 32px))',
  height: 'min(520px, calc(100vh - 140px))',
  display: 'flex',
  flexDirection: 'column',
  borderRadius: 'var(--radius-lg)',
  background: 'var(--color-bg-elevated)',
  border: '1px solid var(--color-border)',
  boxShadow: 'var(--shadow-md)',
  overflow: 'hidden',
  fontFamily: 'var(--font-sans)',
}

const headerStyle: CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  gap: 'var(--space-2)',
  padding: '10px 12px',
  borderBottom: '1px solid var(--color-border-subtle)',
  flexShrink: 0,
}

const bodyStyle: CSSProperties = {
  flex: 1,
  minHeight: 0,
  overflowY: 'auto',
  display: 'flex',
  flexDirection: 'column',
  gap: 'var(--space-2)',
  padding: 'var(--space-3)',
}

const footerStyle: CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 6,
  padding: 'var(--space-2) var(--space-3) var(--space-3)',
  borderTop: '1px solid var(--color-border-subtle)',
  flexShrink: 0,
}

const textareaStyle: CSSProperties = {
  flex: 1,
  resize: 'none',
  padding: '7px 9px',
  borderRadius: 'var(--radius-md)',
  border: '1px solid var(--color-border)',
  background: 'var(--color-bg-primary)',
  color: 'var(--color-text-primary)',
  fontFamily: 'var(--font-sans)',
  fontSize: 'var(--text-sm)',
  lineHeight: 1.4,
}

const rebuildBtnStyle: CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  gap: 6,
  width: '100%',
  height: 30,
  borderRadius: 'var(--radius-md)',
  cursor: 'pointer',
  border: '1px solid var(--color-border)',
  background: 'var(--color-bg-secondary)',
  color: 'var(--color-text-primary)',
  fontFamily: 'var(--font-sans)',
  fontSize: 'var(--text-xs)',
  fontWeight: 'var(--font-weight-medium)' as CSSProperties['fontWeight'],
}
