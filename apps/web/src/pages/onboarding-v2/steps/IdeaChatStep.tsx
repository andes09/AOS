/**
 * Step 4 — the AI idea interview. Renders the transcript plus the in-flight
 * streamed reply, and a live ProjectBrief panel that fills in as the AI
 * extracts structure. The "finish up" override appears after some back-and-forth.
 */
import { useEffect, useRef, useState } from 'react'
import { useIdeaChat } from '../../../features/onboarding-v2'
import type { ProjectBrief } from '../../../features/onboarding-v2'
import { Btn, C, Spinner, WARM } from '../theme'

export function IdeaChatStep() {
  const chat = useIdeaChat()
  const [draft, setDraft] = useState('')
  const [reopening, setReopening] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)

  const disabled = chat.isStreaming || chat.status === 'completed'
  // A session can reach "completed" with nothing usable in the brief (e.g.
  // extraction failed on every turn) — without a way back the founder is
  // stuck with a disabled input and a roadmap that can never draft.
  const stuckEmpty = chat.status === 'completed' && !hasBriefContent(chat.brief)
  // The brief has every required field, or the AI has asked its closing
  // question — either way the founder can move on whenever they like.
  const readyToFinish = chat.briefComplete || chat.awaitingConfirmation

  const reopen = async () => {
    setReopening(true)
    try {
      await chat.reopen()
    } finally {
      setReopening(false)
    }
  }

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
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '32px 0', color: C.t3, fontSize: 14, animation: 'fadeUp 0.22s ease both' }}>
        <Spinner /> Starting the interview…
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18, animation: 'fadeUp 0.22s ease both' }}>
      <div>
        <h2 style={{ fontSize: 21, fontWeight: 700, color: C.t1, letterSpacing: '-0.3px', marginBottom: 5 }}>Tell us about your idea</h2>
        <p style={{ fontSize: 14, color: C.t2, lineHeight: 1.55 }}>Chat through what you're building. We'll turn the conversation into a structured brief on the right.</p>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) 260px', gap: 18, alignItems: 'start' }}>
        {/* Chat column */}
        <div style={{ display: 'flex', flexDirection: 'column', border: `1px solid ${C.border}`, borderRadius: 12, background: C.bg0, overflow: 'hidden' }}>
          <div ref={scrollRef} style={{ display: 'flex', flexDirection: 'column', gap: 12, padding: 16, maxHeight: 340, minHeight: 220, overflowY: 'auto' }}>
            {chat.messages.map(m => <Bubble key={m.id} role={m.role} text={m.content} />)}
            {chat.isStreaming && <Bubble role="assistant" text={chat.streamingReply} busy />}
          </div>

          {chat.error && (
            <div role="alert" style={{ margin: '0 16px 12px', background: C.dangerBg, border: `1px solid ${C.dangerBd}`, borderRadius: 8, padding: '9px 12px', fontSize: 12.5, color: C.danger }}>
              {chat.error}
            </div>
          )}

          {stuckEmpty && (
            <div role="alert" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, margin: '0 16px 12px', background: C.dangerBg, border: `1px solid ${C.dangerBd}`, borderRadius: 8, padding: '9px 12px', fontSize: 12.5, color: C.danger }}>
              <span>This session ended without enough detail to build a plan.</span>
              <Btn variant="outline" size="sm" onClick={() => void reopen()} disabled={reopening}>
                {reopening ? 'Resuming…' : 'Continue the conversation'}
              </Btn>
            </div>
          )}

          <form
            onSubmit={e => { e.preventDefault(); submit() }}
            style={{ display: 'flex', gap: 8, padding: 12, borderTop: `1px solid ${C.borderSubtle}`, background: C.bg1 }}
          >
            <input
              aria-label="Your message"
              value={draft}
              onChange={e => setDraft(e.target.value)}
              disabled={disabled}
              placeholder={chat.status === 'completed' ? 'Interview complete' : 'Type your reply…'}
              style={{ flex: 1, background: C.bg0, border: `1px solid ${C.border}`, borderRadius: 6, padding: '9px 12px', fontSize: 14, color: C.t1, opacity: disabled ? 0.6 : 1 }}
            />
            <Btn type="submit" disabled={disabled || !draft.trim()} style={{ display: 'inline-flex', alignItems: 'center', gap: 7 }}>
              {chat.isStreaming ? <Spinner size={13} color="rgba(255,255,255,0.85)" /> : 'Send'}
            </Btn>
          </form>
        </div>

        {/* Brief panel */}
        <BriefPanel brief={chat.brief} complete={chat.briefComplete} />
      </div>

      {/* Always reachable once there's a usable brief. The AI decides when it
          has enough, but it doesn't get the last word — a model that signs off
          without asking its closing question (or asks one more than the founder
          wants to answer) must never be able to strand the flow on this step.
          The hasBriefContent gate stays: finishing with an empty brief just
          moves the dead end to PlanReviewStep, which can't draft from one. */}
      {chat.status === 'completed' ? (
        !stuckEmpty && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: C.t3, fontSize: 13.5 }}>
            <Spinner /> Interview complete — setting up the next step…
          </div>
        )
      ) : chat.messages.length > 2 && hasBriefContent(chat.brief) && (
        readyToFinish ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <Btn onClick={() => void chat.complete()} disabled={disabled || chat.isCompleting}>
              {chat.isCompleting ? <Spinner size={13} color="rgba(255,255,255,0.85)" /> : 'Looks good — continue →'}
            </Btn>
            <span style={{ fontSize: 12.5, color: C.t3 }}>Your brief has everything we need. Keep chatting to refine it.</span>
          </div>
        ) : (
          <div>
            <Btn variant="outline" size="sm" onClick={() => void chat.complete()} disabled={disabled || chat.isCompleting}>
              That's enough — finish up
            </Btn>
          </div>
        )
      )}
    </div>
  )
}

// Ending the interview early ("finish up") sets the session's status to
// "completed" without any server-side check that a brief actually exists —
// that override is intentional (see useIdeaChat.complete). Gating the button
// here on some real extracted content stops a founder from producing a
// completed session with an empty brief, which /plan/draft can't generate
// from (see PlanReviewStep's "brief_incomplete" case).
function hasBriefContent(brief: ProjectBrief | null): boolean {
  if (!brief) return false
  return Object.values(brief).some(v => (Array.isArray(v) ? v.length > 0 : !!v))
}

function Bubble({ role, text, busy }: { role: 'user' | 'assistant'; text: string; busy?: boolean }) {
  const isUser = role === 'user'
  return (
    <div data-role={role} aria-busy={busy || undefined} style={{ display: 'flex', flexDirection: 'column', alignItems: isUser ? 'flex-end' : 'flex-start' }}>
      <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: '.05em', textTransform: 'uppercase', color: C.t3, marginBottom: 3 }}>{isUser ? 'You' : 'Omada'}</span>
      <div style={{
        maxWidth: '86%', padding: '9px 13px', borderRadius: 12, fontSize: 13.5, lineHeight: 1.5, whiteSpace: 'pre-wrap',
        color: isUser ? '#fff' : C.t1,
        background: isUser ? C.accent : C.bg3,
        borderBottomRightRadius: isUser ? 3 : 12,
        borderBottomLeftRadius: isUser ? 12 : 3,
      }}>
        {text}
        {busy && <span style={{ marginLeft: 3, color: C.t3 }}>▍</span>}
      </div>
    </div>
  )
}

const BRIEF_FIELDS: { key: keyof ProjectBrief; label: string }[] = [
  { key: 'projectName', label: 'Name' },
  { key: 'problemStatement', label: 'Problem' },
  { key: 'targetAudience', label: 'Audience' },
  { key: 'coreFeatures', label: 'Core features' },
  { key: 'scope', label: 'Scope' },
  { key: 'timeline', label: 'Timeline' },
]

function BriefPanel({ brief, complete }: { brief: ProjectBrief | null; complete: boolean }) {
  const fmt = (v: ProjectBrief[keyof ProjectBrief]): string | null => {
    if (v == null) return null
    if (Array.isArray(v)) return v.length ? v.join(', ') : null
    return String(v) || null
  }
  return (
    <aside style={{ border: `1px solid ${C.border}`, borderRadius: 12, background: WARM.surface, padding: 16, position: 'sticky', top: 0 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: '.07em', textTransform: 'uppercase', color: C.t3 }}>Your brief</span>
        {complete && (
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 10.5, fontWeight: 600, color: C.success, background: C.successBg, border: `1px solid ${C.success}`, padding: '2px 7px', borderRadius: 20 }}>
            <svg width="8" height="8" viewBox="0 0 8 8"><path d="M1 4 L3 6 L7 1" stroke={C.success} strokeWidth="1.6" fill="none" strokeLinecap="round" strokeLinejoin="round" /></svg>
            Ready
          </span>
        )}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {BRIEF_FIELDS.map(({ key, label }) => {
          const val = brief ? fmt(brief[key]) : null
          return (
            <div key={String(key)}>
              <div style={{ fontSize: 10.5, fontWeight: 600, color: C.t3, marginBottom: 2 }}>{label}</div>
              <div style={{ fontSize: 12.5, lineHeight: 1.4, color: val ? C.t1 : C.t3 }}>{val ?? '—'}</div>
            </div>
          )
        })}
      </div>
    </aside>
  )
}
